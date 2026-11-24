#!/usr/bin/env python3
"""Replay a finished run through the referee's timing rules (report window, idle limit).

  python3 hosting/replay_rules.py <run folder with summary.json + events.jsonl> [more run folders ...]

Use it to see what a rule change would have done to runs that were already made: it feeds the
logged rover track (one pose every 0.5 s) and the logged rescue times into the referee core of
THIS stack and prints every LATE_REPORT / IDLE the current rules would raise. No simulator needed.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.join(os.path.dirname(HERE), 'sparkx_ws')
for pkg in ('sparkx_worlds', 'sparkx_referee'):
    sys.path.insert(0, os.path.join(WS, 'src', pkg))

from sparkx_referee import core, rules as R  # noqa: E402


def replay(run, worlds=os.path.join(WS, 'src', 'sparkx_worlds', 'worlds')):
    s = json.load(open(os.path.join(run, 'summary.json')))
    ev = [json.loads(l) for l in open(os.path.join(run, 'events.jsonl'))]
    wd = os.path.join(worlds, s['world'])
    ref = core.Referee(wd)
    ref.state = core.RUNNING
    rescues = sorted((e['t'], e['ref_id']) for e in ev if e['type'] == 'RESCUE_CONFIRMED')
    out, stays = [], {}
    for t, x, y, yaw in s['trajectory']:
        while rescues and rescues[0][0] <= ref.elapsed:
            sid = rescues.pop(0)[1]
            v = ref.survivors[sid]
            if v['near_since'] is not None:
                stays[sid] = round(ref.elapsed - v['near_since'], 1)
            v['rescued'] = True
        q = (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
        out += [e for e in ref.update(t, (x, y, 0.13) + q, (0.0, 0.0)) if e['type'] in ('LATE_REPORT', 'IDLE')]
        if ref.state != core.RUNNING:
            break
    return s, out, stays


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(f'rules {R.RULES_VERSION}: report window {R.REPORT_WINDOW_S:.0f} s ({R.SCORING["late_report"]}), '
          f'idle limit {R.IDLE_LIMIT_S:.0f} s ({R.SCORING["idle"]})')
    for run in sys.argv[1:]:
        s, out, stays = replay(run)
        pts = sum(e['score_delta'] for e in out)
        print(f'\n{os.path.basename(run.rstrip("/"))}: rescued {len(s["rescued"])}/{s["survivors_total"]}, '
              f'score {s["final_score"]} -> {s["final_score"] + pts} with these rules ({pts:+d})')
        print('  seconds in the zone before each confirmed rescue:', stays)
        for e in out:
            print(f'  {e["t"]:7.1f}s {e["type"]:11s} {e["description"]} ({e["score_delta"]:+d})')
