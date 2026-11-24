#!/usr/bin/env python3
"""SparkX lock-down tool (plain Python 3, no ROS needed).

Teams may edit only the paths listed in TEAM_FILES.txt. Everything else is locked.

  python3 tools/sparkx_lock.py status               allow-list + stack fingerprint
  python3 tools/sparkx_lock.py manifest             (organiser) hash every locked file -> LOCKED_MANIFEST.sha256
  python3 tools/sparkx_lock.py verify [--json]      exit 1 and list every modified / added / removed locked file
  python3 tools/sparkx_lock.py pack TEAM [-o DIR]   (team) zip the allowed files into TEAM_submission.zip
  python3 tools/sparkx_lock.py load ZIP --into DIR  (organiser) validate a submission and install it into a
                                                    pristine copy of the stack
  python3 tools/sparkx_lock.py protect | unprotect  chmod locked files read-only / writable again

How the lock-down is enforced: a team hands in ONLY the archive made by `pack`; the organiser runs
`load` into a clean checkout whose `verify` passes, builds it and runs the mission there. Whatever
else a team changed on its own machine never reaches the competition run. `protect` merely stops
accidental edits (any user can chmod the files back) - it is a convenience, not security.
"""
import argparse
import importlib.util
import json
import os
import shutil
import stat
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
SUBMISSION_META = 'SUBMISSION.json'
CODE_MAX_KB = 1024                      # each editable source / config file
BANNED_DATA_SUFFIXES = ('.py', '.pyc', '.pyo', '.pyd', '.so', '.sh', '.bash', '.zsh', '.exe', '.dll', '.dylib',
                        '.bat', '.cmd', '.ps1', '.jar', '.elf', '.bin.sh', '.ipynb', '.desktop', '.service')
KEEP_IN_DATA_DIR = ('README.md', '.gitkeep')   # stack-owned placeholders inside models/ survive a load


def load_integrity(root):
    """The hashing rules live in the referee package so the referee and this tool cannot disagree."""
    path = os.path.join(root, 'src', 'sparkx_referee', 'sparkx_referee', 'integrity.py')
    if not os.path.isfile(path):
        path = os.path.join(DEFAULT_ROOT, 'src', 'sparkx_referee', 'sparkx_referee', 'integrity.py')
    if not os.path.isfile(path):
        sys.exit(f'sparkx_lock: cannot find sparkx_referee/integrity.py under {root}')
    spec = importlib.util.spec_from_file_location('sparkx_integrity', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def syntax_error(source, name):
    """None if the Python source compiles, else a one-line description (nothing is executed)."""
    try:
        compile(source, name, 'exec')
        return None
    except (SyntaxError, ValueError) as e:
        return f'{name}: does not compile: line {getattr(e, "lineno", "?")}: {getattr(e, "msg", e)}'


def die(msg):
    print(f'sparkx_lock: ERROR: {msg}', file=sys.stderr)
    sys.exit(2)


def print_changes(res, limit=40):
    for key, label in (('modified', 'MODIFIED'), ('added', 'ADDED'), ('removed', 'REMOVED')):
        for rel in res[key][:limit]:
            print(f'  {label:9s}{rel}')
        if len(res[key]) > limit:
            print(f'  ... and {len(res[key]) - limit} more {label.lower()}')


# ----------------------------------------------------------------------------------- commands
def cmd_status(a, I):
    allow = I.read_allow(a.root)
    print(f'stack root : {a.root}')
    print('editable   :')
    for f in allow.files:
        print(f'  {f}{"" if os.path.isfile(os.path.join(a.root, f)) else "   (missing)"}')
    for d in allow.dirs:
        print(f'  {d}   (data only)')
    res = I.verify(a.root)
    print(f'locked     : {res["files"]} files, fingerprint {res["digest"][:16] or "-"}')
    print(f'integrity  : {res["status"].upper()}{"  - " + res["note"] if res["note"] else ""}')
    return 0


def cmd_manifest(a, I):
    t0 = time.time()
    hashes = I.write_manifest(a.root)
    print(f'{I.MANIFEST_FILE}: {len(hashes)} locked files, fingerprint {I.stack_digest(hashes)[:16]} '
          f'({time.time() - t0:.1f} s)')
    return 0


def cmd_verify(a, I):
    res = I.verify(a.root)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f'stack integrity: {res["status"].upper()}  ({res["files"]} locked files, fingerprint '
              f'{res["digest"][:16] or "-"}){"  - " + res["note"] if res["note"] else ""}')
        print_changes(res)
    return 0 if res['status'] == 'ok' else 1


def data_violation(rel, size, a, allow):
    low = rel.lower()
    if not any(os.path.dirname(rel) + '/' == d for d in allow.dirs):
        return f'{rel}: sub-folders are not allowed in a data folder (the package installs it flat)'
    if low.endswith(BANNED_DATA_SUFFIXES):
        return f'{rel}: executable / code files are not allowed in a data folder'
    if size > a.max_file_mb * 1e6:
        return f'{rel}: {size / 1e6:.0f} MB exceeds the {a.max_file_mb} MB per-file limit'
    return None


def cmd_pack(a, I):
    allow = I.read_allow(a.root)
    team = ''.join(c for c in a.team if c.isalnum() or c in '-_')
    if not team or team != a.team:
        die('team name may only contain letters, digits, "-" and "_"')
    members, problems, total = [], [], 0
    for rel in allow.files:
        full = os.path.join(a.root, rel)
        if os.path.islink(full):
            problems.append(f'{rel}: is a symbolic link')
        elif not os.path.isfile(full):
            problems.append(f'{rel}: missing (all editable files must be present)')
        elif os.path.getsize(full) > CODE_MAX_KB * 1024:
            problems.append(f'{rel}: larger than {CODE_MAX_KB} kB')
        else:
            members.append(rel)
    for d in allow.dirs:
        base = os.path.join(a.root, d)
        if os.path.islink(base.rstrip('/')):
            problems.append(f'{d}: is a symbolic link')
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            for dn in list(dirnames):
                if os.path.islink(os.path.join(dirpath, dn)):
                    problems.append(f'{os.path.relpath(os.path.join(dirpath, dn), a.root)}: is a symbolic link')
                    dirnames.remove(dn)
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, a.root).replace(os.sep, '/')
                if os.path.islink(full):
                    problems.append(f'{rel}: is a symbolic link')
                    continue
                if os.path.dirname(rel) + '/' == d and fn in KEEP_IN_DATA_DIR:
                    continue
                bad = data_violation(rel, os.path.getsize(full), a, allow)
                if bad:
                    problems.append(bad)
                    continue
                total += os.path.getsize(full)
                members.append(rel)
    if total > a.max_total_mb * 1e6:
        problems.append(f'data folders hold {total / 1e6:.0f} MB, limit is {a.max_total_mb} MB')
    for rel in members:
        if rel.endswith('.py'):
            with open(os.path.join(a.root, rel), 'rb') as f:
                err = syntax_error(f.read(), rel)
            if err:
                problems.append(err)
    if problems:
        print('submission NOT packed:', file=sys.stderr)
        for p in problems:
            print(f'  {p}', file=sys.stderr)
        return 2
    res = I.verify(a.root)
    if res['status'] == 'modified':
        print('WARNING: locked files in this stack differ from the official manifest. Those changes are NOT part of\n'
              '         your submission; the organisers run your files inside an unmodified stack:')
        print_changes(res, 12)
    meta = dict(team=team, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                stack_fingerprint=res['expected_digest'] or res['digest'], stack_status=res['status'],
                files={rel: I.sha256_file(os.path.join(a.root, rel)) for rel in members})
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f'{team}_submission.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in members:
            z.write(os.path.join(a.root, rel), rel)
        z.writestr(SUBMISSION_META, json.dumps(meta, indent=1))
    print(f'{out}: {len(members)} files, {os.path.getsize(out) / 1e6:.2f} MB')
    for rel in members:
        print(f'  {rel}')
    return 0


def inspect_archive(z, allow, a):
    """Return (members, problems). Nothing outside the allow-list may be in a submission."""
    problems, members, total = [], [], 0
    seen = set()
    for info in z.infolist():
        name = info.filename
        if name == SUBMISSION_META:
            continue
        if info.is_dir():
            if not any((name if name.endswith('/') else name + '/').startswith(d) or d.startswith(name) for d in allow.dirs):
                problems.append(f'{name}: folder outside the allow-list')
            continue
        kind = stat.S_IFMT(info.external_attr >> 16)      # 0 when the archiver stored no Unix file type
        if kind not in (0, stat.S_IFREG):
            problems.append(f'{name}: links and special files are not allowed')
            continue
        norm = os.path.normpath(name).replace(os.sep, '/')
        if name.startswith('/') or '\\' in name or norm != name or norm.startswith('..'):
            problems.append(f'{name}: illegal path')
            continue
        if name in seen:
            problems.append(f'{name}: duplicate entry')
            continue
        seen.add(name)
        if not allow.matches(name):
            problems.append(f'{name}: not in {I_ALLOW_NAME}')
            continue
        if allow.is_data(name):
            bad = data_violation(name, info.file_size, a, allow)
            if bad:
                problems.append(bad)
                continue
            total += info.file_size
        elif info.file_size > CODE_MAX_KB * 1024:
            problems.append(f'{name}: larger than {CODE_MAX_KB} kB')
            continue
        members.append(info)
    for rel in allow.files:
        if rel not in seen:
            problems.append(f'{rel}: missing from the archive')
    if total > a.max_total_mb * 1e6:
        problems.append(f'data files unpack to {total / 1e6:.0f} MB, limit is {a.max_total_mb} MB')
    return members, problems


I_ALLOW_NAME = 'TEAM_FILES.txt'


def cmd_load(a, I):
    target = os.path.abspath(os.path.expanduser(a.into))
    if not I.is_stack_root(target):
        die(f'{target} is not a SparkX stack root (no TEAM_FILES.txt + src/)')
    allow = I.read_allow(target)                      # the organiser's allow-list decides, not the team's
    res = I.verify(target)
    if res['status'] != 'ok' and not a.force:
        print(f'target stack is {res["status"].upper()}: {res["note"]}', file=sys.stderr)
        print_changes(res, 12)
        die('refusing to load into a stack that is not pristine (use --force to override)')
    try:
        z = zipfile.ZipFile(a.zip)
    except (OSError, zipfile.BadZipFile) as e:
        die(f'cannot open {a.zip}: {e}')
    with z:
        members, problems = inspect_archive(z, allow, a)
        if not problems and not a.no_check:           # syntax-check the code before touching the stack
            for info in members:
                if info.filename.endswith('.py'):
                    err = syntax_error(z.read(info), info.filename)
                    if err:
                        problems.append(err)
        if problems:
            print(f'submission REJECTED ({a.zip}):', file=sys.stderr)
            for p in problems:
                print(f'  {p}', file=sys.stderr)
            return 2
        meta = {}
        if SUBMISSION_META in z.namelist():
            try:
                meta = json.loads(z.read(SUBMISSION_META))
            except ValueError:
                meta = {}
        for d in allow.dirs:                          # data folders are replaced, not merged
            base = os.path.join(target, d)
            if os.path.isdir(base):
                for dirpath, dirnames, filenames in os.walk(base, topdown=False):
                    for fn in filenames:
                        if not (os.path.abspath(dirpath) == os.path.abspath(base) and fn in KEEP_IN_DATA_DIR):
                            os.remove(os.path.join(dirpath, fn))
                    for dn in dirnames:
                        p = os.path.join(dirpath, dn)
                        os.unlink(p) if os.path.islink(p) else (os.rmdir(p) if not os.listdir(p) else None)
        for info in members:
            dst = os.path.join(target, info.filename)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.lexists(dst):
                os.chmod(dst, 0o644) if not os.path.islink(dst) else None
                os.remove(dst)
            with z.open(info) as src, open(dst, 'wb') as f:
                shutil.copyfileobj(src, f, 1 << 20)      # streamed: a large model never sits in memory
            os.chmod(dst, 0o644)
    after = I.verify(target)
    print(f'loaded {len(members)} files from team "{meta.get("team", "?")}" into {target}')
    if meta.get('stack_fingerprint') and after['expected_digest'] and meta['stack_fingerprint'] != after['expected_digest']:
        print(f'NOTE: the team built against stack {meta["stack_fingerprint"][:16]}, this stack is '
              f'{after["expected_digest"][:16]} (different release).')
    print(f'stack integrity after load: {after["status"].upper()}')
    return 0 if after['status'] == 'ok' or a.force else 1


def cmd_protect(a, I, writable=False):
    n = 0
    for rel in I.locked_files(a.root):
        full = os.path.join(a.root, rel)
        if os.path.islink(full):
            continue
        mode = stat.S_IMODE(os.stat(full).st_mode)
        new = (mode | stat.S_IWUSR) if writable else (mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        if new != mode:
            os.chmod(full, new)
            n += 1
    print(f'{"unprotected" if writable else "protected"} {n} locked files '
          f'({"owner-writable again" if writable else "read-only; editable files untouched"})')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description='SparkX lock-down tool', formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    p.add_argument('--root', default=DEFAULT_ROOT, help='stack root (folder with TEAM_FILES.txt), default: this checkout')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    sub.add_parser('manifest')
    v = sub.add_parser('verify')
    v.add_argument('--json', action='store_true')
    limits = argparse.ArgumentParser(add_help=False)
    limits.add_argument('--max-file-mb', type=float, default=500.0, help='largest single data file')
    limits.add_argument('--max-total-mb', type=float, default=1500.0, help='all data files together')
    k = sub.add_parser('pack', parents=[limits])
    k.add_argument('team')
    k.add_argument('-o', '--out', default='.')
    ld = sub.add_parser('load', parents=[limits])
    ld.add_argument('zip')
    ld.add_argument('--into', required=True, help='pristine stack root to install the submission into')
    ld.add_argument('--force', action='store_true', help='load even if the target stack does not verify')
    ld.add_argument('--no-check', action='store_true', help='skip the Python syntax check')
    sub.add_parser('protect')
    sub.add_parser('unprotect')
    a = p.parse_args(argv)
    a.root = os.path.abspath(os.path.expanduser(a.root))
    I = load_integrity(a.root if a.cmd != 'load' else os.path.abspath(os.path.expanduser(a.into)))
    if a.cmd != 'load' and not I.is_stack_root(a.root):
        die(f'{a.root} is not a SparkX stack root (no TEAM_FILES.txt + src/)')
    fn = {'status': cmd_status, 'manifest': cmd_manifest, 'verify': cmd_verify, 'pack': cmd_pack, 'load': cmd_load,
          'protect': cmd_protect, 'unprotect': lambda a, I: cmd_protect(a, I, writable=True)}[a.cmd]
    return fn(a, I)


if __name__ == '__main__':
    sys.exit(main())
