#!/usr/bin/env python3
"""Referee self-check (ORGANISERS ONLY - it reads the answer sheet).

Proves, in a live simulation, that the competition machinery progresses the way the rules say:
every rescue is confirmed, every clue is released by the right person, a rescue that follows its
clue earns the clue-led bonus, aftershocks are triggered, and ending in the base zone earns the
return and time bonuses. It places the rover at each survivor's approach point (Gazebo set_pose),
waits out the 2 s dwell and files a perfect report, clue sources before their targets.

  # terminal 1: simulator + referee only, no team code, manual start
  ros2 launch sparkx_bringup practice.launch.py world:=practice_small_day baseline:=false start_delay_s:=15.0
  # terminal 2
  python3 tools/referee_selfcheck.py --world-dir <world dir>

Exit code 0 when every expectation holds. Never run this during a scored run."""
import argparse
import json
import math
import os
import subprocess
import sys
import time

import rclpy
import yaml
from geometry_msgs.msg import PointStamped
from rclpy.node import Node

from sparkx_interfaces.msg import MissionEvent, MissionStatus
from sparkx_interfaces.srv import EndMission, ReportSurvivor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--world-dir', required=True)
    a = ap.parse_args()
    sc = yaml.safe_load(open(os.path.join(a.world_dir, 'private', 'scenario.yaml')))
    world = sc['world']
    st = sc['start']
    c0, s0 = math.cos(st['yaw']), math.sin(st['yaw'])

    def to_map(x, y):
        dx, dy = x - st['x'], y - st['y']
        return c0 * dx + s0 * dy, -s0 * dx + c0 * dy

    rclpy.init()
    n = Node('sparkx_referee_selfcheck')
    status, events = {}, []
    n.create_subscription(MissionStatus, '/sparkx/mission/status', lambda m: status.__setitem__('m', m), 5)
    n.create_subscription(MissionEvent, '/sparkx/mission/events', lambda m: events.append(m), 100)
    cli = n.create_client(ReportSurvivor, '/sparkx/mission/report_survivor')
    end = n.create_client(EndMission, '/sparkx/mission/end')

    def spin(sec):
        t0 = time.time()
        while time.time() - t0 < sec:
            rclpy.spin_once(n, timeout_sec=0.05)

    def sim_wait(sec):
        """Wait `sec` seconds of MISSION time (the dwell is counted in simulation time)."""
        t0 = status['m'].elapsed_s
        w0 = time.time()
        while status['m'].elapsed_s - t0 < sec and time.time() - w0 < 60:
            rclpy.spin_once(n, timeout_sec=0.05)

    def place(x, y, yaw):
        req = (f'name: "sparkx_ugv", position: {{x: {x}, y: {y}, z: 0.08}}, '
               f'orientation: {{z: {math.sin(yaw / 2)}, w: {math.cos(yaw / 2)}}}')
        subprocess.run(['gz', 'service', '-s', f'/world/{world}/set_pose', '--reqtype', 'gz.msgs.Pose', '--reptype',
                        'gz.msgs.Boolean', '--timeout', '5000', '--req', req], capture_output=True)

    print('waiting for the referee ...')
    t0 = time.time()
    while ('m' not in status or status['m'].state != MissionStatus.RUNNING) and time.time() - t0 < 120:
        rclpy.spin_once(n, timeout_sec=0.2)
    if 'm' not in status or status['m'].state != MissionStatus.RUNNING:
        print('FAIL: mission is not RUNNING (start it, or check /clock)')
        return 1
    cli.wait_for_service(10.0)

    by_id = {s['id']: s for s in sc['survivors']}
    target_of = {h['id']: h['target'] for h in sc['hints']}
    targets = set(target_of.values())
    # clue sources first, so that every clue is out before its target is rescued
    order, done = [], set()
    pending = list(sc['survivors'])
    while pending:
        ready = [s for s in pending if s['id'] not in targets or
                 all(h['source'] in done for h in sc['hints'] if h['target'] == s['id'])]
        s = (ready or pending)[0]
        order.append(s)
        done.add(s['id'])
        pending.remove(s)

    fails, released = [], set()
    for s in order:
        ax, ay = s['approach_points'][0]
        place(ax, ay, math.atan2(s['y'] - ay, s['x'] - ax))
        spin(1.0)
        sim_wait(3.5)                                             # dwell + report rate limit
        req = ReportSurvivor.Request()
        req.estimated_position = PointStamped()
        req.estimated_position.header.frame_id = 'map'
        req.estimated_position.point.x, req.estimated_position.point.y = to_map(s['x'], s['y'])
        req.detection_source, req.confidence = 'selfcheck', 1.0
        f = cli.call_async(req)
        rclpy.spin_until_future_complete(n, f, timeout_sec=20.0)
        r = f.result()
        if r is None:
            fails.append(f'{s["id"]}: no reply from the referee')
            continue
        got = sorted(h.hint_id for h in r.hints)
        want = sorted(s['releases'])
        clue_led = s['id'] in targets and any(target_of[h] == s['id'] for h in released)
        base = 100 + (50 if clue_led else 0)
        ok = r.success and r.survivor_id == s['id'] and got == want and base <= r.score_delta <= base + 20
        print(f'{"OK  " if ok else "FAIL"} {s["id"]} ({s["kind"]}, {s["posture"]}): {r.message[:70]}  points {r.score_delta:+d}'
              f'{"  [clue-led]" if clue_led else ""}  clues released {got}')
        if not ok:
            fails.append(f'{s["id"]}: success={r.success} id={r.survivor_id} released={got} expected={want} '
                         f'points={r.score_delta} expected {base}..{base + 20}')
        released.update(got)
    spin(3.0)
    n_shock = sum(1 for e in events if e.type == MissionEvent.AFTERSHOCK)
    want_shock = min(sc['aftershocks']['count'], len(sc['aftershocks']['candidates']))
    print(f'{"OK  " if n_shock == want_shock else "FAIL"} aftershocks spawned: {n_shock} (scenario allows {want_shock})')
    if n_shock != want_shock:
        fails.append(f'aftershocks {n_shock} != {want_shock}')

    place(st['x'], st['y'], st['yaw'])
    spin(1.0)
    sim_wait(2.5)
    before = status['m'].score
    f = end.call_async(EndMission.Request(reason='SELFCHECK'))
    rclpy.spin_until_future_complete(n, f, timeout_sec=20.0)
    r = f.result()
    spin(6.0)
    types = [e.type for e in events]
    ok = r is not None and r.success and r.in_base_zone and 'RETURN_TO_BASE' in types
    print(f'{"OK  " if ok else "FAIL"} EndMission in base zone: in_base={getattr(r, "in_base_zone", None)}  '
          f'return bonus {"yes" if "RETURN_TO_BASE" in types else "NO"}  time bonus {"yes" if "TIME_BONUS" in types else "no"}  '
          f'score {before} -> {getattr(r, "final_score", "?")}')
    if not ok:
        fails.append('EndMission / return bonus')
    m = status['m']
    ok = m.state == MissionStatus.FINISHED and m.survivors_rescued == len(order) and m.false_reports == 0
    print(f'{"OK  " if ok else "FAIL"} final status: {m.state_text}, rescued {m.survivors_rescued}/{len(order)}, '
          f'clues {m.hints_released}/{len(sc["hints"])}, false reports {m.false_reports}, score {m.score}')
    if not ok or m.hints_released != len(sc['hints']):
        fails.append('final status')
    print('\nSELF-CHECK ' + ('PASSED' if not fails else 'FAILED:\n  ' + '\n  '.join(fails)))
    n.destroy_node()
    rclpy.shutdown()
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
