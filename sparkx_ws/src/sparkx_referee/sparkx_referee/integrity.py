"""Stack integrity for the SparkX lock-down (pure standard library, no ROS).

A stack root is the folder that holds `TEAM_FILES.txt` (the allow-list of files a team may edit),
`src/` and, once generated, `LOCKED_MANIFEST.sha256` (SHA-256 of every locked file).

  locked files = every regular file under LOCKED_DIRS + LOCKED_TOP_FILES
                 minus the allow-list, minus build products and caches.

Used by tools/sparkx_lock.py (manifest / verify / pack / load / protect) and by the referee, which
verifies the stack when it starts and writes the result into summary.json.
"""
import hashlib
import os

ALLOW_FILE = 'TEAM_FILES.txt'
MANIFEST_FILE = 'LOCKED_MANIFEST.sha256'
LOCKED_DIRS = ('src', 'docs', 'docker', 'tools')
LOCKED_TOP_FILES = (ALLOW_FILE,)
SKIP_DIRS = {'__pycache__', '.git', 'build', 'install', 'log', '.pytest_cache', '.vscode', '.idea'}
SKIP_SUFFIXES = ('.pyc', '.pyo', '.swp', '.swo', '~')
SKIP_DIR_SUFFIXES = ('.egg-info',)


class Allow:
    """Parsed TEAM_FILES.txt: exact files plus data-only folders (entries ending with '/')."""

    def __init__(self, files, dirs):
        self.files = tuple(files)
        self.dirs = tuple(dirs)          # each ends with '/'

    def matches(self, rel):
        rel = rel.replace(os.sep, '/')
        return rel in self.files or any(rel.startswith(d) for d in self.dirs)

    def is_data(self, rel):
        return any(rel.replace(os.sep, '/').startswith(d) for d in self.dirs)


def read_allow(root):
    files, dirs = [], []
    with open(os.path.join(root, ALLOW_FILE)) as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            line = line.replace('\\', '/')
            while line.startswith('./'):
                line = line[2:]
            if line.startswith('/') or '..' in line.split('/'):
                raise ValueError(f'{ALLOW_FILE}: illegal path "{line}"')
            (dirs if line.endswith('/') else files).append(line)
    return Allow(files, dirs)


def is_stack_root(path):
    return os.path.isfile(os.path.join(path, ALLOW_FILE)) and os.path.isdir(os.path.join(path, 'src'))


def find_stack_root(hints=()):
    """First folder that looks like a stack root among: explicit hints, $SPARKX_STACK_ROOT, the
    parents of this file (works for a colcon install inside the workspace) and of the cwd."""
    starts = [h for h in hints if h]
    if os.environ.get('SPARKX_STACK_ROOT'):
        starts.append(os.environ['SPARKX_STACK_ROOT'])
    starts += [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]
    for s in starts:
        p = os.path.abspath(os.path.expanduser(s))
        while True:
            if is_stack_root(p):
                return p
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return None


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def locked_files(root, allow=None):
    """Sorted relative paths (posix separators) of every locked file. Symlinks are listed too (and
    hashed by their target text) so that swapping a file for a link is detected."""
    allow = allow or read_allow(root)
    out = [f for f in LOCKED_TOP_FILES if os.path.lexists(os.path.join(root, f))]
    for top in LOCKED_DIRS:
        base = os.path.join(root, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            keep = []
            for d in dirnames:
                full = os.path.join(dirpath, d)
                if d in SKIP_DIRS or d.endswith(SKIP_DIR_SUFFIXES):
                    continue
                if os.path.islink(full):                      # a linked folder counts as one entry
                    filenames.append(d)
                    continue
                keep.append(d)
            dirnames[:] = keep
            for fn in filenames:
                if fn.endswith(SKIP_SUFFIXES):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, '/')
                if not allow.matches(rel):
                    out.append(rel)
    return sorted(set(out))


def digest_of(root, rel):
    full = os.path.join(root, rel)
    if os.path.islink(full):
        return 'link:' + hashlib.sha256(os.readlink(full).encode()).hexdigest()
    return sha256_file(full)


def compute(root, allow=None):
    return {rel: digest_of(root, rel) for rel in locked_files(root, allow)}


def stack_digest(hashes):
    """One short fingerprint of the whole locked stack (what organisers compare at a glance)."""
    h = hashlib.sha256()
    for rel in sorted(hashes):
        h.update(f'{hashes[rel]}  {rel}\n'.encode())
    return h.hexdigest()


def write_manifest(root):
    hashes = compute(root)
    lines = ['# SparkX locked-stack manifest. Regenerate with: python3 tools/sparkx_lock.py manifest',
             f'# files: {len(hashes)}   stack digest: {stack_digest(hashes)}']
    lines += [f'{hashes[rel]}  {rel}' for rel in sorted(hashes)]
    with open(os.path.join(root, MANIFEST_FILE), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return hashes


def read_manifest(root):
    hashes = {}
    with open(os.path.join(root, MANIFEST_FILE)) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            digest, rel = line.rstrip('\n').split('  ', 1)
            hashes[rel] = digest
    return hashes


def verify(root):
    """Compare the stack with its manifest.

    Returns dict(status, root, digest, expected_digest, files, modified, added, removed, note):
    status is 'ok', 'modified' or 'unverified' (no stack root / no manifest / unreadable)."""
    res = dict(status='unverified', root=root or '', digest='', expected_digest='', files=0, modified=[], added=[],
               removed=[], note='')
    if not root or not is_stack_root(root):
        res['note'] = 'stack root not found (set the stack_root parameter or SPARKX_STACK_ROOT)'
        return res
    if not os.path.isfile(os.path.join(root, MANIFEST_FILE)):
        res['note'] = f'{MANIFEST_FILE} missing - run: python3 tools/sparkx_lock.py manifest'
        return res
    try:
        want = read_manifest(root)
        have = compute(root)
    except (OSError, ValueError) as e:
        res['note'] = f'could not read the stack: {e}'
        return res
    res['files'] = len(have)
    res['digest'] = stack_digest(have)
    res['expected_digest'] = stack_digest(want)
    res['modified'] = sorted(r for r in have if r in want and have[r] != want[r])
    res['added'] = sorted(r for r in have if r not in want)
    res['removed'] = sorted(r for r in want if r not in have)
    changed = res['modified'] or res['added'] or res['removed']
    res['status'] = 'modified' if changed else 'ok'
    if changed:
        res['note'] = (f'{len(res["modified"])} modified, {len(res["added"])} added, '
                       f'{len(res["removed"])} removed locked file(s)')
    return res
