"""Tiny OBJ mesh builder used to batch static world geometry into few draw calls.

UVs are generated in world units (divided by a tile size) so textures repeat naturally on
long walls, streets and slabs. Flat per-face normals are written explicitly.
"""
import math
import os

import numpy as np


def rot_z(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def rot_rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


class ObjMesh:
    def __init__(self, tile=None):
        self.tile = tile  # real-world size of one texture repeat; overrides per-call tile sizes
        self.v = []   # xyz
        self.vt = []  # uv
        self.vn = []  # normals
        self.f = []   # ((vi, ti, ni) x n)
        self.tris = []  # baked kit geometry: list of (P (T,3,3), N (T,3,3), UV (T,3,2))

    def empty(self):
        return not self.f and not self.tris

    def add_tris(self, P, N, UV=None):
        """Raw triangles with per-corner normals (kit parts). Without UVs they are box-projected
        from world coordinates so the material keeps its real-world scale at any part size."""
        P = np.asarray(P, np.float32)
        N = np.asarray(N, np.float32)
        if UV is None:
            tile = self.tile or 2.0
            fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            ax = np.abs(fn).argmax(axis=1)                       # dominant axis of each face
            UV = np.empty(P.shape[:2] + (2,), np.float32)
            for a, (i0, i1) in enumerate(((1, 2), (0, 2), (0, 1))):
                m = ax == a
                UV[m, :, 0] = P[m][:, :, i0] / tile
                UV[m, :, 1] = P[m][:, :, i1] / tile
        self.tris.append((P, N, np.asarray(UV, np.float32)))

    def add_poly(self, pts, uvs, normal=None):
        pts = [np.asarray(p, float) for p in pts]
        if normal is None:
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            ln = np.linalg.norm(n)
            normal = n / ln if ln > 1e-12 else np.array([0, 0, 1.0])
        base_v, base_t = len(self.v), len(self.vt)
        self.vn.append(tuple(normal))
        ni = len(self.vn)
        face = []
        for i, (p, uv) in enumerate(zip(pts, uvs)):
            self.v.append(tuple(p)); self.vt.append(tuple(uv))
            face.append((base_v + i + 1, base_t + i + 1, ni))
        self.f.append(face)

    def add_quad_world_uv(self, pts, tile=2.0, uv_axes=None):
        """Quad whose UVs are the projection of its corners on two in-plane axes / tile."""
        tile = self.tile or tile
        pts = [np.asarray(p, float) for p in pts]
        e1 = pts[1] - pts[0]; e2 = pts[3] - pts[0]
        n = np.cross(e1, e2); n /= (np.linalg.norm(n) + 1e-12)
        if uv_axes is None:
            a1 = e1 / (np.linalg.norm(e1) + 1e-12)
            a2 = np.cross(n, a1)
            # keep texture "up" pointing +z on vertical faces
            if abs(n[2]) < 0.5:
                a2 = np.array([0, 0, 1.0])
                a1 = np.cross(a2, n); a1 /= (np.linalg.norm(a1) + 1e-12)
        else:
            a1, a2 = uv_axes
        uvs = [(float(np.dot(p, a1) / tile), float(np.dot(p, a2) / tile)) for p in pts]
        self.add_poly(pts, uvs, n)

    def add_box(self, center, size, rpy=(0, 0, 0), tile=2.0, faces='all'):
        """Axis-aligned (in its own frame) box with world-scale UVs on each face."""
        c = np.asarray(center, float)
        hx, hy, hz = [s / 2.0 for s in size]
        r = rot_rpy(*rpy)
        corners = np.array([[sx * hx, sy * hy, sz * hz] for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)])
        w = corners @ r.T + c
        # corner index: (sx,sy,sz) -> i = ((sz>0)*4 + (sy>0)*2 + (sx>0))
        quads = {
            'bottom': (0, 2, 3, 1), 'top': (4, 5, 7, 6),
            '-y': (0, 1, 5, 4), '+y': (2, 6, 7, 3),
            '-x': (0, 4, 6, 2), '+x': (1, 3, 7, 5),
        }
        for name, q in quads.items():
            if faces != 'all' and name not in faces:
                continue
            self.add_quad_world_uv([w[i] for i in q], tile)

    def add_rect_xy(self, x0, y0, x1, y1, z=0.0, tile=4.0, u_along=None, v_span=None):
        """Ground quad. If u_along='x'/'y', u follows that axis (per tile) and v spans the
        perpendicular width 0..1 (used for lane-marked street textures)."""
        pts = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        if u_along is None:
            tile = self.tile or tile
        if u_along == 'x':
            uvs = [(x0 / tile, 0), (x1 / tile, 0), (x1 / tile, 1), (x0 / tile, 1)]
        elif u_along == 'y':
            uvs = [(y0 / tile, 1), (y0 / tile, 0), (y1 / tile, 0), (y1 / tile, 1)]
        else:
            uvs = [(x / tile, y / tile) for x, y, _ in pts]
        self.add_poly(pts, uvs, (0, 0, 1.0))

    def add_quad_centered(self, center, size_x, size_y, yaw=0.0, z=0.0):
        """Ground decal quad with 0..1 UVs (for single images like scorch marks / helipad)."""
        r = rot_z(yaw)
        hx, hy = size_x / 2, size_y / 2
        loc = np.array([[-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0]])
        w = loc @ r.T + np.array([center[0], center[1], z])
        self.add_poly(list(w), [(0, 0), (1, 0), (1, 1), (0, 1)], (0, 0, 1.0))

    def add_blob(self, center, radius, rng, z=0.0, tile=3.0, n=18, jitter=0.22):
        """Irregular ground patch (dust, debris spill, scorch) with world-scale UVs."""
        tile = self.tile or tile
        cx, cy = center
        rim = []
        for k in range(n):
            a = 2 * math.pi * k / n
            r = radius * (1 + float(rng.uniform(-jitter, jitter)))
            rim.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
        for k in range(n):
            p0, p1 = rim[k], rim[(k + 1) % n]
            pts = [(cx, cy, z), p0, p1]
            self.add_poly(pts, [(p[0] / tile, p[1] / tile) for p in pts], (0, 0, 1.0))

    def add_panel(self, center, width, height, yaw, uv=((0, 0), (1, 1)), double=False):
        """Upright rectangle facing direction `yaw` (its outward normal) showing one image that reads
        left-to-right for a viewer standing in front of it. uv = ((u0, v0), (u1, v1)).
        Facing the panel, the viewer's right-hand side is +t where t = (-sin yaw, cos yaw)."""
        cx, cy, cz = center
        nx, ny = math.cos(yaw), math.sin(yaw)
        tx, ty = -ny, nx
        (u0, v0), (u1, v1) = uv
        hw, hh = width / 2, height / 2
        p = lambda s, v: (cx + s * tx, cy + s * ty, cz + v)  # noqa: E731
        uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        self.add_poly([p(-hw, -hh), p(hw, -hh), p(hw, hh), p(-hw, hh)], uvs, (nx, ny, 0))
        if double:                                             # readable from behind as well
            self.add_poly([p(hw, -hh), p(-hw, -hh), p(-hw, hh), p(hw, hh)], uvs, (-nx, -ny, 0))

    def add_cylinder(self, center, radius, height, segments=20, tile=None):
        cx, cy, cz = center
        tile = self.tile or tile
        circ = 2 * math.pi * radius
        for i in range(segments):
            a0 = 2 * math.pi * i / segments; a1 = 2 * math.pi * (i + 1) / segments
            p0 = (cx + radius * math.cos(a0), cy + radius * math.sin(a0))
            p1 = (cx + radius * math.cos(a1), cy + radius * math.sin(a1))
            u0, u1 = i / segments, (i + 1) / segments
            if tile:
                u0, u1 = u0 * circ / tile, u1 * circ / tile
            vt = height / tile if tile else 1.0
            n = (math.cos((a0 + a1) / 2), math.sin((a0 + a1) / 2), 0)
            self.add_poly([(p0[0], p0[1], cz), (p1[0], p1[1], cz), (p1[0], p1[1], cz + height),
                           (p0[0], p0[1], cz + height)], [(u0, 0), (u1, 0), (u1, vt), (u0, vt)], n)
        top = [(cx + radius * math.cos(2 * math.pi * i / segments), cy + radius * math.sin(2 * math.pi * i / segments),
                cz + height) for i in range(segments)]
        self.add_poly(top, [(0.5 + 0.5 * math.cos(2 * math.pi * i / segments),
                             0.5 + 0.5 * math.sin(2 * math.pi * i / segments)) for i in range(segments)], (0, 0, 1))

    def add_heightfield_ring(self, center, radii, heights, segments=40, jitter=None, tile=3.0, rng=None):
        """Radial surface of revolution (crater): radii[i] -> heights[i]."""
        cx, cy = center
        tile = self.tile or tile
        rings = []
        for j, (r, h) in enumerate(zip(radii, heights)):
            ring = []
            for i in range(segments):
                a = 2 * math.pi * i / segments
                rr = r * (1 + (rng.normal(0, jitter) if (rng is not None and jitter and 0 < j < len(radii) - 1) else 0))
                hh = h * (1 + (rng.normal(0, jitter * 2) if (rng is not None and jitter and 0 < j < len(radii) - 1) else 0))
                ring.append(np.array([cx + rr * math.cos(a), cy + rr * math.sin(a), max(hh, -0.05)]))
            rings.append(ring)
        for j in range(len(rings) - 1):
            for i in range(segments):
                i2 = (i + 1) % segments
                q = [rings[j][i], rings[j + 1][i], rings[j + 1][i2], rings[j][i2]]
                n = np.cross(q[1] - q[0], q[3] - q[0])
                if n[2] < 0:
                    q = q[::-1]
                uvs = [(p[0] / tile, p[1] / tile) for p in q]
                self.add_poly(q, uvs)
        return rings

    def triangles(self):
        """(N,3,3) triangles (fan-triangulated) for ground-truth rasterization."""
        out = []
        v = np.array(self.v)
        for face in self.f:
            idx = [fi[0] - 1 for fi in face]
            for k in range(1, len(idx) - 1):
                out.append(v[[idx[0], idx[k], idx[k + 1]]])
        return np.array(out) if out else np.zeros((0, 3, 3))

    def write(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('# SparkX generated mesh\n')
            f.writelines(f'v {x:.4f} {y:.4f} {z:.4f}\n' for x, y, z in self.v)
            f.writelines(f'vt {u:.4f} {t:.4f}\n' for u, t in self.vt)
            f.writelines(f'vn {a:.4f} {b:.4f} {c:.4f}\n' for a, b, c in self.vn)
            for face in self.f:
                f.write('f ' + ' '.join(f'{a}/{b}/{c}' for a, b, c in face) + '\n')
            if self.tris:
                P = np.concatenate([t[0] for t in self.tris]).reshape(-1, 3)
                N = np.concatenate([t[1] for t in self.tris]).reshape(-1, 3)
                UV = np.concatenate([t[2] for t in self.tris]).reshape(-1, 2)
                out = []
                idx = []
                for arr, tag, base, prec in ((P, 'v', len(self.v), 3), (UV, 'vt', len(self.vt), 3), (N, 'vn', len(self.vn), 2)):
                    q = np.round(arr, prec)
                    uniq, inv = np.unique(q, axis=0, return_inverse=True)   # share identical vertices
                    fmt_ = f'%.{prec}f'
                    out.append('\n'.join(tag + ' ' + ' '.join(fmt_ % c for c in row) for row in uniq))
                    idx.append(inv.reshape(-1) + base + 1)
                f.write('\n'.join(out) + '\n')
                iv, it, in_ = (i.reshape(-1, 3) for i in idx)
                f.write('\n'.join(f'f {iv[k, 0]}/{it[k, 0]}/{in_[k, 0]} {iv[k, 1]}/{it[k, 1]}/{in_[k, 1]} '
                                  f'{iv[k, 2]}/{it[k, 2]}/{in_[k, 2]}' for k in range(len(iv))) + '\n')
