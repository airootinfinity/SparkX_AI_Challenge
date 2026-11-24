#!/usr/bin/env python3
"""Self-test of the timing rules and the clue-led rescue rule in the referee core (no simulator, no ROS).

  python3 hosting/test_timing_rules.py

Drives a simulated rover pose through the referee of THIS stack on a practice world and checks the
report window, the idle limit and the clue bonus, including the cases that must NOT be penalised
or paid.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.join(os.path.dirname(HERE), 'sparkx_ws')
for pkg in ('sparkx_worlds', 'sparkx_referee'):
    sys.path.insert(0, os.path.join(WS, 'src', pkg))
from sparkx_referee import core, rules as R  # noqa: E402

WORLD = os.path.join(WS, 'src', 'sparkx_worlds', 'worlds', 'practice_small_day')
FAILED = []


def fresh():
    ref = core.Referee(WORLD)
    ref.state = core.RUNNING
    ref.t = 0.0
    return ref


def hold(ref, x, y, seconds, yaw=0.0, wiggle=0.0):
    """Keep the rover at (x, y) for `seconds` of mission time; returns the timing events raised.
    wiggle > 0 moves it back and forth by that much every 20 s (it is 'moving' but stays put)."""
    out = []
    for k in range(int(seconds / 0.05)):
        ref.t += 0.05
        dx = wiggle if wiggle and int(ref.t / 20) % 2 else 0.0
        ev = ref.update(ref.t, (x + dx, y, 0.13, 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)), (0.0, 0.0))
        out += [e['type'] for e in ev if e['type'] in ('LATE_REPORT', 'IDLE')]
    return out


def approach_point(ref, s, dist):
    """A point `dist` m from survivor s with a clear line of sight, or None."""
    for k in range(72):
        a = 2 * math.pi * k / 72
        x, y = s['x'] + dist * math.cos(a), s['y'] + dist * math.sin(a)
        if ref.los((x, y, core.CAMERA_Z), (s['x'], s['y'], s['z']), s['body']):
            return x, y
    return None


def expect(name, got, want):
    ok = got == want
    print(f'  {"ok  " if ok else "FAIL"} {name}: {got}' + ('' if ok else f'   (wanted {want})'))
    if not ok:
        FAILED.append(name)


def main():
    print(f'rules {R.RULES_VERSION}: report window {R.REPORT_WINDOW_S} s, idle limit {R.IDLE_LIMIT_S} s / {R.IDLE_MOVE_M} m')
    ref = fresh()
    s = next(v for v in ref.survivors.values() if approach_point(ref, v, 1.5))
    near, far = approach_point(ref, s, 1.5), approach_point(ref, s, 1.5)
    far = (s['x'] + (near[0] - s['x']) * 3.0, s['y'] + (near[1] - s['y']) * 3.0)      # 4.5 m away, same direction

    ref = fresh()
    expect('9 s at a survivor, then leave for 6 s: no penalty', hold(ref, *near, 9.0) + hold(ref, *far, 6.0), [])
    expect('back for another 9 s (clock was reset): no penalty', hold(ref, *near, 9.0), [])
    expect('stay to 11 s: one LATE_REPORT', hold(ref, *near, 2.0), ['LATE_REPORT'])
    expect('stay 30 s more: not charged twice for the same survivor', hold(ref, *near, 30.0, wiggle=0.6), [])
    expect('score after one late report', ref.score, R.SCORING['late_report'])

    ref = fresh()
    expect('hop out for 0.5 s every 9 s: the clock keeps running (v1.4)',
           hold(ref, *near, 9.0) + hold(ref, *far, 0.5) + hold(ref, *near, 3.0), ['LATE_REPORT'])

    ref = fresh()
    hold(ref, *near, 4.0)
    ref.still_since = ref.elapsed - 3.0
    code = ref.report('base_link', *ref.pose['p'].inverse_apply(s['x'], s['y']))[0]
    expect('report after 4 s is confirmed', code, 'CONFIRMED')
    expect('staying 30 s beside a rescued survivor: no LATE_REPORT', hold(ref, *near, 30.0, wiggle=0.6), [])

    ref = fresh()
    expect('2.5 m away for 30 s (outside the zone): no penalty',
           hold(ref, s['x'] + (near[0] - s['x']) * 2.5 / 1.5, s['y'] + (near[1] - s['y']) * 2.5 / 1.5, 30.0, wiggle=0.6), [])

    ref = fresh()
    expect('standing 59 s: no IDLE', hold(ref, *far, 59.0), [])
    expect('standing to 61 s: one IDLE', hold(ref, *far, 2.0), ['IDLE'])
    expect('standing 60 s more: a second IDLE', hold(ref, *far, 60.0), ['IDLE'])
    expect('moving 0.6 m every 20 s for 3 min: no IDLE', hold(ref, far[0] + 5.0, far[1], 180.0, wiggle=0.6), [])
    expect('score after two idle penalties', ref.score, 2 * R.SCORING['idle'])

    ref = fresh()
    ref.state = core.PAUSED
    expect('paused for 5 min: nothing is charged', hold(ref, *near, 300.0), [])
    clue_tests()
    print('ALL PASSED' if not FAILED else f'{len(FAILED)} FAILED: {FAILED}')
    return 1 if FAILED else 0


def rescue(ref, s):
    """Drive next to survivor s, stand still and report it. Returns (code, points)."""
    hold(ref, *approach_point(ref, s, 1.5), 2.5)
    ref.still_since, ref.last_report = ref.elapsed - 3.0, -1e9
    r = ref.report('base_link', *ref.pose['p'].inverse_apply(s['x'], s['y']))
    return r[0], r[3]


def clue_tests():
    """Rules v1.3: +50 only if the team's own search area for the clue held the person before the rover
    could see them. The practice world: rescuing S03 releases clue H01, which points at S01."""
    print(f'clue rule: search radius <= {R.CLUE_MAX_SEARCH_RADIUS_M} m, seen = line of sight within {R.CLUE_SEEN_RANGE_M} m')
    base = R.SCORING['rescue']

    def setup():
        ref = fresh()
        s1, s3 = ref.survivors['S01'], ref.survivors['S03']
        code, _ = rescue(ref, s3)
        assert code == 'CONFIRMED' and 'H01' in ref.released, 'setup: S03 rescue must release H01'
        return ref, s1

    def area(ref, s, off=2.0, r=4.0, hid='H01', status='SEARCHING'):
        mx, my = ref.world_to_map(s['x'] + off, s['y'])
        ref.team_clues([(hid, status, mx, my, r)])

    def bonus(pts):
        return pts - base >= R.SCORING['rescue_via_hint']

    ref, s1 = setup()
    area(ref, s1)
    code, pts = rescue(ref, s1)
    expect('clue area placed on the person before seeing them: +50', (code, bonus(pts)), ('CONFIRMED', True))

    ref, s1 = setup()
    code, pts = rescue(ref, s1)
    expect('clue released, person found without publishing a search area: no +50', bonus(pts), False)

    ref, s1 = setup()
    hold(ref, *approach_point(ref, s1, 5.0), 1.0)
    area(ref, s1)
    code, pts = rescue(ref, s1)
    expect('search area published only after the rover saw the person: no +50', bonus(pts), False)

    ref, s1 = setup()
    area(ref, s1, off=20.0)
    code, pts = rescue(ref, s1)
    expect('search area 20 m off: no +50', bonus(pts), False)

    ref, s1 = setup()
    area(ref, s1, r=40.0)
    code, pts = rescue(ref, s1)
    expect('search radius 40 m (covers half the map): no +50', bonus(pts), False)

    ref, s1 = setup()
    area(ref, s1, status='LANDMARK_UNKNOWN')
    code, pts = rescue(ref, s1)
    expect('area sent with a status other than SEARCHING: no +50', bonus(pts), False)

    ref, s1 = setup()
    area(ref, s1, off=30.0)
    hold(ref, *approach_point(ref, s1, 5.0), 1.0)
    area(ref, s1)
    code, pts = rescue(ref, s1)
    expect('wrong area, then moved onto the person once in sight: no +50', bonus(pts), False)

    ref, s1 = setup()
    mx, my = ref.world_to_map(s1['x'], s1['y'])
    ref.team_clues([('H01', 'SEARCHING', mx + 30.0, my, 4.0), ('H01', 'SEARCHING', mx, my, 4.0)])
    code, pts = rescue(ref, s1)
    expect('two areas for the same clue in one message: only the first counts', bonus(pts), False)

    ref = fresh()
    rescue(ref, ref.survivors['S01'])
    code, pts = rescue(ref, ref.survivors['S03'])
    expect('person rescued before their clue was released: no +50', bonus(pts), False)


if __name__ == '__main__':
    sys.exit(main())
