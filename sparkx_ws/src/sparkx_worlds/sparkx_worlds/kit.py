"""Loader for the Blender-built world kit (models/sparkx_kit/*.obj, see tools/blender/build_kit.py).

Each part is a triangle soup split into material ROLES. `place()` bakes a transformed copy of a part
into a StaticGroup, mapping every role to one of the scanned world materials, so thousands of
instances still render as a handful of draw calls and take any colour the scenario asks for.
"""
import json
import math
import os

import numpy as np

from .geometry import rpy_matrix

# default role -> world material (override per call with `roles=`)
ROLE_MATERIAL = {
    'body': 'paint_gray', 'frame': 'paint_black', 'steel': 'paint_gray', 'dark': 'paint_black', 'glass': 'glass',
    'wood': 'wood', 'canvas': 'fabric_white', 'stone': 'concrete', 'stone_dark': 'concrete_dark',
    'concrete': 'concrete', 'rebar': 'burnt_metal', 'rust': 'burnt_metal', 'charred': 'charred',
    'white': 'paint_white', 'lamp': 'lamp_glass', 'rubber': 'rubber', 'crimson': 'brand_crimson',
    'ink': 'brand_ink', 'offwhite': 'brand_offwhite', 'yellow': 'paint_yellow', 'plastic': 'paint_blue',
    'cardboard': 'cardboard',
}

_CACHE = {}
_DIR = None


def kit_dir():
    global _DIR
    if _DIR is None:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'sparkx_kit')
        if os.path.isdir(here):
            _DIR = os.path.abspath(here)
        else:
            from ament_index_python.packages import get_package_share_directory
            _DIR = os.path.join(get_package_share_directory('sparkx_worlds'), 'models', 'sparkx_kit')
    return _DIR


def index():
    if '_index' not in _CACHE:
        with open(os.path.join(kit_dir(), 'kit.yaml')) as f:
            _CACHE['_index'] = json.load(f)
    return _CACHE['_index']


def load(name):
    """-> {role: (P (T,3,3) positions, N (T,3,3) normals)}"""
    if name in _CACHE:
        return _CACHE[name]
    v, vn, parts, role = [], [], {}, 'body'
    with open(os.path.join(kit_dir(), name + '.obj')) as f:
        for ln in f:
            if ln.startswith('v '):
                v.append(ln.split()[1:4])
            elif ln.startswith('vn '):
                vn.append(ln.split()[1:4])
            elif ln.startswith('usemtl '):
                role = ln.split()[1]
            elif ln.startswith('f '):
                idx = [c.split('/') for c in ln.split()[1:4]]
                parts.setdefault(role, []).append([(int(c[0]) - 1, int(c[2]) - 1) for c in idx])
    v, vn = np.array(v, np.float32), np.array(vn, np.float32)
    out = {}
    for role, faces in parts.items():
        fa = np.array(faces, np.int64)                       # (T, 3, 2)
        out[role] = (v[fa[:, :, 0]], vn[fa[:, :, 1]])
    _CACHE[name] = out
    return out


def bounds(name):
    e = index()[name]
    return np.array(e['min']), np.array(e['max'])


def place(group, name, pos, yaw=0.0, scale=(1.0, 1.0, 1.0), roles=None, rpy=None, only=None):
    """Bake kit part `name` into `group` at pos (x, y, z), rotated by yaw (or full rpy) and scaled.
    roles: {role: material} overrides; a role mapped to None is skipped."""
    rot = rpy_matrix(*(rpy if rpy is not None else (0.0, 0.0, yaw)))
    s = np.asarray(scale if np.ndim(scale) else (scale,) * 3, np.float32)
    m = (rot * s[None, :]).astype(np.float32)                 # R @ diag(s)
    mn = (rot / s[None, :]).astype(np.float32)                # normals: R @ diag(1/s)
    t = np.asarray(pos, np.float32)
    for role, (P, N) in load(name).items():
        if only and role not in only:
            continue
        mat = (roles or {}).get(role, ROLE_MATERIAL.get(role, 'paint_gray'))
        if mat is None:
            continue
        Pw = P @ m.T + t
        Nw = N @ mn.T
        Nw /= (np.linalg.norm(Nw, axis=2, keepdims=True) + 1e-9)
        group.mesh(mat).add_tris(Pw, Nw)


def fit(group, name, box_row, roles=None, pad=1.0):
    """Bake a unit-cube part (chunks, heaps) so that it fills the oriented box `box_row`
    [cx cy cz sx sy sz roll pitch yaw]."""
    place(group, name, box_row[:3], scale=[v * pad for v in box_row[3:6]], roles=roles, rpy=box_row[6:9])


def tube(group, material, path, radius, sides=4):
    """Thin cable / wire through a 3D polyline."""
    path = np.asarray(path, np.float32)
    ang = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    rings = []
    for i, p in enumerate(path):
        d = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        d /= (np.linalg.norm(d) + 1e-9)
        a = np.cross(d, [0, 0, 1.0])
        if np.linalg.norm(a) < 1e-3:
            a = np.array([1.0, 0, 0])
        a /= np.linalg.norm(a)
        b = np.cross(d, a)
        rings.append((p[None, :] + radius * (np.cos(ang)[:, None] * a[None, :] + np.sin(ang)[:, None] * b[None, :]),
                      np.cos(ang)[:, None] * a[None, :] + np.sin(ang)[:, None] * b[None, :]))
    P, N = [], []
    for (r0, n0), (r1, n1) in zip(rings[:-1], rings[1:]):
        for k in range(sides):
            k2 = (k + 1) % sides
            P += [[r0[k], r1[k], r1[k2]], [r0[k], r1[k2], r0[k2]]]
            N += [[n0[k], n1[k], n1[k2]], [n0[k], n1[k2], n0[k2]]]
    group.mesh(material).add_tris(np.array(P, np.float32), np.array(N, np.float32))
