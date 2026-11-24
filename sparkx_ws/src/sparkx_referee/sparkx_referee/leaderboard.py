"""Aggregate referee summaries into a leaderboard.

usage: ros2 run sparkx_referee leaderboard [~/sparkx_logs] [--csv out.csv] [--require-integrity]
                                           [--dq-voids-world]

Each team's total = sum over worlds of its best run per world, where
  * a DISQUALIFIED run (rule violation, see docs/RULES.md) counts 0 for that world;
  * --dq-voids-world: one disqualified run zeroes that world even if a clean run exists;
  * --require-integrity: runs made on a modified or unverified stack also count 0.
The INTEGRITY column is the worst stack-integrity status among a team's counted runs and DQ the
number of disqualified runs found in the logs."""
import csv
import glob
import json
import os
import sys

INTEGRITY_RANK = {'ok': 0, 'unverified': 1, 'modified': 2}


def official(run, require_integrity=False):
    """Score that counts for the ranking."""
    if run.get('disqualified'):          # a disqualified run never scores more than 0, and never less than it earned
        return min(0, int(run.get('final_score', 0)))
    if require_integrity and integrity_of(run) != 'ok':
        return 0
    return int(run.get('official_score', run.get('final_score', 0)))


def integrity_of(run):
    return (run.get('stack_integrity') or {}).get('status', 'unverified')


def build(runs, require_integrity=False, dq_voids_world=False):
    best, dq_worlds, dq_count = {}, set(), {}
    for r in runs:
        k = (r['team'], r['world'])
        if r.get('disqualified'):
            dq_worlds.add(k)
            dq_count[r['team']] = dq_count.get(r['team'], 0) + 1
        s = official(r, require_integrity)
        if k not in best or s > best[k][0]:
            best[k] = (s, r)
    teams = {}
    for (team, world), (score, r) in best.items():
        if dq_voids_world and (team, world) in dq_worlds:
            score = 0
        t = teams.setdefault(team, dict(team=team, total=0, rescued=0, worlds=0, collisions=0, integrity='ok',
                                        disqualified=0))
        t['total'] += score
        t['rescued'] += 0 if r.get('disqualified') else len(r.get('rescued', []))
        t['worlds'] += 1
        t['collisions'] += r.get('collisions', 0)
        if INTEGRITY_RANK.get(integrity_of(r), 1) > INTEGRITY_RANK[t['integrity']]:
            t['integrity'] = integrity_of(r)
    for team, t in teams.items():
        t['disqualified'] = dq_count.get(team, 0)
    return sorted(teams.values(), key=lambda t: (-t['total'], -t['rescued'], t['collisions']))


def main():
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    args, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
        elif a == '--csv':
            skip = True
        elif not a.startswith('--'):
            args.append(a)
    root = os.path.expanduser(args[0] if args else '~/sparkx_logs')
    runs = []
    for f in sorted(glob.glob(os.path.join(root, '*', 'summary.json'))):
        try:
            with open(f) as fh:
                runs.append(json.load(fh))
        except (OSError, ValueError) as e:
            print(f'skipping {f}: {e}', file=sys.stderr)
    rows = build(runs, '--require-integrity' in flags, '--dq-voids-world' in flags)
    print(f'{"#":>2} {"team":20s} {"total":>7} {"rescued":>8} {"worlds":>6} {"collisions":>10} {"integrity":>10} {"DQ":>3}')
    for i, t in enumerate(rows, 1):
        print(f'{i:>2} {t["team"]:20s} {t["total"]:>7} {t["rescued"]:>8} {t["worlds"]:>6} {t["collisions"]:>10} '
              f'{t["integrity"]:>10} {t["disqualified"]:>3}')
    if '--csv' in sys.argv:
        out = sys.argv[sys.argv.index('--csv') + 1]
        with open(out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['team'])
            w.writeheader()
            w.writerows(rows)


if __name__ == '__main__':
    main()
