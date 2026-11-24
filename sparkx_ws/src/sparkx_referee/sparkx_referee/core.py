"""ROS-free referee core: mission state, rescue verification, hints, penalties and scoring.

World frame = Gazebo world. Team "map" frame = robot start pose (x forward at start, z up).
"""
import math
import os
import time

import numpy as np
import yaml

from sparkx_worlds.geometry import BoxSet

from . import rules as R
from .physics import TEAM_TEXT as PHYSICS_TEXT, Watchdog

WAITING, RUNNING, PAUSED, FINISHED = 0, 1, 2, 3
STATE_TEXT = {0: 'WAITING', 1: 'RUNNING', 2: 'PAUSED', 3: 'FINISHED'}
CODES = dict(CONFIRMED=0, MISSION_NOT_RUNNING=1, NOT_STOPPED=2, NO_SURVIVOR_IN_RANGE=3, NO_LINE_OF_SIGHT=4,
             POSITION_MISMATCH=5, ALREADY_RESCUED=6, RATE_LIMITED=7, INVALID_REQUEST=8)
PENALIZED = {'NOT_STOPPED', 'NO_SURVIVOR_IN_RANGE', 'NO_LINE_OF_SIGHT', 'POSITION_MISMATCH', 'ALREADY_RESCUED'}
CAMERA_Z = 0.55


def yaw_of(q):
    return math.atan2(2 * (q[3] * q[2] + q[0] * q[1]), 1 - 2 * (q[1] ** 2 + q[2] ** 2))


class Pose2:
    def __init__(self, x=0.0, y=0.0, yaw=0.0):
        self.x, self.y, self.yaw = x, y, yaw

    def apply(self, px, py):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return self.x + c * px - s * py, self.y + s * px + c * py

    def inverse_apply(self, wx, wy):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        dx, dy = wx - self.x, wy - self.y
        return c * dx + s * dy, -s * dx + c * dy


class Referee:
    def __init__(self, world_dir, team='team', hide_total=False):
        self.world_dir = world_dir
        priv = os.path.join(world_dir, 'private')
        self.sc = yaml.safe_load(open(os.path.join(priv, 'scenario.yaml')))
        z = np.load(os.path.join(priv, 'occluders.npz'))
        rows, tags = z['rows'], [str(t) for t in z['tags']]
        keep = [i for i, t in enumerate(tags) if rows[i][2] + abs(rows[i][5]) / 2 >= 0.35]
        self.occ_rows = rows[keep]
        self.occ = BoxSet(self.occ_rows)
        self.gt_occ, self.gt_reach = z['occ'], z['reach']
        self.gt_origin, self.gt_res = tuple(z['origin']), float(z['res'])
        self.team, self.hide_total = team, hide_total
        st = self.sc['start']
        self.start = Pose2(st['x'], st['y'], st['yaw'])
        self.rs = self.sc['rescue']
        self.time_limit = float(self.sc['time_limit_s'])
        self.survivors = {s['id']: dict(s, rescued=False, near_since=None, late=False) for s in self.sc['survivors']}
        self.late_reports = 0          # survivors at which the report window ran out
        self.idle_penalties = 0
        self.idle_anchor = None        # (x, y, elapsed) where and when the rover last moved IDLE_MOVE_M
        self.hints = {h['id']: h for h in self.sc['hints']}
        self.hint_targets = {h['target'] for h in self.sc['hints']}
        self.state = WAITING
        self.elapsed = 0.0
        self.last_sim = None
        self.score_items = []          # (sim_elapsed, points, type, text, ref)
        self.events = []               # dict events for logs / dashboard
        self.released = []             # hint ids
        self.clue_area = {}            # hint id -> (wx, wy, r): the team's search area while its person was unseen
        a = self.sc.get('arena') or {}
        self.physics = Watchdog((a['xmin'], a['xmax'], a['ymin'], a['ymax']) if 'xmin' in a else None)
        self.clue_seen = set()
        self.clue_anchor = {}          # hint id -> where the team's search centre last settled
        self.clue_moves = {}           # hint id -> how often the team's search centre jumped
        self.clue_forfeit = set()      # hint ids whose area moved too often: no +50         # hint ids whose person the rover has seen since the clue was released
        self.rescue_order = []
        self.collisions = 0
        self.false_reports = 0
        self.health = 100.0
        self.pose = None               # world Pose2 + z, roll, pitch
        self.speed = (0.0, 0.0)
        self.still_since = None
        self.last_report = -1e9
        self.last_collision = {}
        self.contact_since = {}        # collision element -> start of the current continuous contact
        self.collision_log = []        # (t, collision element) for the evaluator; not shown to the team
        self.fire_accum = 0.0
        self.finish_reason = ''
        self.aftershocks_done = []
        self.trajectory = []           # (t, x, y, yaw) world
        self.team_pose_samples = []    # (t, world xy, team map xy)
        self.warned = set()
        self.submitted = None
        self.final_extra = {}

    # ------------------------------------------------------------------ helpers
    @property
    def score(self):
        return int(round(sum(p for _, p, *_ in self.score_items)))

    def add(self, pts, typ, text, ref=''):
        # the event shows how much the rounded total moved, so the events always add up to the final
        # score; the total itself is rounded only once, from the exact points
        before = self.score
        self.score_items.append((self.elapsed, pts, typ, text, ref))
        return self.event(typ, text, self.score - before, ref)

    def event(self, typ, text, pts=0, ref=''):
        e = dict(t=round(self.elapsed, 2), wall=time.time(), type=typ, description=text, score_delta=int(pts),
                 ref_id=ref)
        self.events.append(e)
        return e

    def map_to_world(self, mx, my):
        return self.start.apply(mx, my)

    def world_to_map(self, wx, wy):
        return self.start.inverse_apply(wx, wy)

    def los(self, p0, p1, own):
        idx, hit = self.occ.segment_hits(p0, p1, shrink=0.02)
        if not len(idx) or not hit.any():
            return True
        own = np.asarray(own)
        for k in idx[hit]:
            if not np.allclose(self.occ_rows[k], own, atol=1e-3):
                return False
        return True

    # ------------------------------------------------------------------ lifecycle
    def start_mission(self):
        self.physics.reset()
        if self.state in (WAITING, PAUSED):
            self.state = RUNNING
            return [self.event('MISSION_STARTED' if not self.events else 'MISSION_RESUMED', 'Mission running')]
        return []

    def pause(self):
        if self.state == RUNNING:
            self.state = PAUSED
            return [self.event('MISSION_PAUSED', 'Paused by organizer')]
        return []

    def finish(self, reason):
        if self.state == FINISHED:
            return []
        self.state = FINISHED
        self.finish_reason = reason
        return [self.event('MISSION_FINISHED', reason)]

    def cmd_enabled(self):
        return self.state == RUNNING and self.health > 0

    # ------------------------------------------------------------------ periodic update
    def update(self, sim_t, pose=None, twist=None):
        """pose=(x, y, z, qx, qy, qz, qw) world; twist=(vx, wz). Returns list of new events."""
        ev = []
        dt = 0.0 if self.last_sim is None else max(0.0, sim_t - self.last_sim)
        self.last_sim = sim_t
        if pose is not None:
            x, y, z, qx, qy, qz, qw = pose
            roll = math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy))
            pitch = math.asin(max(-1, min(1, 2 * (qw * qy - qz * qx))))
            self.pose = dict(p=Pose2(x, y, yaw_of((qx, qy, qz, qw))), z=z, roll=roll, pitch=pitch)
        if twist is not None:
            self.speed = twist
        if self.state != RUNNING or self.pose is None:
            return ev
        self.elapsed += dt
        p = self.pose['p']
        if not self.trajectory or sim_t - self.trajectory[-1][0] >= 0.5:
            self.trajectory.append((sim_t, p.x, p.y, p.yaw))
        v, w = self.speed
        still = abs(v) <= self.rs['max_stop_speed_mps'] and abs(w) <= 2 * self.rs['max_stop_speed_mps']
        if still:
            self.still_since = self.still_since if self.still_since is not None else self.elapsed
        else:
            self.still_since = None
        # fires: health drops for every fire the rover is in; points are -2 per second inside any fire,
        # counted once however many fires overlap, and every whole second is charged even after a gap
        # between updates
        hot = None
        for f in self.sc['fires']:
            d = math.hypot(p.x - f['x'], p.y - f['y'])
            if d < f['hazard_radius']:
                rate = R.HEALTH['fire_danger_per_s'] if d < f['danger_radius'] else R.HEALTH['fire_hazard_per_s']
                self.health = max(0.0, self.health - rate * dt)
                if hot is None or d < hot[0]:
                    hot = (d, f)
        if hot is not None:
            f = hot[1]
            self.fire_accum += dt
            while self.fire_accum >= 1.0:
                self.fire_accum -= 1.0
                ev.append(self.add(R.SCORING['fire_damage_per_s'], 'FIRE_DAMAGE',
                                   f'Robot inside fire hazard ({f["id"]}), health {self.health:.0f}%', f['id']))
        ev += self.timing_rules(p)
        for kind in self.physics.update(sim_t, p.x, p.y, self.pose['z']):
            ev.append(self.event('PHYSICS_ANOMALY', PHYSICS_TEXT[kind], 0, kind))
        self.clue_sightings(p)
        # flip
        if abs(self.pose['roll']) > R.FLIP_ANGLE_RAD or abs(self.pose['pitch']) > R.FLIP_ANGLE_RAD:
            ev.append(self.add(R.SCORING['flip'], 'ROBOT_FLIPPED', 'Robot rolled over'))
            self.health = 0.0
        if self.health <= 0.0:
            ev.append(self.event('ROBOT_DISABLED', 'Robot disabled (health 0)'))
            ev += self.finish('ROBOT_DISABLED')
            return ev
        # time
        rem = self.time_limit - self.elapsed
        for w_s in R.TIME_WARNINGS_S:
            if rem <= w_s and w_s not in self.warned:
                self.warned.add(w_s)
                ev.append(self.event('TIME_WARNING', f'{int(w_s)} s remaining'))
        if rem <= 0:
            ev += self.finish('TIME_LIMIT')
        return ev

    def timing_rules(self, p):
        """Rules v1.2: the report window at a survivor and the idle limit. Both run on mission time."""
        ev = []
        if R.REPORT_WINDOW_S > 0:
            for s in self.survivors.values():
                if s['rescued'] or s['late']:
                    continue
                near = math.hypot(s['x'] - p.x, s['y'] - p.y) <= self.rs['radius_m'] and \
                    self.los((p.x, p.y, CAMERA_Z), (s['x'], s['y'], s['z']), s['body'])
                if not near:
                    # the clock resets only after REPORT_RESET_S outside the zone, so hopping out for a
                    # moment does not restart it (v1.4)
                    s['away_since'] = s.get('away_since') if s.get('away_since') is not None else self.elapsed
                    if self.elapsed - s['away_since'] >= R.REPORT_RESET_S:
                        s['near_since'] = None
                    continue
                s['away_since'] = None
                if s['near_since'] is None:
                    s['near_since'] = self.elapsed
                elif self.elapsed - s['near_since'] > R.REPORT_WINDOW_S:
                    s['late'] = True
                    self.late_reports += 1
                    ev.append(self.add(R.SCORING['late_report'], 'LATE_REPORT',
                                       f'At {s["id"]} for more than {R.REPORT_WINDOW_S:.0f} s without a confirmed rescue',
                                       s['id']))
        if R.IDLE_LIMIT_S > 0:
            a = self.idle_anchor
            if a is None or math.hypot(p.x - a[0], p.y - a[1]) >= R.IDLE_MOVE_M:
                self.idle_anchor = (p.x, p.y, self.elapsed)
            elif self.elapsed - a[2] >= R.IDLE_LIMIT_S:
                self.idle_anchor = (a[0], a[1], self.elapsed)      # the next penalty needs another full limit
                self.idle_penalties += 1
                ev.append(self.add(R.SCORING['idle'], 'IDLE',
                                   f'Rover has not moved {R.IDLE_MOVE_M} m in {R.IDLE_LIMIT_S:.0f} s'))
        return ev

    def on_contact(self, other):
        """other: 'model::link::collision' of the entity touching the chassis."""
        if self.state != RUNNING:
            return []
        model = other.split('::')[0]
        if model in ('ground_plane',) or model.startswith('sparkx_ugv'):
            return []
        # obstacles are counted per collision element, not per model: one model can be a whole city block
        key = model if model.startswith('survivor_') else other
        last = self.last_collision.get(key, -1e9)
        if model.startswith('survivor_'):
            # at most one penalty per survivor every SURVIVOR_CONTACT_DEBOUNCE_S
            if self.elapsed - last < R.SURVIVOR_CONTACT_DEBOUNCE_S:
                return []
            self.last_collision[key] = self.elapsed
        else:
            # a new event needs 1 s without contact, or COLLISION_REPEAT_S of continuous contact (v1.4)
            self.last_collision[key] = self.elapsed
            if self.elapsed - last < R.COLLISION_DEBOUNCE_S:
                since = self.contact_since.setdefault(key, self.elapsed)
                if self.elapsed - since < R.COLLISION_REPEAT_S:
                    return []
            self.contact_since[key] = self.elapsed
        if model.startswith('survivor_'):
            return [self.add(R.SCORING['survivor_contact'], 'SURVIVOR_CONTACT', 'Robot touched a person')]
        self.collisions += 1
        # the text never names the object: "mannequin_d01" would tell a team which figure is a decoy
        self.collision_log.append((round(self.elapsed, 1), other))
        return [self.add(R.SCORING['collision'], 'COLLISION', 'Collision with an obstacle')]

    def intervention(self, note):
        self.physics.reset()            # an organiser may move the rover
        return [self.add(R.SCORING['intervention'], 'INTERVENTION', note or 'Manual intervention')]

    # ------------------------------------------------------------------ rescue
    def report(self, frame, ex, ey, team_pose=None, source='', confidence=0.0):
        """team_pose: (mx, my, myaw) team map->base_link at report time (or None).
        Returns (code_name, message, survivor_id, pts, err, hints, events)."""
        ev = []
        if self.state != RUNNING:
            return 'MISSION_NOT_RUNNING', 'mission is not running', '', 0, -1.0, [], ev
        if team_pose is not None and not all(map(math.isfinite, team_pose)):
            team_pose = None                     # a broken team pose is treated as no pose (fails closed)
        if frame not in ('map', 'base_link') or not all(map(math.isfinite, (ex, ey))):
            return 'INVALID_REQUEST', 'frame_id must be map or base_link', '', 0, -1.0, [], ev
        if self.elapsed - self.last_report < R.REPORT_RATE_LIMIT_S:
            return 'RATE_LIMITED', f'max one report per {R.REPORT_RATE_LIMIT_S:.0f} s', '', 0, -1.0, [], ev
        self.last_report = self.elapsed
        p = self.pose['p']
        # estimate in world, robot-relative (drift free) + absolute (map-frame) versions
        if frame == 'base_link':
            rel = (ex, ey)
            abs_w = p.apply(ex, ey)
        else:
            abs_w = self.map_to_world(ex, ey)
            if team_pose is not None:
                tp = Pose2(*team_pose)
                rel = tp.inverse_apply(ex, ey)
            else:
                rel = p.inverse_apply(*abs_w)
        rel_w = p.apply(*rel)
        code, msg, sid = None, '', ''
        still_for = 0.0 if self.still_since is None else self.elapsed - self.still_since
        cands = sorted(self.survivors.values(), key=lambda s: math.hypot(s['x'] - p.x, s['y'] - p.y))
        in_range = [s for s in cands if math.hypot(s['x'] - p.x, s['y'] - p.y) <= self.rs['radius_m']]
        if still_for < self.rs['stop_dwell_s']:
            code, msg = 'NOT_STOPPED', f'robot must be stationary for {self.rs["stop_dwell_s"]} s ({still_for:.1f} s)'
        elif not in_range:
            code, msg = 'NO_SURVIVOR_IN_RANGE', f'no survivor within {self.rs["radius_m"]} m of the robot'
        else:
            match = min(in_range, key=lambda s: math.hypot(s['x'] - rel_w[0], s['y'] - rel_w[1]))
            err_rel = math.hypot(match['x'] - rel_w[0], match['y'] - rel_w[1])
            unresc = [s for s in in_range if not s['rescued']]
            if match['rescued'] and (not unresc or err_rel <= self.rs['report_tolerance_m']):
                code, msg, sid = 'ALREADY_RESCUED', f'{match["id"]} was already rescued', match['id']
            else:
                match = min(unresc, key=lambda s: math.hypot(s['x'] - rel_w[0], s['y'] - rel_w[1]))
                err_rel = math.hypot(match['x'] - rel_w[0], match['y'] - rel_w[1])
                if not self.los((p.x, p.y, CAMERA_Z), (match['x'], match['y'], match['z']), match['body']):
                    code, msg = 'NO_LINE_OF_SIGHT', 'no line of sight between robot and survivor'
                elif not err_rel <= self.rs['report_tolerance_m']:      # also refuses NaN (fails closed)
                    # no distance in the message: it would let a team home in by trial reports (v1.4)
                    code, msg = 'POSITION_MISMATCH', f'reported position is more than {self.rs["report_tolerance_m"]:.1f} m off'
                else:
                    code, sid = 'CONFIRMED', match['id']
        if code != 'CONFIRMED':
            pts = 0
            if code in PENALIZED:
                self.false_reports += 1
                e = self.add(R.SCORING['false_report'], 'RESCUE_REJECTED', f'{code}: {msg}', sid)
                pts = e['score_delta']
                ev.append(e)
            else:
                ev.append(self.event('RESCUE_REJECTED', f'{code}: {msg}', 0, sid))
            return code, msg, sid, pts, -1.0, [], ev
        s = self.survivors[sid]
        s['rescued'] = True
        s['rescued_at'] = self.elapsed
        self.rescue_order.append(sid)
        err_abs = math.hypot(s['x'] - abs_w[0], s['y'] - abs_w[1])
        acc = R.SCORING['accuracy_bonus_max'] * max(0.0, 1.0 - err_rel / self.rs['report_tolerance_m'])
        pts = R.SCORING['rescue'] + acc
        text = f'{sid} rescued (error {err_rel:.2f} m, map error {err_abs:.2f} m)'
        if self.clue_led(sid, team_pose):
            pts += R.SCORING['rescue_via_hint']
            text += ' - clue-led rescue'
        e = self.add(pts, 'RESCUE_CONFIRMED', text, sid)
        ev.append(e)
        new_hints = []
        for hid in s.get('releases', []):
            if hid not in self.released:
                self.released.append(hid)
                self.hints[hid]['released_at'] = self.elapsed
                new_hints.append(self.hints[hid])
                ev.append(self.event('HINT_RELEASED', self.hints[hid]['text'], 0, hid))
        return 'CONFIRMED', text, sid, e['score_delta'], err_abs, new_hints, ev

    # ------------------------------------------------------------------ clue-led rescues (rules v1.3)
    def clue_sightings(self, p):
        """Freeze a clue's search area once the rover has seen the clue's person (clear line of sight
        within CLUE_SEEN_RANGE_M): from then on the team could find the person without the clue."""
        for hid in self.released:
            if hid in self.clue_seen:
                continue
            s = self.survivors.get(self.hints[hid]['target'])
            if s is None or s['rescued']:
                continue
            if math.hypot(s['x'] - p.x, s['y'] - p.y) <= R.CLUE_SEEN_RANGE_M and \
                    self.los((p.x, p.y, CAMERA_Z), (s['x'], s['y'], s['z']), s['body']):
                self.clue_seen.add(hid)

    def team_clues(self, clues, team_pose=None):
        """clues: [(hint_id, status, cx, cy, radius)] from /team/clues, centre in the team's map frame.
        team_pose: (mx, my, myaw) team map->base_link now, so SLAM drift is not punished. Silent: no
        event is raised, so a team cannot probe where a person is by publishing areas."""
        if self.state != RUNNING or self.pose is None:
            return
        p, done = self.pose['p'], set()
        for hid, status, cx, cy, r in clues:
            if hid in done:                      # only the first entry per clue counts
                continue
            done.add(hid)
            if hid not in self.released or hid in self.clue_seen or status != 'SEARCHING':
                continue
            if not all(map(math.isfinite, (cx, cy, r))) or not 0.0 < r <= R.CLUE_MAX_SEARCH_RADIUS_M:
                continue
            if hid in self.clue_forfeit:
                continue
            # kept in the team's own map frame: converting with a true pose and a TF taken at slightly
            # different times would make a fixed area appear to move while the rover turns
            wx, wy = cx, cy
            anchor = self.clue_anchor.get(hid)
            if anchor is None:
                self.clue_anchor[hid] = (wx, wy)
            elif math.hypot(wx - anchor[0], wy - anchor[1]) > R.CLUE_MOVE_M:
                # a search area that keeps moving (e.g. one that follows the rover) is not a resolved clue;
                # drift is measured from where the area last settled, so small steps add up
                self.clue_anchor[hid] = (wx, wy)
                self.clue_moves[hid] = self.clue_moves.get(hid, 0) + 1
                if self.clue_moves[hid] > R.CLUE_MAX_MOVES:
                    self.clue_forfeit.add(hid)
                    self.clue_area.pop(hid, None)
                    continue
            self.clue_area[hid] = (wx, wy, r)

    def clue_led(self, sid, team_pose=None):
        """True when a released clue points at survivor sid and the team's last search area for it,
        published before the rover saw the person, holds the person."""
        s = self.survivors[sid]
        for hid in self.released:
            if self.hints[hid]['target'] != sid or hid not in self.clue_area:
                continue
            mx, my, r = self.clue_area[hid]
            # to the world through the rover's own map->base_link at the report (it has stood still 2 s),
            # so SLAM drift does not count against the team
            if team_pose is not None:
                wx, wy = self.pose['p'].apply(*Pose2(*team_pose).inverse_apply(mx, my))
            else:
                wx, wy = self.map_to_world(mx, my)
            if math.hypot(s['x'] - wx, s['y'] - wy) <= r + R.CLUE_AREA_SLACK_M:
                return True
        return False

    # ------------------------------------------------------------------ aftershocks
    def aftershock_due(self):
        a = self.sc.get('aftershocks') or {}
        if self.state != RUNNING or len(self.aftershocks_done) >= a.get('count', 0) or not a.get('candidates'):
            return None
        k = len(self.aftershocks_done)
        trig = (len(self.rescue_order) >= a['trigger_after_rescues'] * (k + 1) or
                self.elapsed >= a['trigger_time_fraction'] * self.time_limit * (k + 1))
        if not trig:
            return None
        p = self.pose['p']
        done = {c['id'] for c in self.aftershocks_done}
        ok = [c for c in a['candidates'] if c['id'] not in done and
              math.hypot(c['x'] - p.x, c['y'] - p.y) >= a['min_robot_distance_m']]
        if not ok:
            return None
        # prefer a segment the robot already drove through (forces replanning on known routes)
        def visited(c):
            return any(math.hypot(tx - c['x'], ty - c['y']) < 6 for _, tx, ty, _ in self.trajectory)
        ok.sort(key=lambda c: (not visited(c), math.hypot(c['x'] - p.x, c['y'] - p.y)))
        return ok[0]

    def apply_aftershock(self, cand):
        self.aftershocks_done.append(cand)
        rows = np.vstack([self.occ_rows, np.array(cand['rows'], float)])
        self.occ_rows = rows
        self.occ = BoxSet(rows)
        return [self.event('AFTERSHOCK', 'Aftershock! Structural collapse reported - some routes may be blocked',
                           0, cand['id'])]

    # ------------------------------------------------------------------ end
    def end_mission(self, reason):
        if self.state not in (RUNNING, PAUSED):
            return False, 'mission not running', False, self.score, []
        p = self.pose['p']
        in_base = math.hypot(p.x - self.start.x, p.y - self.start.y) <= self.rs['base_zone_radius_m']
        ev = []
        if in_base and len(self.rescue_order) >= R.SCORING['return_requires_rescues']:
            ev.append(self.add(R.SCORING['return_to_base'], 'RETURN_TO_BASE', 'Robot returned to base'))
            if len(self.rescue_order) == len(self.survivors):
                mins = int(max(0.0, self.time_limit - self.elapsed) // 60)
                if mins:
                    ev.append(self.add(R.SCORING['time_bonus_per_min'] * mins, 'TIME_BONUS',
                                       f'All survivors rescued, {mins} min left'))
        ev += self.finish(f'END_MISSION:{reason}' + (' (in base)' if in_base else ' (outside base)'))
        return True, 'mission ended', in_base, self.score, ev

    def status(self):
        return dict(state=self.state, state_text=STATE_TEXT[self.state], team=self.team,
                    world=self.sc['world'], elapsed=self.elapsed, time_limit=self.time_limit,
                    remaining=max(0.0, self.time_limit - self.elapsed), score=self.score,
                    rescued=len(self.rescue_order), total=0 if self.hide_total else len(self.survivors),
                    hints=len(self.released), collisions=self.collisions, false_reports=self.false_reports,
                    late_reports=self.late_reports, idle_penalties=self.idle_penalties,
                    health=self.health, cmd_enabled=self.cmd_enabled(), finish_reason=self.finish_reason)
