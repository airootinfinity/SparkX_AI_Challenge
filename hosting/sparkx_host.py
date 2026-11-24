#!/usr/bin/env python3
"""SparkX host - run a team's submission on the organiser machine with one command or one button.

  python3 hosting/sparkx_host.py setup                      build the stack once and verify its seal ([--reseal]: organisers only)
  python3 hosting/sparkx_host.py ui                         control panel on http://127.0.0.1:8090 (the button)
  python3 hosting/sparkx_host.py check <zip>                is this submission acceptable? (nothing is run)
  python3 hosting/sparkx_host.py run <zip> --world <name>   check -> clean copy -> build -> run -> score
  python3 hosting/sparkx_host.py board                      leaderboard from every finished run
  python3 hosting/sparkx_host.py new-world --name final_A --size medium   (random 63-bit seed + secret salt; --practice for a plain one) [--difficulty normal] [--lighting day]
  python3 hosting/sparkx_host.py stop                       stop a run that is in progress

Folders (all inside hosting/):
  submissions/   put the zips the teams sent here
  worlds/        secret competition worlds (made with new-world); practice worlds are offered as well
  results/       runs/<date>_<team>_<world>/summary.json, team_logs/, leaderboard.csv
  work/          one clean copy of the stack per team (rebuilt on every run)

What one run does
  1. The zip is checked. It must contain perception.py, memory.py, mission.py and team.yaml, may
     contain data files in a models/ folder, and nothing else. Folder layout inside the zip does
     not matter.
  2. The four files are placed in a fresh copy of the sealed stack (tools/sparkx_lock.py load), so
     nothing else a team changed can take part. Only the sparkx_team package is rebuilt.
  3. Simulator + referee start in competition mode on the chosen world.
  4. The team's software starts in a sandbox (when bubblewrap is installed): it cannot read the
     world's answer files, other teams' code, the results or the organisers' home folder, it does
     not see the simulator's own data channel, and it has a memory limit.
  5. When navigation reports ready the mission is started. The run ends when the team ends it, at
     the time limit, or when the team's software has died.
  6. The result is stored and the leaderboard is rebuilt.

Plain Python 3; needs ROS 2 only for the commands that build or run.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STACK = os.path.join(ROOT, 'sparkx_ws')
SUBS, WORLDS, RESULTS, WORK = (os.path.join(HERE, d) for d in ('submissions', 'worlds', 'results', 'work'))
RUNS = os.path.join(RESULTS, 'runs')
PRACTICE = os.path.join(STACK, 'src', 'sparkx_worlds', 'worlds')
ORG_UNIT, TEAM_UNIT = 'sparkx-host-org', 'sparkx-host-team'
CODE = {'perception.py': 'src/sparkx_team/sparkx_team/perception.py', 'memory.py': 'src/sparkx_team/sparkx_team/memory.py',
        'mission.py': 'src/sparkx_team/sparkx_team/mission.py', 'team.yaml': 'src/sparkx_team/config/team.yaml'}
IGNORED_DIRS = ('__MACOSX', '__pycache__')                      # zip folders that are skipped
IGNORED_FILES = ('.DS_Store', 'Thumbs.db', 'SUBMISSION.json', 'desktop.ini')
MAX_FILE_MB, MAX_TOTAL_MB = 500.0, 1500.0                         # as sparkx_lock.py load; checked before unpacking


def ignored(name):
    parts = name.replace('\\', '/').split('/')
    return any(d in parts[:-1] for d in IGNORED_DIRS) or parts[-1] in IGNORED_FILES or parts[-1].endswith('.pyc')

DEFAULTS = dict(
    ros_setup='/opt/ros/jazzy/setup.bash',
    extra_setup=[],                 # more scripts to source (e.g. a local overlay with Nav2)
    team_visible_paths=[],          # extra folders the sandboxed team software may read (e.g. that overlay, ~/.local/lib)
    ros_domain_id='random',         # a fresh domain (30-99) per run, so ROS programs on other machines never mix in
    dashboard_port=8080,
    ui_port=8090,
    team_memory='8G',               # memory limit of the team's software ('' = none)
    team_cpus=8,                    # CPU cores for the team's software (0 = no limit; needs the cpu controller)
    org_memory='',                  # memory limit of simulator + referee ('' = none)
    sandbox='on',                   # on | auto | off   (bubblewrap; 'on' refuses to run without it)
    team_user='',                   # run team software as this Unix user (see secure_setup.sh); '' = as you
    textures='full',                # full | lite
    start_timeout_s=240,            # simulator, referee and navigation must be up within this time
    min_free_mb=0,                  # refuse to start with less memory available than this
)


def config():
    c = dict(DEFAULTS)
    p = os.path.join(HERE, 'host_config.json')
    if os.path.isfile(p):
        c.update(json.load(open(p)))
    return c


def clean(text, limit=2000):
    """Team-made text (file names, error lines) without terminal control characters, shortened."""
    t = ''.join(ch if ch in '\n\t' or (ord(ch) >= 32 and ord(ch) != 127 and not 0x80 <= ord(ch) < 0xa0) else '?'
                for ch in str(text))
    return t if len(t) <= limit else t[:limit] + '...'


def cap_problems(problems, n=40):
    """At most n problem lines (a zip with 300,000 bad entries must not flood the panel)."""
    problems = [clean(p, 400) for p in problems]
    return problems if len(problems) <= n else problems[:n] + [f'... and {len(problems) - n} more problems']


def say(msg, job=None):
    line = f'[{time.strftime("%H:%M:%S")}] {clean(msg, 4000)}'
    print(line, flush=True)
    if job is not None:
        job['log'].append(line)
        del job['log'][:-400]


def ros_env(c, team_install=None):
    parts = [f'source {shlex.quote(os.path.expanduser(c["ros_setup"]))}']
    # extra setup scripts may find their files through $HOME, and the team software runs with a home
    # folder of its own: source them with the organiser's home, then put the team's back
    real_home = shlex.quote(os.path.expanduser('~'))
    parts += [f'_h=$HOME; export HOME={real_home}; source {shlex.quote(os.path.expanduser(p))}; export HOME=$_h'
              for p in c['extra_setup']]
    parts.append(f'source {shlex.quote(os.path.join(STACK, "install", "setup.bash"))}')
    if team_install:
        parts.append(f'source {shlex.quote(os.path.join(team_install, "setup.bash"))}')
    return '; '.join(parts)


CLEAN_ENV = {k: os.environ[k] for k in ('HOME', 'USER', 'LANG', 'DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS')
             if k in os.environ}
CLEAN_ENV['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


def bash(cmd, log=None, cwd=None, timeout=None, clean=False):
    """Run a bash command line; returns (exit code, output). clean=True: start from an environment
    without the caller's ROS workspaces, so a build records only ROS and the configured extra setup
    scripts as its underlays (whatever a profile sourced on this machine never reaches a run)."""
    r = subprocess.run(['bash', '-c', cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout,
                       env=CLEAN_ENV if clean else None)
    if log:
        with open(log, 'a') as f:
            f.write(f'$ {cmd}\n{r.stdout}\n')
    return r.returncode, r.stdout


# ------------------------------------------------------------------------------------ submissions
def team_of(zip_path):
    name = os.path.basename(zip_path)
    name = re.sub(r'\.zip$', '', name, flags=re.I)
    name = re.sub(r'[_-]?submission$', '', name, flags=re.I)
    name = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_-')
    return name or 'team'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def normalise(zip_path, out_zip=None):
    """Map whatever folder layout a team zipped to the paths of TEAM_FILES.txt.
    Returns (problems, members) where members = {stack path: name inside the zip}."""
    problems, members = [], {}
    try:
        z = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as e:
        return [f'cannot open the zip: {e}'], {}
    with z:
        total = 0
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or ignored(name):
                continue
            total += info.file_size
            if info.file_size > MAX_FILE_MB * 1e6:
                problems.append(f'{name}: {info.file_size / 1e6:.0f} MB exceeds the {MAX_FILE_MB:.0f} MB per-file limit')
                continue
            base, parent = os.path.basename(name), os.path.basename(os.path.dirname(name))
            if base in CODE:
                dst = CODE[base]
            elif parent == 'models':
                if base in ('README.md', '.gitkeep'):
                    continue
                dst = f'src/sparkx_team/models/{base}'
            elif base == '__init__.py' and info.file_size == 0:
                continue
            else:
                problems.append(f'{name}: not one of the four team files and not inside models/')
                continue
            if dst in members:
                problems.append(f'{base}: found twice ({members[dst]} and {name})')
                continue
            members[dst] = name
        if total > MAX_TOTAL_MB * 1e6:
            problems.append(f'the files add up to {total / 1e6:.0f} MB, more than the {MAX_TOTAL_MB:.0f} MB limit')
        for base, dst in CODE.items():
            if dst not in members:
                problems.append(f'{base}: missing')
        if out_zip and not problems:
            try:
                with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as out:
                    for dst, name in members.items():
                        with z.open(name) as src, out.open(dst, 'w') as d:   # streamed: never the whole file in memory
                            shutil.copyfileobj(src, d, 1 << 20)
            except Exception as e:      # encrypted member, bad CRC, unsupported compression, ...
                problems.append(f'cannot unpack the zip: {type(e).__name__}: {e}')
    return problems, members


def check(zip_path, job=None):
    """Full acceptance check without running anything. Returns the list of problems (empty = accepted)."""
    import tempfile
    os.makedirs(WORK, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='.check_', dir=WORK)      # unique: two checks never share a folder
    try:
        norm = os.path.join(tmp, 'submission.zip')
        try:
            problems, members = normalise(zip_path, norm)
        except Exception as e:
            return [f'cannot read the zip: {type(e).__name__}: {e}']
        if problems:
            return cap_problems(problems)
        # the strict rules (sizes, no code in models/, Python that compiles) live in the lock tool
        stack = os.path.join(tmp, 'stack')
        os.makedirs(os.path.join(stack, 'src'))
        shutil.copy(os.path.join(STACK, 'TEAM_FILES.txt'), stack)
        shutil.copytree(os.path.join(STACK, 'src', 'sparkx_referee'), os.path.join(stack, 'src', 'sparkx_referee'))
        code, out = bash(f'python3 {shlex.quote(os.path.join(STACK, "tools", "sparkx_lock.py"))} load {shlex.quote(norm)} '
                         f'--into {shlex.quote(stack)} --force')
        if code == 0:
            return []
        lines = [l.strip() for l in out.splitlines() if l.strip() and not l.strip().startswith('loaded ')
                 and 'submission REJECTED' not in l]
        # never "accepted" because every line happened to be filtered out: the exit code decides
        return cap_problems(lines or [f'the lock tool refused the submission (exit code {code})'])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prepare(zip_path, c, job=None):
    """Clean copy of the stack + the team's files, sparkx_team rebuilt. Returns the team's install folder."""
    team = team_of(zip_path)
    base = os.path.join(WORK, team)
    if c.get('team_user') and os.path.isdir(os.path.join(base, 'home')):
        subprocess.run(['sudo', '-n', '-u', c['team_user'], '/usr/bin/env', 'rm', '-rf', '--one-file-system',
                        os.path.join(base, 'home')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.rmtree(base, ignore_errors=True)
    if os.path.exists(base):
        raise RuntimeError(f'cannot clear {base} (files the organiser may not delete); remove it with sudo')
    os.makedirs(os.path.join(base, 'home'))
    snap = os.path.join(base, 'submitted.zip')      # a private copy: what is hashed is exactly what runs
    shutil.copyfile(zip_path, snap)
    norm = os.path.join(base, 'submission.zip')
    problems, _ = normalise(snap, norm)
    if problems:
        raise RuntimeError('submission rejected:\n  ' + '\n  '.join(problems))
    stack = os.path.join(base, 'stack')
    say(f'{team}: copying the sealed stack', job)
    shutil.copytree(STACK, stack, symlinks=True,
                    ignore=shutil.ignore_patterns('build', 'install', 'log', '__pycache__', '*.pyc'))
    log = os.path.join(base, 'build.log')
    lock = shlex.quote(os.path.join(STACK, 'tools', 'sparkx_lock.py'))
    code, out = bash(f'python3 {lock} load {shlex.quote(norm)} --into {shlex.quote(stack)}', log)
    if code != 0:
        raise RuntimeError('submission rejected:\n' + out)
    say(f'{team}: files accepted, building sparkx_team', job)
    code, out = bash(f'{ros_env(c)}; colcon build --packages-select sparkx_team --allow-overriding sparkx_team '
                     f'--event-handlers console_cohesion+', log, cwd=stack, timeout=900, clean=True)
    if code != 0 or not os.path.isdir(os.path.join(stack, 'install', 'sparkx_team')):
        raise RuntimeError('build failed - see ' + log + '\n' + out[-1500:])
    return os.path.join(stack, 'install')


# ------------------------------------------------------------------------------------ processes
def unit_active(unit):
    return subprocess.run(['systemctl', '--user', 'is-active', '-q', f'{unit}.scope']).returncode == 0


def unit_stop(unit):
    subprocess.run(['systemctl', '--user', 'kill', '-s', 'INT', f'{unit}.scope'], stderr=subprocess.DEVNULL)
    for _ in range(16):
        if not unit_active(unit):
            break
        time.sleep(0.5)
    subprocess.run(['systemctl', '--user', 'stop', f'{unit}.scope'], stderr=subprocess.DEVNULL)
    subprocess.run(['systemctl', '--user', 'reset-failed', f'{unit}.scope'], stderr=subprocess.DEVNULL)


def unit_start(unit, argv, log, mem='', cpus=0, env=None):
    subprocess.run(['systemctl', '--user', 'reset-failed', f'{unit}.scope'], stderr=subprocess.DEVNULL)
    cmd = ['systemd-run', '--user', '--scope', '-q', f'--unit={unit}']
    if mem:
        cmd += ['-p', f'MemoryMax={mem}', '-p', 'MemorySwapMax=0']
    if cpus and cpu_controller():
        cmd += ['-p', f'CPUQuota={int(cpus) * 100}%']
    return subprocess.Popen(cmd + argv, stdout=open(log, 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)


def port_in_use(port):
    import socket
    with socket.socket() as so:
        so.settimeout(0.5)
        return so.connect_ex(('127.0.0.1', port)) == 0


def cpu_controller():
    try:
        p = f'/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/cgroup.controllers'
        return 'cpu' in open(p).read().split()
    except OSError:
        return False


def sandbox_available():
    if not shutil.which('bwrap'):
        return False
    r = subprocess.run(['bwrap', '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev', '--unshare-pid', '--proc', '/proc',
                        '--tmpfs', '/tmp', 'true'], capture_output=True)
    return r.returncode == 0


SYSTEM_MOUNTS = ('/', '/boot', '/boot/efi', '/usr', '/var', '/opt', '/etc', '/nix')
REMOVABLE_FS = ('vfat', 'exfat', 'ntfs', 'ntfs3', 'fuseblk', 'msdos', 'udf', 'iso9660', 'nfs', 'nfs4', 'cifs', 'smb3',
                'sshfs', 'fuse.sshfs', 'fuse.rclone', 'fuse.gvfsd-fuse', '9p', 'btrfs', 'xfs', 'ext2', 'ext3', 'ext4', 'zfs')


def hidden_mounts():
    """Folders the team must see empty: the usual places for USB drives and shares, plus every other disk or
    network share mounted outside the system folders (a second disk at /data could hold submissions)."""
    out = ['/media', '/mnt', '/srv']
    try:
        with open('/proc/self/mountinfo') as f:
            for line in f:
                part = line.split(' - ')
                target = part[0].split()[4].replace('\\040', ' ')
                fstype = part[1].split()[0] if len(part) > 1 else ''
                if fstype not in REMOVABLE_FS or target in SYSTEM_MOUNTS or not os.path.isdir(target):
                    continue
                if any(target == h or target.startswith(h + os.sep)
                       for h in out + ['/proc', '/sys', '/dev', '/run', '/tmp', '/snap', '/var/lib', '/boot']):
                    continue
                if os.access(target, os.X_OK):
                    out.append(target)
    except OSError:
        pass
    return [h for h in dict.fromkeys(out) if os.path.isdir(h)]


def sandbox_argv(c, team_install, home):
    """bubblewrap command line: the team's software sees the system, the built stack and its own
    folder, and nothing else of the organisers' files or processes."""
    user_home = os.path.expanduser('~')
    hide = [user_home] + ([] if (ROOT + os.sep).startswith(user_home + os.sep) else [ROOT])
    # a minimal /dev (null, zero, random, tty, shm): no camera, microphone or the machine's /dev/mqueue
    a = ['bwrap', '--die-with-parent', '--ro-bind', '/', '/', '--dev', '/dev', '--unshare-pid', '--proc', '/proc',
         '--unshare-ipc', '--mqueue', '/dev/mqueue',                      # its own message queues and semaphores: nothing left for the next team
         '--tmpfs', '/tmp',
         # /run holds the Docker, containerd and D-Bus sockets (no container control for team code): the team sees an
         # empty /run. /media, /mnt and /srv hold USB drives and shares, e.g. other teams' zips.
         '--tmpfs', '/run', '--tmpfs', f'/run/user/{os.getuid()}',
         '--tmpfs', '/dev/shm']                # its own shared memory: never the DDS segments of the organiser's nodes
    for h in hidden_mounts() + hide:
        a += ['--tmpfs', h]
    show = [os.path.join(STACK, 'install'), team_install] + [os.path.expanduser(p) for p in c['team_visible_paths']]
    show += [os.path.dirname(os.path.expanduser(p)) for p in c['extra_setup']]
    for p in show[2:]:
        rp = os.path.realpath(p)
        if rp in ('/', os.path.realpath(user_home)) or any(os.path.realpath(x).startswith(rp + os.sep)
                                                           for x in (WORLDS, SUBS, RESULTS, ROOT)):
            raise RuntimeError(f'"{p}" (team_visible_paths / extra_setup) would show the team your home, the secret '
                               'worlds or other submissions: put those files in a folder of their own')
    for p in dict.fromkeys(show):
        if os.path.exists(p):
            a += ['--ro-bind', p, p]
    a += ['--bind', home, home]
    answers = os.path.join(STACK, 'install', 'sparkx_worlds', 'share', 'sparkx_worlds', 'worlds')
    if os.path.isdir(answers):
        a += ['--tmpfs', answers]            # practice worlds carry their answer sheets
    return a


# ------------------------------------------------------------------------------------ worlds, results
def worlds():
    out = []
    for kind, base in (('secret', WORLDS), ('practice', PRACTICE)):
        if os.path.isdir(base):
            for n in sorted(os.listdir(base)):
                if os.path.isfile(os.path.join(base, n, 'private', 'scenario.yaml')):
                    out.append(dict(name=n, kind=kind, dir=os.path.join(base, n)))
    return out


def world_dir(name):
    if os.path.isfile(os.path.join(name, 'private', 'scenario.yaml')):
        return os.path.abspath(name)
    for w in worlds():
        if w['name'] == name:
            return w['dir']
    raise RuntimeError(f'no such world: {name} (known: {", ".join(w["name"] for w in worlds()) or "none"})')


def summaries():
    out = []
    if os.path.isdir(RUNS):
        for d in sorted(os.listdir(RUNS)):
            p = os.path.join(RUNS, d, 'summary.json')
            if os.path.isfile(p):
                try:
                    s = json.load(open(p), parse_constant=lambda c: None)
                except (OSError, ValueError):
                    continue
                s.pop('trajectory', None)
                s['run'] = d
                try:
                    hj = json.load(open(os.path.join(RUNS, d, 'host.json')))
                    s['official'] = hj.get('official', True)
                except (OSError, ValueError):
                    s['official'] = d < '20261122_2300'   # older runs had no host.json field; newer ones always do
                out.append(s)
    return out


def board(runs=None):
    """Total = sum over worlds of the best official score per world."""
    best = {}
    for s in runs if runs is not None else summaries():
        if s.get('official') is False:
            continue                       # --unofficial test runs never count
        k = (s['team'], s['world'])
        score = min(0, int(s.get('final_score', 0))) if s.get('disqualified') else int(s.get('official_score', s.get('final_score', 0)))
        if k not in best or score > best[k]['score']:
            best[k] = dict(score=score, review=bool(s.get('needs_review')), rescued=len(s.get('rescued', [])), total=s.get('survivors_total', 0),
                           elapsed=s.get('elapsed_s', 0), reason=s.get('finish_reason', ''), run=s['run'])
    teams = {}
    for (team, world), b in best.items():
        t = teams.setdefault(team, dict(team=team, total=0, rescued=0, worlds={}))
        t['total'] += b['score']
        t['rescued'] += b['rescued']
        t['worlds'][world] = b
    return sorted(teams.values(), key=lambda t: (-t['total'], -t['rescued'], t['team']))


def write_board():
    rows = board()
    os.makedirs(RESULTS, exist_ok=True)
    names = sorted({w for t in rows for w in t['worlds']})
    with open(os.path.join(RESULTS, 'leaderboard.csv'), 'w') as f:
        f.write('rank,team,total,rescued,' + ','.join(names) + '\n')
        for i, t in enumerate(rows, 1):
            f.write(f'{i},{t["team"]},{t["total"]},{t["rescued"]},' +
                    ','.join(str(t['worlds'][w]['score']) if w in t['worlds'] else '' for w in names) + '\n')
    return rows


# ------------------------------------------------------------------------------------ one run
def http(url, post=False, timeout=4):
    req = urllib.request.Request(url, data=b'' if post else None, method='POST' if post else 'GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def new_job(zip_path='', world=''):
    return dict(stage='idle', team=team_of(zip_path) if zip_path else '', world=world, zip=os.path.basename(zip_path),
                log=[], mission=None, result=None, error='', token='', started=time.time(), stop=False)


DANGEROUS_GROUPS = ('docker', 'sudo', 'admin', 'wheel', 'root', 'lxd', 'libvirt', 'incus-admin', 'podman', 'disk', 'adm')


def insecure_reasons(c):
    """Why team software on this machine could still reach what it must not. Empty = the
    machine is set up for scored runs: team code runs as its own user, outside every group that gives root
    (Docker!), behind the firewall of secure_setup.sh (no internet, no TCP)."""
    u = c.get('team_user') or ''
    if not u:
        return ['team_user is not set: team code would run as you, and your user is ' +
                ('in the docker group (= root on this machine)' if 'docker' in groups_of(None) else 'not separated') +
                '. Run "sudo bash hosting/secure_setup.sh" and set "team_user": "sparkxteam" in host_config.json']
    out = []
    try:
        import pwd
        pwd.getpwnam(u)
    except KeyError:
        return [f'team_user "{u}" does not exist: run "sudo bash hosting/secure_setup.sh"']
    bad = sorted(set(groups_of(u)) & set(DANGEROUS_GROUPS))
    if bad:
        out.append(f'team_user "{u}" is in the group(s) {", ".join(bad)}, which give root access: '
                   f'"sudo gpasswd -d {u} <group>" for each')
    if u == os.environ.get('USER') or u == 'root':
        out.append(f'team_user "{u}" is you or root: use the separate user made by secure_setup.sh')
    if not os.path.isfile('/etc/sparkx/team-firewall.ok'):
        out.append('the team firewall (no internet, no TCP) is not installed: run "sudo bash hosting/secure_setup.sh"')
    return out


def groups_of(user):
    r = subprocess.run(['id', '-Gn'] + ([user] if user else []), capture_output=True, text=True)
    return r.stdout.split()


def run(zip_path, world, c, job=None, gui=False, time_limit=0.0, unofficial=False):
    """The whole pipeline for one team on one world. Returns the run's summary (dict)."""
    job = job if job is not None else new_job(zip_path, world)
    insecure = insecure_reasons(c)
    team = team_of(zip_path)
    clash = [n for n in (os.listdir(SUBS) if os.path.isdir(SUBS) else [])
             if n.lower().endswith('.zip') and n != os.path.basename(zip_path) and team_of(n) == team]
    if clash and os.path.dirname(os.path.abspath(zip_path)) == os.path.abspath(SUBS):
        raise RuntimeError(f'another submission ({", ".join(clash)}) has the same team name "{team}": rename one')
    wdir = world_dir(world)
    wname = os.path.basename(wdir)
    try:    # competition worlds must be salted (made with new-world)
        import yaml
        if not yaml.safe_load(open(os.path.join(wdir, 'private', 'scenario.yaml'))).get('salted'):
            insecure = insecure + [f'world "{wname}" is not salted (plain seed), so it is not private. Make competition worlds with "new-world" (no --seed)']
    except (OSError, ValueError, AttributeError):
        insecure = insecure + [f'world "{wname}": scenario.yaml unreadable']
    try:
        job['stage'] = 'checking'
        if insecure and not unofficial:
            raise RuntimeError('this machine is not safe for scored runs:\n  - ' + '\n  - '.join(insecure) +
                               '\n(for a test only: "run ... --unofficial" runs it, marks it unofficial and keeps it off '
                               'the leaderboard)')
        for r_ in insecure:
            say(f'UNOFFICIAL RUN (not for scores): {r_}', job)
        if not os.path.isdir(os.path.join(STACK, 'install', 'sparkx_referee')):
            raise RuntimeError('the organiser stack is not built yet: run "sparkx_host.py setup" first')
        code, out = bash(f'python3 {shlex.quote(os.path.join(STACK, "tools", "sparkx_lock.py"))} verify')
        if code != 0:
            raise RuntimeError('the organiser stack does not match its seal (LOCKED_MANIFEST.sha256):\n' + out[-800:] +
                               '\nIf the change is intended, run "sparkx_host.py setup" again.')
        for unit in (ORG_UNIT, TEAM_UNIT, 'sparkx-main'):
            if unit_active(unit):
                raise RuntimeError(f'a simulation is already running ({unit}.scope); stop it first')
        if port_in_use(int(c['dashboard_port'])):     # e.g. someone's own "ros2 launch sparkx_bringup practice.launch.py"
            raise RuntimeError(f'port {c["dashboard_port"]} is in use: another SparkX simulation (a referee dashboard) seems '
                               'to be running on this machine. Stop it (Ctrl+C in its terminal) first')
        avail = int(subprocess.run(['free', '-m'], capture_output=True, text=True).stdout.splitlines()[1].split()[6])
        if avail < c['min_free_mb']:
            raise RuntimeError(f'only {avail} MB of memory available, {c["min_free_mb"]} MB wanted (host_config.json)')
        job['stage'] = 'building'
        team_install = prepare(zip_path, c, job)
        home = os.path.join(WORK, team, 'home')
        os.makedirs(RUNS, exist_ok=True)
        logs = os.path.join(RESULTS, 'team_logs', f'{time.strftime("%Y%m%d_%H%M%S")}_{team}_{wname}')
        os.makedirs(logs)

        # ---- organiser side: simulator + referee, competition mode, own Gazebo partition
        job['stage'] = 'starting simulator'
        if str(c['ros_domain_id']) == 'random':
            c = dict(c, ros_domain_id=30 + secrets.randbelow(70))
        say(f'ROS domain {c["ros_domain_id"]} for this run', job)
        token = 't' + secrets.token_hex(6)
        job['token'] = token
        port = int(c['dashboard_port'])
        # ROS discovery stays on this machine: with the default range any laptop on the same network
        # could join this domain and, for example, publish /cmd_vel during a run
        org_env = dict(CLEAN_ENV, GZ_PARTITION='org_' + secrets.token_hex(8), GZ_IP='127.0.0.1',
                       ROS_DOMAIN_ID=str(c['ros_domain_id']), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
        args = [f'world_dir:={wdir}', f'team_name:={team}', 'baseline:=false', 'competition:=true', 'auto_start:=false',
                f'dashboard_token:={token}', f'dashboard_port:={port}', f'log_dir:={RUNS}', f'stack_root:={STACK}',
                f'gui:={"true" if gui else "false"}', f'textures:={c["textures"]}']
        if time_limit > 0:
            args.append(f'time_limit_s:={float(time_limit)}')
        before = set(os.listdir(RUNS))
        unit_start(ORG_UNIT, ['bash', '-c', f'{ros_env(c)}; exec ros2 launch sparkx_bringup practice.launch.py ' +
                              ' '.join(shlex.quote(a) for a in args)], os.path.join(logs, 'organiser.log'),
                   mem=c['org_memory'], env=org_env)
        state_url = f'http://127.0.0.1:{port}/state?token={token}'
        t0 = time.time()
        while True:
            time.sleep(2)
            try:
                st = http(state_url)
                if st.get('robot'):
                    break
            except Exception:
                pass
            if time.time() - t0 > c['start_timeout_s'] or not unit_active(ORG_UNIT) or job['stop']:
                raise RuntimeError('simulator / referee did not come up - see ' + os.path.join(logs, 'organiser.log'))
        if st['lockdown']['start_block']:
            raise RuntimeError('the referee refuses to start: ' + st['lockdown']['start_block'])
        say(f'simulator and referee are up after {time.time() - t0:.0f} s (world {wname})', job)

        # ---- team side: the autonomy stack with the team's files, sandboxed and limited
        job['stage'] = 'starting team software'
        use_box = c['sandbox'] == 'on' or (c['sandbox'] == 'auto' and sandbox_available())
        if c['sandbox'] == 'on' and not sandbox_available():
            raise RuntimeError('sandbox is set to "on" but bubblewrap (bwrap) does not work on this machine')
        team_env = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME=home, LANG='C.UTF-8',
                        ROS_DOMAIN_ID=str(c['ros_domain_id']), ROS_LOG_DIR=os.path.join(home, 'roslog'),
                        GZ_PARTITION='team', PYTHONUNBUFFERED='1',
                        FASTDDS_BUILTIN_TRANSPORTS='UDPv4')   # no shared-memory transport across the sandbox wall
        if 'RMW_IMPLEMENTATION' in os.environ:
            team_env['RMW_IMPLEMENTATION'] = os.environ['RMW_IMPLEMENTATION']
        # no LOCALHOST discovery range here: it does not work across the sandbox's own /dev/shm (tested);
        # the organiser side is LOCALHOST-only, and team_user's firewall keeps team traffic on this machine
        inner = ['bash', '-c', f'umask 002; {ros_env(c, team_install)}; exec ros2 launch sparkx_baseline baseline.launch.py']
        envv = [f'{k}={v}' for k, v in team_env.items()]
        box = sandbox_argv(c, team_install, home) if use_box else []
        if c['team_user']:
            check_team_user(c, envv, box)
            argv = ['sudo', '-n', '-u', c['team_user'], '/usr/bin/env', '-i'] + envv + box + inner
        else:
            argv = ['env', '-i'] + envv + box + inner
        models = model_check(c, envv, box, team_install, job)
        team_log = os.path.join(logs, 'team.log')
        unit_start(TEAM_UNIT, argv, team_log, mem=c['team_memory'], cpus=c['team_cpus'])
        say(f'team software started ({"sandboxed" if use_box else "NOT sandboxed: it can read every file of this user"}'
            f'{", as user " + c["team_user"] if c["team_user"] else ", as your own user (no team_user: see secure_setup.sh)"}'
            f'{", memory limit " + c["team_memory"] if c["team_memory"] else ""})', job)
        t1 = time.time()
        while True:
            time.sleep(2)
            txt = open(team_log, errors='replace').read() if os.path.isfile(team_log) else ''
            if 'navigation active after' in txt:
                break
            if not unit_active(TEAM_UNIT):
                raise RuntimeError('the team software exited during start-up - see ' + team_log + '\n' + txt[-1500:])
            if time.time() - t1 > c['start_timeout_s'] or job['stop']:
                raise RuntimeError('navigation did not become active - see ' + team_log)
        repaired = 'this guard had to make' in txt
        say(f'navigation active after {time.time() - t1:.0f} s{" (start-up was repaired by the guard)" if repaired else ""}', job)
        time.sleep(5)                                            # let the team nodes finish connecting

        # ---- mission
        st = http(f'http://127.0.0.1:{port}/admin/start/{token}', post=True)
        if st.get('state_text') != 'RUNNING':
            raise RuntimeError(f'mission did not start: {st}')
        job['stage'] = 'mission running'
        say('MISSION STARTED', job)
        limit = float(st.get('time_limit', 1500.0))
        dead_since, wall0 = None, time.time()
        while True:
            time.sleep(2)
            try:
                full = http(state_url)
            except Exception:
                if not unit_active(ORG_UNIT):
                    raise RuntimeError('simulator / referee stopped during the mission - see ' + os.path.join(logs, 'organiser.log'))
                continue
            st = full['status']
            job['mission'] = dict(st, behavior=full.get('behavior'))
            for e in reversed(full['events']):                    # the dashboard lists the newest first
                key = (e['t'], e['type'], e['description'])
                if key not in job.setdefault('_seen', set()) and e['type'] not in ('TIME_WARNING',):
                    job['_seen'].add(key)
                    if e['score_delta'] or e['type'] in ('HINT_RELEASED', 'AFTERSHOCK', 'MISSION_FINISHED', 'RULE_VIOLATION'):
                        say(f'  {e["t"]:6.0f}s {e["type"]}: {e["description"]} ({e["score_delta"]:+d})', job)
            if st['state_text'] == 'FINISHED':
                break
            used = folder_mb(home)
            if used > c.get('team_disk_mb', 4000):
                say(f'the team software wrote {used:.0f} MB to its folder (limit {c.get("team_disk_mb", 4000)} MB): ending the run', job)
                http(f'http://127.0.0.1:{port}/admin/abort/{token}', post=True)
            if not unit_active(TEAM_UNIT):
                dead_since = dead_since or time.time()
                if time.time() - dead_since > 15:
                    say('the team software is no longer running: ending the run (the score so far stands)', job)
                    http(f'http://127.0.0.1:{port}/admin/abort/{token}', post=True)
            if job['stop']:
                say('stopped by the organiser', job)
                http(f'http://127.0.0.1:{port}/admin/abort/{token}', post=True)
                job['stop'] = False
            if time.time() - wall0 > limit * 6 + 600:
                say('wall-clock limit reached (the simulator is far too slow): ending the run', job)
                http(f'http://127.0.0.1:{port}/admin/abort/{token}', post=True)
        job['stage'] = 'collecting result'
        summary, t2 = None, time.time()
        while time.time() - t2 < 60 and summary is None:
            time.sleep(1)
            for d in sorted(set(os.listdir(RUNS)) - before):
                p = os.path.join(RUNS, d, 'summary.json')
                if os.path.isfile(p):
                    time.sleep(0.5)
                    summary = json.load(open(p), parse_constant=lambda c: None)
                    summary['run'] = d
        if summary is None:
            raise RuntimeError('the referee wrote no summary.json')
        with open(os.path.join(RUNS, summary['run'], 'host.json'), 'w') as f:
            json.dump(dict(official=not (unofficial or insecure), insecure_reasons=insecure,
                           zip=os.path.basename(zip_path), zip_sha256=sha256(os.path.join(WORK, team, 'submitted.zip')), sandboxed=use_box,
                           team_memory=c['team_memory'], nav_startup_repaired=repaired, logs=logs, model_check=models,
                           wall_s=round(time.time() - wall0)), f, indent=1)
        summary.pop('trajectory', None)
        job['result'] = summary
        say(f'RESULT {team} on {wname}: score {summary["official_score"]}, rescued {len(summary["rescued"])}/'
            f'{summary["survivors_total"]}, {summary["finish_reason"]}, mission time {summary["elapsed_s"]:.0f} s', job)
        if summary.get('needs_review'):
            say(f'REVIEW NEEDED: physics {summary.get("physics", {}).get("counts", {})}, '
                f'unnamed private-topic endpoints {len(summary.get("graph_review", []))}, '
                f'publishers on referee topics {len(summary.get("topic_review", []))} - see summary.json', job)
        if summary.get('api_calls', {}).get('max_info_per_s', 0) > 100:
            say(f'NOTE: the team called get_mission_info up to {summary["api_calls"]["max_info_per_s"]} times a second '
                '(answered from a cache, no effect on the score)', job)
        return summary
    except Exception as e:
        job['error'] = str(e)
        say(f'FAILED: {e}', job)
        raise
    finally:
        try:     # a run that failed late still has a summary.json (SHUTDOWN): mark it, so it never counts 
            for d in (set(os.listdir(RUNS)) - before) if 'before' in locals() else ():
                hp = os.path.join(RUNS, d, 'host.json')
                if not os.path.exists(hp):
                    with open(hp, 'w') as f:
                        json.dump(dict(official=False, error=job.get('error') or 'run did not complete',
                                       insecure_reasons=insecure, zip=os.path.basename(zip_path)), f, indent=1)
        except OSError:
            pass
        unit_stop(TEAM_UNIT)
        if c.get('team_user'):      # your systemd cannot signal another user's processes: end them as that user
            subprocess.run(['sudo', '-n', '-u', c['team_user'], '/usr/bin/env', 'kill', '-KILL', '-1'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['systemctl', '--user', 'stop', f'{TEAM_UNIT}.scope'], stderr=subprocess.DEVNULL)
        unit_stop(ORG_UNIT)
        try:
            if 'logs' in locals():
                copy_team_logs(os.path.join(WORK, team, 'home', 'roslog'), os.path.join(logs, 'roslog'))
        except Exception:
            pass
        write_board()
        job['stage'] = 'failed' if job['error'] else 'finished'


def team_probe_code(port):
    """Python run as the team user before a run. Exit 3 = nothing reachable, 0 = TCP port answered,
    4 = the X display (screen) answered."""
    return ('import socket,sys\ns=socket.socket();s.settimeout(1)\n'
             f'tcp=s.connect_ex(("127.0.0.1",{port}))==0\n'
             'x=socket.socket(socket.AF_UNIX);x.settimeout(1)\n'
             'try:\n x.connect("\\0/tmp/.X11-unix/X0");x.send(b"l\\0\\x0b\\0\\0\\0\\0\\0\\0\\0\\0\\0");r=x.recv(1)\n'
             ' xok=r==b"\\x01"\nexcept Exception:\n xok=False\n'
             'sys.exit(0 if tcp else 4 if xok else 3)')


SALT_FILE = os.path.expanduser('~/.sparkx_organiser/world_salt')    # outside the stack and this tool: never shipped


def world_salt():
    """The organisers' secret salt for competition worlds, made once on this machine (keep a copy with the seeds:
    without it a world cannot be rebuilt)."""
    if not os.path.isfile(SALT_FILE):
        import secrets
        os.makedirs(os.path.dirname(SALT_FILE), mode=0o700, exist_ok=True)
        fd = os.open(SALT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32) + '\n')
        print(f'made a new secret world salt: {SALT_FILE} (back it up privately; never put it in the stack or git)')
    return SALT_FILE


def cmd_new_world(c, a):
    """Competition worlds: a random 63-bit seed and the secret salt, which keep them private. --practice makes a plain, publicly reproducible world."""
    import secrets
    if a.practice:
        seed = a.seed if a.seed is not None else secrets.randbits(31)
        salt_arg = ''
        print('PRACTICE world: anyone with the released generator can rebuild it from its seed. Never score with it.')
    else:
        seed = a.seed if a.seed is not None else secrets.randbits(63)
        if seed < 2 ** 40:
            print(f'refused: seed {seed} is small enough to guess or search. Leave --seed out (a random 63-bit seed is '
                  'drawn), or add --practice for a world that is not used for scores')
            return 2
        salt_arg = f' --salt-file {shlex.quote(world_salt())}'
    code, out = bash(f'{ros_env(c)}; ros2 run sparkx_worlds generate_world --name {shlex.quote(a.name)} --seed {seed} '
                     f'--size {a.size} --difficulty {a.difficulty} --lighting {a.lighting} --out {shlex.quote(WORLDS)}'
                     f'{salt_arg}', timeout=1800)
    print(out[-1500:])
    if code == 0 and not a.practice:
        print(f'seed {seed} (salted). It is also in {os.path.join(WORLDS, a.name, "private", "scenario.yaml")}; keep both '
              f'private, with a backup of {SALT_FILE}')
    return code


def check_team_user(c, envv, box):
    """Before team code runs as c['team_user']: that user must exist, sudo must work without a password,
    and the firewall must really stop it reaching this machine's TCP ports (dashboard, panel, simulator)."""
    u = c['team_user']
    if not os.path.isfile('/etc/sparkx/team-firewall.ok'):
        raise RuntimeError(f'team_user is "{u}" but secure_setup.sh has not been run (sudo bash hosting/secure_setup.sh)')
    # 3 = nothing reachable. 0 = the dashboard port answered. 4 = the X display (screen) answered.
    probe = team_probe_code(int(c['dashboard_port']))
    # the referee's dashboard is already listening at this point: the team user must not reach it
    r = subprocess.run(['sudo', '-n', '-u', u, '/usr/bin/env', '-i'] + envv + box + ['python3', '-c', probe],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        raise RuntimeError(f'the firewall for "{u}" is not active: it reached 127.0.0.1:{c["dashboard_port"]}. '
                           'Run: sudo systemctl start sparkx-team-firewall')
    if r.returncode == 4:
        raise RuntimeError(f'the screen (X display :0) accepts connections from "{u}" (e.g. "xhost +local:" is set). '
                           'Run "xhost -local:" (and "xhost -SI:localuser:' + u + '") before a run')
    if r.returncode != 3:
        raise RuntimeError(f'cannot start programs as "{u}" (sudo or sandbox failed): {(r.stderr or r.stdout)[-400:]}')


ML_KIT = dict(numpy='1.26.4', cv2='4.6.0', onnxruntime='1.32.0')      # the official ML kit of the rules (RULES.md §6): what every team may rely on

# The pre-run model check runs the stack's own sealed tools/model_selftest.py (--json), the very file teams
# test with, so the two can never disagree.
MODEL_SELFTEST = os.path.join(STACK, 'tools', 'model_selftest.py')


def model_check(c, envv, box, team_install, job):
    """RULES.md §6: before the run, open every model file of the team with the official ML kit (numpy, cv2.ml,
    onnxruntime: the three levels of the rules), inside the sandbox
    and with the team's environment. A missing kit is the machine's fault: the run is refused (no score). A
    model that does not load is the team's: it is recorded and the run goes ahead."""
    mdir = os.path.join(team_install, 'sparkx_team', 'share', 'sparkx_team', 'models')
    if not os.path.isdir(mdir) or not any(os.path.isfile(os.path.join(d, f)) and f != 'README.md'
                                          for d, _, fs in os.walk(mdir) for f in fs):
        return dict(models=[], note='no model files')
    with open(MODEL_SELFTEST) as f:
        probe = f.read()
    inner = ['bash', '-c', f'{ros_env(c, team_install)}; exec python3 -s -c "$0" --json "$1"', probe, mdir]
    pre = ['sudo', '-n', '-u', c['team_user'], '/usr/bin/env', '-i'] if c['team_user'] else ['env', '-i']
    # the team's memory limit applies here too, while the simulator runs
    unit = 'sparkx-modelcheck'
    subprocess.run(['systemctl', '--user', 'reset-failed', f'{unit}.scope'], stderr=subprocess.DEVNULL)
    scope = ['systemd-run', '--user', '--scope', '-q', f'--unit={unit}', '-p', f'MemoryMax={c["team_memory"]}',
             '-p', 'MemorySwapMax=0'] if c.get('team_memory') else []
    team_fault = None
    try:
        r = subprocess.run(scope + pre + envv + box + inner, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        unit_stop(unit)
        r, team_fault = None, 'loading the models took over 180 s'
    res = None
    if r is not None:
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            if r.returncode in (137, -9) or 'MemoryError' in (r.stderr or '') or 'Killed' in (r.stderr or ''):
                team_fault = f'loading the models ran out of the team\'s memory ({c.get("team_memory")})'
            else:
                raise RuntimeError(f'model check failed to run: {(r.stderr or r.stdout)[-600:]}')
    if team_fault:      # the team's own models: its fault, the run is scored (RULES.md §6)
        say(f'model check: DOES NOT LOAD ({team_fault}). That is the team\'s responsibility; the run goes ahead', job)
        return dict(models=[dict(file='*', status='fail', ok=False, error=team_fault)])
    if r.returncode == 3:
        raise RuntimeError('this machine lacks the official ML kit (RULES.md §6, hosting/README.md section 1): '
                           f'{res.get("error")}. Install it; this run must not be scored')
    kit = res.get('kit', {})
    for k, v in ML_KIT.items():
        if kit.get(k) != v:
            raise RuntimeError(f'the official ML kit is {k} {v}, this machine has {kit.get(k)}: install the '
                               'announced version (hosting/README.md section 1); this run must not be scored')
    for m in res['models']:
        if m.get('status') == 'fail':
            say(f'model check: {m["file"]}: DOES NOT LOAD ({m["error"]}). That is the team\'s responsibility '
                '(RULES.md §6); the run goes ahead', job)
        else:
            say(f'model check: {m["file"]}: ' + (f'level {m["level"]}, opens with the kit ({m["info"]})' if m.get('status') == 'ok'
                else m.get('info', 'data file')), job)
    return res


def folder_mb(path):
    total = 0
    for d, _, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(d, f)).st_blocks * 512
            except OSError:
                pass
    return total / 1e6


def copy_team_logs(src, dst, max_bytes=200 << 20):
    """Copy the team's ROS logs. The folder is written by team code, so: regular files only, symbolic
    links never followed (a link could point at a secret world or another team's zip), at most max_bytes."""
    import stat
    left = max_bytes
    # the folder itself, or one above it inside the team's home, may be a link put there by team code
    if os.path.islink(src) or os.path.islink(os.path.dirname(src)) or not os.path.isdir(src):
        return
    for d, dirs, files in os.walk(src, followlinks=False):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        for f in sorted(files):
            p = os.path.join(d, f)
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode) or st.st_size > left:
                continue
            out = os.path.join(dst, os.path.relpath(p, src))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as a, open(out, 'wb') as b:
                shutil.copyfileobj(a, b, 1 << 20)
            left -= st.st_size


# ------------------------------------------------------------------------------------ control panel
class Panel:
    def __init__(self, c):
        self.c = c
        self.job = new_job()
        self.queue = []
        self.checks = {}            # zip name -> (mtime, problems)
        self.lock = threading.Lock()
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                if not self.queue or self.job['stage'] not in ('idle', 'finished', 'failed'):
                    continue
                zip_name, world, gui = self.queue.pop(0)
                self.job = new_job(os.path.join(SUBS, zip_name), world)
                self.job['stage'] = 'queued'
            try:
                run(os.path.join(SUBS, zip_name), world, self.c, self.job, gui=gui)
            except Exception:
                pass

    def submissions(self):
        out = []
        runs = summaries()
        for n in sorted(os.listdir(SUBS)) if os.path.isdir(SUBS) else []:
            if not n.lower().endswith('.zip'):
                continue
            p = os.path.join(SUBS, n)
            m = os.path.getmtime(p)
            if self.checks.get(n, (0, None))[0] != m:
                self.checks[n] = (m, check(p))
            team = team_of(p)
            out.append(dict(zip=n, team=team, problems=self.checks[n][1], received=time.strftime('%d %b %H:%M', time.localtime(m)),
                            runs=[dict(world=s['world'], score=s.get('official_score', 0), rescued=len(s.get('rescued', [])),
                                       total=s.get('survivors_total', 0), reason=s.get('finish_reason', ''))
                                  for s in runs if s['team'] == team]))
        by_team = {}
        for x in out:
            by_team.setdefault(x['team'], []).append(x['zip'])
        for x in out:                        # two zips must never share a team name (one would hide the other)
            others = [z for z in by_team[x['team']] if z != x['zip']]
            if others:
                x['problems'] = list(x['problems']) + [f'same team name "{x["team"]}" as {", ".join(others)}: rename one']
        return out, runs

    def state(self):
        subs, runs = self.submissions()
        j = {k: v for k, v in self.job.items() if not k.startswith('_')}
        j['log'] = j['log'][-60:]
        j['dashboard'] = f'http://127.0.0.1:{self.c["dashboard_port"]}/?token={j["token"]}' if j['stage'] in (
            'starting team software', 'mission running') else ''
        return dict(job=j, queue=[dict(zip=z, world=w) for z, w, _ in self.queue], submissions=subs,
                    worlds=[dict(name=w['name'], kind=w['kind']) for w in worlds()], board=board(runs),
                    sandbox=sandbox_available() if self.c['sandbox'] != 'off' else False, stack=os.path.isdir(os.path.join(STACK, 'install')))


def serve(c):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    panel = Panel(c)
    # Team software runs on this machine and can reach 127.0.0.1, so the API answers only requests that
    # carry this key. It exists only in this process and in the address printed below.
    key = secrets.token_urlsafe(18)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype='application/json'):
            body = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def key_ok(self):
            return secrets.compare_digest(self.headers.get('X-Panel-Key', ''), key)

        def do_GET(self):
            if self.path.split('?')[0] in ('/', '/index.html'):
                return self.send(200, open(os.path.join(HERE, 'panel.html'), 'rb').read(), 'text/html; charset=utf-8')
            if self.path.split('?')[0] == '/brand/header.png':      # the partner header (public artwork, no key)
                p = os.path.join(STACK, 'src', 'sparkx_worlds', 'models', 'sparkx_media', 'brand', 'header_strip_dark.png')
                return self.send(200, open(p, 'rb').read(), 'image/png') if os.path.isfile(p) else self.send(404, '{}')
            if not self.key_ok():
                return self.send(403, '{"error":"panel key required"}')
            if self.path == '/api/state':
                return self.send(200, json.dumps(panel.state()))
            self.send(404, '{}')

        def do_POST(self):
            if not self.key_ok():            # a custom header also rules out cross-site form posts
                return self.send(403, '{"error":"panel key required"}')
            n = int(self.headers.get('Content-Length') or 0)
            try:
                q = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self.send(400, '{}')
            if self.path == '/api/run':
                names = [s for s in os.listdir(SUBS) if s.lower().endswith('.zip')]
                todo = ([z for z in names if not (panel.checks.get(z, (0, ['?']))[1])] if q.get('zip') == '*'
                        else [q.get('zip')])
                if any(z not in names for z in todo) or not any(w['name'] == q.get('world') for w in worlds()):
                    return self.send(400, '{"error":"unknown submission or world"}')
                with panel.lock:
                    panel.queue += [(z, q['world'], bool(q.get('gui'))) for z in sorted(todo)]
                return self.send(200, '{"ok":true}')
            if self.path == '/api/stop':
                with panel.lock:
                    panel.queue.clear()
                    panel.job['stop'] = True
                return self.send(200, '{"ok":true}')
            self.send(404, '{}')

    port = int(c['ui_port'])
    url = f'http://127.0.0.1:{port}/?key={key}'
    print(f'SparkX host control panel: {url}\n  (open this exact address; Ctrl-C quits and stops a run in progress)', flush=True)
    try:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        unit_stop(TEAM_UNIT)
        unit_stop(ORG_UNIT)


# ------------------------------------------------------------------------------------ commands
def cmd_setup(c, reseal=False):
    for d in (SUBS, WORLDS, RUNS, WORK):
        os.makedirs(d, exist_ok=True)
    print('building the organiser stack (a few minutes the first time) ...')
    for d in ('build', 'install', 'log'):                 # from scratch: no underlay of an earlier build survives
        shutil.rmtree(os.path.join(STACK, d), ignore_errors=True)
    code, out = bash(f'source {shlex.quote(os.path.expanduser(c["ros_setup"]))}; ' +
                     ''.join(f'source {shlex.quote(os.path.expanduser(p))}; ' for p in c['extra_setup']) +
                     'colcon build', cwd=STACK, timeout=3600, clean=True)
    print(out[-1200:])
    if code != 0:
        sys.exit('build failed')
    lock = shlex.quote(os.path.join(STACK, 'tools', 'sparkx_lock.py'))
    code, out = bash(f'python3 {lock} verify')
    if code != 0 and reseal:
        print('the stack differs from its seal; sealing the current state as the release (--reseal):')
        print(bash(f'python3 {lock} manifest')[1].strip())
        code, out = bash(f'python3 {lock} verify')
    print(out.strip())
    if code != 0:
        print('REFUSED: this copy of the stack differs from its seal, so no team may be run on it. Restore the\n'
              'files listed above (in a git clone: git status, then git checkout -- <file>). Only the organisers,\n'
              'after an intended change to a locked file, use "setup --reseal".')
    print(f'sandbox for team software: {"available (bubblewrap)" if sandbox_available() else "NOT available - install bubblewrap"}')
    return code


def main():
    ap = argparse.ArgumentParser(description='SparkX host', formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sp = sub.add_parser('setup')
    sp.add_argument('--reseal', action='store_true', help='organisers only: seal the current state of the stack as the release')
    sub.add_parser('ui')
    sub.add_parser('board')
    sub.add_parser('stop')
    k = sub.add_parser('check')
    k.add_argument('zip')
    r = sub.add_parser('run')
    r.add_argument('zip')
    r.add_argument('--world', required=True, help='name of a world in hosting/worlds or of a practice world, or a world folder')
    r.add_argument('--gui', action='store_true', help='show the Gazebo window')
    r.add_argument('--time-limit', type=float, default=0.0, help='override the world\'s time limit (seconds)')
    r.add_argument('--unofficial', action='store_true',
                   help='run on a machine that is not secured (no team_user/firewall): a test, kept off the leaderboard')
    w = sub.add_parser('new-world')
    w.add_argument('--name', required=True)
    w.add_argument('--seed', type=int, default=None,
                   help='leave out: a random 63-bit seed is drawn and the world is salted with your secret salt ')
    w.add_argument('--practice', action='store_true',
                   help='a practice world that anyone may rebuild: plain seed, no salt (never use it for scores)')
    w.add_argument('--size', default='medium', choices=['small', 'medium', 'large'])
    w.add_argument('--difficulty', default='normal', choices=['easy', 'normal', 'hard'])
    w.add_argument('--lighting', default='day', choices=['day', 'afternoon', 'smoky', 'dusk'])
    a = ap.parse_args()
    c = config()
    for d in (SUBS, WORLDS, RUNS, WORK):
        os.makedirs(d, exist_ok=True)
    if a.cmd == 'setup':
        return cmd_setup(c, a.reseal)
    if a.cmd == 'ui':
        return serve(c)
    if a.cmd == 'stop':
        unit_stop(TEAM_UNIT)
        unit_stop(ORG_UNIT)
        return 0
    if a.cmd == 'board':
        rows = write_board()
        print(f'{"#":>2} {"team":22s} {"total":>6} {"rescued":>8}  per world')
        for i, t in enumerate(rows, 1):
            per = ', '.join(f'{w}: {b["score"]} ({b["rescued"]}/{b["total"]})' for w, b in sorted(t['worlds'].items()))
            print(f'{i:>2} {t["team"]:22s} {t["total"]:>6} {t["rescued"]:>8}  {per}')
        print(f'written to {os.path.join(RESULTS, "leaderboard.csv")}')
        return 0
    if a.cmd == 'check':
        problems = check(a.zip)
        print(f'{os.path.basename(a.zip)} (team "{team_of(a.zip)}"): ' + ('ACCEPTED' if not problems else 'REJECTED'))
        for p in problems:
            print('  ' + p)
        return 1 if problems else 0
    if a.cmd == 'new-world':
        return cmd_new_world(c, a)
    if a.cmd == 'run':
        try:
            run(a.zip, a.world, c, gui=a.gui, time_limit=a.time_limit, unofficial=a.unofficial)
            return 0
        except KeyboardInterrupt:
            return 130
        except Exception:
            return 1


if __name__ == '__main__':
    sys.exit(main())
