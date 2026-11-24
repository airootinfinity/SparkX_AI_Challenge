"""Minimal mesh loaders (COLLADA .dae and Wavefront .obj) returning triangles in metres.

Used by the world generator to compute asset extents and rasterize ground-truth
occupancy footprints. Handles COLLADA <unit>, <up_axis>, node <matrix>/<translate>/
<rotate>/<scale> hierarchies, and <triangles>/<polylist>/<polygons> primitives.
"""
import re
import xml.etree.ElementTree as ET

import numpy as np


def _strip_ns(root):
    for el in root.iter():
        if '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    return root


def _node_matrix(node):
    m = np.eye(4)
    for child in node:
        tag = child.tag
        vals = [float(v) for v in (child.text or '').split()]
        if tag == 'matrix' and len(vals) == 16:
            m = m @ np.array(vals).reshape(4, 4)
        elif tag == 'translate' and len(vals) == 3:
            t = np.eye(4); t[:3, 3] = vals; m = m @ t
        elif tag == 'rotate' and len(vals) == 4:
            ax = np.array(vals[:3]); ax = ax / (np.linalg.norm(ax) + 1e-12)
            a = np.radians(vals[3]); c, s = np.cos(a), np.sin(a)
            x, y, z = ax
            r = np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                          [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                          [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])
            t = np.eye(4); t[:3, :3] = r; m = m @ t
        elif tag == 'scale' and len(vals) == 3:
            t = np.diag(vals + [1.0]); m = m @ t
    return m


def _geometry_triangles(geom):
    """Return (N,3,3) triangles of a <geometry> element in its local frame."""
    mesh = geom.find('mesh')
    if mesh is None:
        return np.zeros((0, 3, 3))
    sources = {}
    for src in mesh.findall('source'):
        fa = src.find('float_array')
        if fa is None or not fa.text:
            continue
        arr = np.array(fa.text.split(), dtype=float)
        acc = src.find('technique_common/accessor')
        stride = int(acc.get('stride', 3)) if acc is not None else 3
        sources[src.get('id')] = arr.reshape(-1, stride)[:, :3]
    verts_map = {}
    for v in mesh.findall('vertices'):
        for inp in v.findall('input'):
            if inp.get('semantic') == 'POSITION':
                verts_map[v.get('id')] = inp.get('source').lstrip('#')
    tris = []
    for prim in list(mesh):
        if prim.tag not in ('triangles', 'polylist', 'polygons', 'trifans', 'tristrips'):
            continue
        inputs = prim.findall('input')
        if not inputs:
            continue
        stride = max(int(i.get('offset', 0)) for i in inputs) + 1
        vin = [i for i in inputs if i.get('semantic') == 'VERTEX']
        if not vin:
            continue
        off = int(vin[0].get('offset', 0))
        sid = vin[0].get('source').lstrip('#')
        pos = sources.get(verts_map.get(sid, sid))
        if pos is None:
            continue
        plist = prim.findall('p')
        if prim.tag == 'triangles':
            for p in plist:
                idx = np.array(p.text.split(), dtype=int).reshape(-1, stride)[:, off]
                idx = idx[: len(idx) // 3 * 3].reshape(-1, 3)
                tris.append(pos[idx])
        elif prim.tag == 'polylist':
            vc = prim.find('vcount')
            counts = np.array(vc.text.split(), dtype=int) if vc is not None and vc.text else []
            idx = np.array(plist[0].text.split(), dtype=int).reshape(-1, stride)[:, off] if plist else []
            k = 0
            out = []
            for c in counts:
                poly = idx[k:k + c]; k += c
                for j in range(1, c - 1):
                    out.append((poly[0], poly[j], poly[j + 1]))
            if out:
                tris.append(pos[np.array(out)])
        elif prim.tag == 'polygons':
            out = []
            for p in plist:
                poly = np.array(p.text.split(), dtype=int).reshape(-1, stride)[:, off]
                for j in range(1, len(poly) - 1):
                    out.append((poly[0], poly[j], poly[j + 1]))
            if out:
                tris.append(pos[np.array(out)])
    return np.concatenate(tris) if tris else np.zeros((0, 3, 3))


def load_dae(path):
    txt = open(path, 'rb').read().decode('utf-8', 'ignore')
    root = _strip_ns(ET.fromstring(txt))
    unit = root.find('asset/unit')
    scale = float(unit.get('meter', 1.0)) if unit is not None else 1.0
    up = root.find('asset/up_axis')
    up = up.text.strip() if up is not None and up.text else 'Y_UP'
    geoms = {g.get('id'): g for g in root.iter('geometry')}
    cache = {}

    def geo(gid):
        if gid not in cache:
            cache[gid] = _geometry_triangles(geoms[gid]) if gid in geoms else np.zeros((0, 3, 3))
        return cache[gid]

    out = []
    controllers = {c.get('id'): c for c in root.iter('controller')}

    def add(t, m):
        if len(t):
            h = np.concatenate([t.reshape(-1, 3), np.ones((t.shape[0] * 3, 1))], axis=1)
            out.append((h @ m.T)[:, :3].reshape(-1, 3, 3))

    def walk(node, parent_m):
        m = parent_m @ _node_matrix(node)
        for ig in node.findall('instance_geometry'):
            add(geo(ig.get('url', '').lstrip('#')), m)
        for ic in node.findall('instance_controller'):
            ctrl = controllers.get(ic.get('url', '').lstrip('#'))
            skin = ctrl.find('skin') if ctrl is not None else None
            if skin is None:
                continue
            bsm = skin.find('bind_shape_matrix')
            b = np.array(bsm.text.split(), float).reshape(4, 4) if bsm is not None and bsm.text else np.eye(4)
            add(geo(skin.get('source', '').lstrip('#')), m @ b)
        for child in node.findall('node'):
            walk(child, m)

    scenes = list(root.iter('visual_scene'))
    if scenes:
        for n in scenes[0].findall('node'):
            walk(n, np.eye(4))
    else:
        for gid in geoms:
            out.append(geo(gid))
    tris = np.concatenate(out) if out else np.zeros((0, 3, 3))
    tris = tris * scale
    if up == 'Y_UP':  # convert to Z-up: (x, y, z) -> (x, -z, y)
        tris = np.stack([tris[..., 0], -tris[..., 2], tris[..., 1]], axis=-1)
    elif up == 'X_UP':
        tris = np.stack([-tris[..., 1], tris[..., 0], tris[..., 2]], axis=-1)
    return tris


def load_obj(path):
    verts, faces = [], []
    with open(path, errors='ignore') as f:
        for line in f:
            if line.startswith('v '):
                verts.append([float(v) for v in line.split()[1:4]])
            elif line.startswith('f '):
                idx = [int(tok.split('/')[0]) for tok in line.split()[1:]]
                for j in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[j], idx[j + 1]))
    v = np.array(verts, dtype=float)
    fa = np.array(faces, dtype=int)
    fa = np.where(fa > 0, fa - 1, len(v) + fa)
    return v[fa] if len(fa) else np.zeros((0, 3, 3))


def load_mesh(path):
    p = path.lower()
    if p.endswith('.dae'):
        return load_dae(path)
    if p.endswith('.obj'):
        return load_obj(path)
    raise ValueError(f'unsupported mesh {path}')


def rpy_matrix(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def transform(tris, scale=(1, 1, 1), pose=(0, 0, 0, 0, 0, 0)):
    """Apply SDF-style <scale> then <pose> (x y z roll pitch yaw)."""
    t = tris * np.asarray(scale, float)
    r = rpy_matrix(*pose[3:6])
    return t @ r.T + np.asarray(pose[:3], float)


def clip_band(tris, zmin, zmax):
    """Clip triangles to zmin <= z <= zmax. Returns list of XY polygons (numpy (k,2))."""
    polys = []
    lo = tris[..., 2].min(axis=1); hi = tris[..., 2].max(axis=1)
    sel = (hi >= zmin) & (lo <= zmax)
    for tri in tris[sel]:
        poly = list(tri)
        for z0, keep_above in ((zmin, True), (zmax, False)):
            out = []
            n = len(poly)
            for i in range(n):
                a, b = poly[i], poly[(i + 1) % n]
                ina = a[2] >= z0 if keep_above else a[2] <= z0
                inb = b[2] >= z0 if keep_above else b[2] <= z0
                if ina:
                    out.append(a)
                if ina != inb:
                    t = (z0 - a[2]) / (b[2] - a[2] + 1e-12)
                    out.append(a + t * (b - a))
            poly = out
            if len(poly) < 3:
                break
        if len(poly) >= 3:
            polys.append(np.array(poly)[:, :2])
        elif len(poly) == 2:
            polys.append(np.array(poly)[:, :2])
    return polys


def extents(tris):
    pts = tris.reshape(-1, 3)
    return pts.min(axis=0), pts.max(axis=0)
