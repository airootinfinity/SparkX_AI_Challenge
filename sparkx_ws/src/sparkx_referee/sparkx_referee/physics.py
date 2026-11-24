"""Physics watchdog (rules v1.4): flags rover motion that the platform cannot produce.

The rover's true pose arrives about 30 times a second. Honest driving is limited by the drive plugin
(1.0 m/s, 1.5 m/s^2) and the referee's gate; the ground is flat. Anything else - a jump between two
samples, sustained overspeed, the rover off the ground, outside the arena, moving while the gate
commands zero, the simulator frozen - means something other than the team's /cmd_vel moved the rover
(direct simulator access, a physics glitch). Each kind is recorded once per episode as a
PHYSICS_ANOMALY: no points, but the run is marked for review in summary.json and on the dashboard.
The team only ever sees a fixed sentence without numbers.
"""
import math

TELEPORT_STEP_M = 0.20          # plus MAX_SPEED * dt: an honest 30 Hz step is about 0.03 m
MAX_SPEED_MPS = 1.4             # sustained (1 s window) speed above this: the plugin limit is 1.0 m/s
OFF_GROUND_M = 0.20             # chassis clearance is 0.12 m; the ground is flat
OUT_OF_ARENA_M = 0.5            # beyond the arena's inner edge
UNCOMMANDED_MPS = 0.35          # faster than the highest gated command of the last 1.5 s by this much
STALL_WALL_S = 5.0              # simulator time not advancing for this long (wall clock) while running
HOLD_S = 0.5                    # a condition must last this long (sim time) before it counts
REARM_S = 2.0                   # ... and be clear this long before the same kind can count again

TEAM_TEXT = {
    'TELEPORT': 'The rover moved in a way the platform cannot drive; this run will be reviewed.',
    'OVERSPEED': 'The rover moved faster than the platform allows; this run will be reviewed.',
    'OFF_GROUND': 'The rover left the ground; this run will be reviewed.',
    'OUT_OF_ARENA': 'The rover left the arena; this run will be reviewed.',
    'UNCOMMANDED_MOTION': 'The rover moved without a matching command; this run will be reviewed.',
    'SIM_STALLED': 'The simulation stopped advancing; this run will be reviewed.',
}


class Watchdog:
    def __init__(self, arena=None):
        self.arena = arena              # (xmin, xmax, ymin, ymax) or None
        self.prev = None                # (t, x, y, z)
        self.window = []                # (t, x, y) for the speed window
        self.cmds = []                  # (t, |v| commanded by the gate)
        self.z_ref = None
        self.z_samples = []
        self.active = {}                # kind -> (since, last_true)
        self.flags = []                 # (t, kind, detail)
        self.counted = {}
        self.max_speed = 0.0
        self.max_lift = 0.0

    def reset(self):
        """After a pause, an organiser intervention or the start: the next sample is a new baseline."""
        self.prev, self.window = None, []

    def command(self, t, v):
        self.cmds.append((t, abs(v)))
        self.cmds = [c for c in self.cmds if t - c[0] <= 1.5]

    def _cond(self, t, kind, true, detail):
        st = self.active.get(kind)
        if true:
            if st is None:
                self.active[kind] = [t, t, False]
                st = self.active[kind]
            st[1] = t
            if not st[2] and t - st[0] >= HOLD_S:
                st[2] = True
                self.flags.append((round(t, 2), kind, detail))
                self.counted[kind] = self.counted.get(kind, 0) + 1
                return kind
        elif st is not None and t - st[1] >= REARM_S:
            del self.active[kind]
        return None

    def update(self, t, x, y, z):
        """Feed one true pose (sim time t). Returns a list of anomaly kinds raised now."""
        out = []
        if len(self.z_samples) < 15:
            self.z_samples.append(z)
            if len(self.z_samples) == 15:
                self.z_ref = min(0.20, max(-0.05, sorted(self.z_samples)[7]))
        if self.prev is not None:
            pt, px, py, _ = self.prev
            dt = t - pt
            step = math.hypot(x - px, y - py)
            if dt <= 0 and step > TELEPORT_STEP_M or dt > 0 and step > TELEPORT_STEP_M + 2.0 * dt:
                self.flags.append((round(t, 2), 'TELEPORT', f'{step:.2f} m in {max(dt, 0):.3f} s'))
                self.counted['TELEPORT'] = self.counted.get('TELEPORT', 0) + 1
                out.append('TELEPORT')
                self.window = []
        self.prev = (t, x, y, z)
        self.window.append((t, x, y))
        self.window = [w for w in self.window if t - w[0] <= 1.0]
        speed = 0.0
        if len(self.window) > 2 and t - self.window[0][0] >= 0.8:
            path = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(self.window, self.window[1:]))
            speed = path / (t - self.window[0][0])
            self.max_speed = max(self.max_speed, speed)
        out.append(self._cond(t, 'OVERSPEED', speed > MAX_SPEED_MPS, f'{speed:.2f} m/s'))
        cmd = max([c[1] for c in self.cmds], default=0.0)
        out.append(self._cond(t, 'UNCOMMANDED_MOTION', speed > cmd + UNCOMMANDED_MPS,
                              f'{speed:.2f} m/s, gate {cmd:.2f} m/s'))
        if self.z_ref is not None:
            lift = z - self.z_ref
            self.max_lift = max(self.max_lift, lift)
            out.append(self._cond(t, 'OFF_GROUND', lift > OFF_GROUND_M, f'{lift:.2f} m up'))
        if self.arena:
            x0, x1, y0, y1 = self.arena
            outside = x < x0 - OUT_OF_ARENA_M or x > x1 + OUT_OF_ARENA_M or y < y0 - OUT_OF_ARENA_M or y > y1 + OUT_OF_ARENA_M
            out.append(self._cond(t, 'OUT_OF_ARENA', outside, f'({x:.1f}, {y:.1f})'))
        return [k for k in out if k]

    def stalled(self, t_wall_since_advance, sim_t):
        """Called on a wall-clock timer while the mission runs."""
        if t_wall_since_advance >= STALL_WALL_S and 'SIM_STALLED' not in self.active:
            self.active['SIM_STALLED'] = [sim_t, sim_t, True]
            self.flags.append((round(sim_t, 2), 'SIM_STALLED', f'no simulation time for {t_wall_since_advance:.0f} s'))
            self.counted['SIM_STALLED'] = self.counted.get('SIM_STALLED', 0) + 1
            return 'SIM_STALLED'
        if t_wall_since_advance < 1.0:
            self.active.pop('SIM_STALLED', None)
        return None

    def summary(self):
        return dict(anomalies=[dict(t=t, kind=k, detail=d) for t, k, d in self.flags[:200]], counts=dict(self.counted),
                    max_speed_mps=round(self.max_speed, 2), max_lift_m=round(self.max_lift, 3),
                    z_ref=None if self.z_ref is None else round(self.z_ref, 3), needs_review=bool(self.flags))
