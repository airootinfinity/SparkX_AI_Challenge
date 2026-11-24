"""Geometry helpers shared by the world generator and the referee.

* Oriented boxes stored as rows [cx, cy, cz, sx, sy, sz, roll, pitch, yaw]
* Vectorized segment-vs-box occlusion tests (line of sight)
* Rasterization of boxes into 2D occupancy grids (ground-truth maps)
"""
import math

import numpy as np
from PIL import Image, ImageDraw


def rpy_matrix(roll, pitch, yaw):
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def rpy_matrices(rpy):
    """(N,3) rpy -> (N,3,3) rotation matrices (world_from_box)."""
    r, p, y = rpy[:, 0], rpy[:, 1], rpy[:, 2]
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    m = np.empty((len(rpy), 3, 3))
    m[:, 0, 0] = cy * cp; m[:, 0, 1] = cy * sp * sr - sy * cr; m[:, 0, 2] = cy * sp * cr + sy * sr
    m[:, 1, 0] = sy * cp; m[:, 1, 1] = sy * sp * sr + cy * cr; m[:, 1, 2] = sy * sp * cr - cy * sr
    m[:, 2, 0] = -sp; m[:, 2, 1] = cp * sr; m[:, 2, 2] = cp * cr
    return m


def box_corners(row):
    c = np.asarray(row[:3], float)
    h = np.asarray(row[3:6], float) / 2
    r = rpy_matrix(*row[6:9])
    signs = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], float)
    return (signs * h) @ r.T + c


class BoxSet:
    """Set of oriented boxes supporting vectorized occlusion queries."""

    def __init__(self, rows, tags=None):
        rows = np.asarray(rows, float).reshape(-1, 9)
        self.rows = rows
        self.tags = list(tags) if tags is not None else [''] * len(rows)
        self.c = rows[:, :3]
        self.h = rows[:, 3:6] / 2.0
        self.R = rpy_matrices(rows[:, 6:9]) if len(rows) else np.zeros((0, 3, 3))
        # world AABBs for fast pre-filtering
        if len(rows):
            ext = np.abs(self.R) @ self.h[:, :, None]
            ext = ext[:, :, 0]
            self.amin = self.c - ext
            self.amax = self.c + ext
        else:
            self.amin = self.amax = np.zeros((0, 3))

    def __len__(self):
        return len(self.rows)

    def subset_near(self, pmin, pmax, margin=0.5):
        pmin = np.asarray(pmin) - margin
        pmax = np.asarray(pmax) + margin
        sel = np.all(self.amax >= pmin, axis=1) & np.all(self.amin <= pmax, axis=1)
        return np.nonzero(sel)[0]

    def segment_hits(self, p0, p1, idx=None, shrink=0.0):
        """Boolean array: which boxes (optionally restricted to idx) intersect segment p0->p1."""
        p0 = np.asarray(p0, float); p1 = np.asarray(p1, float)
        if idx is None:
            idx = self.subset_near(np.minimum(p0, p1), np.maximum(p0, p1), 0.05)
        if len(idx) == 0:
            return idx, np.zeros(0, bool)
        Rt = np.transpose(self.R[idx], (0, 2, 1))
        q0 = np.einsum('nij,nj->ni', Rt, p0 - self.c[idx])
        d = np.einsum('nij,j->ni', Rt, p1 - p0)
        h = np.maximum(self.h[idx] - shrink, 1e-4)
        with np.errstate(divide='ignore', invalid='ignore'):
            inv = 1.0 / d
            t1 = (-h - q0) * inv
            t2 = (h - q0) * inv
        tmin = np.where(np.isfinite(t1), np.minimum(t1, t2), -np.inf)
        tmax = np.where(np.isfinite(t1), np.maximum(t1, t2), np.inf)
        # parallel axes: inside slab -> no constraint, outside -> miss
        par = np.abs(d) < 1e-12
        outside = par & (np.abs(q0) > h)
        tmin = np.where(par, -np.inf, tmin)
        tmax = np.where(par, np.inf, tmax)
        enter = tmin.max(axis=1)
        leave = tmax.min(axis=1)
        hit = (enter <= leave) & (leave >= 0.0) & (enter <= 1.0) & ~outside.any(axis=1)
        return idx, hit

    def segment_blocked(self, p0, p1, exclude=None, shrink=0.0):
        idx, hit = self.segment_hits(p0, p1, shrink=shrink)
        if exclude is not None and len(idx):
            keep = ~np.isin(idx, np.asarray(list(exclude), int))
            hit = hit & keep
        return bool(hit.any())


def rasterize_boxes(rows, origin, res, shape, zmin, zmax, grid=None):
    """Mark cells covered by the XY projection of boxes overlapping the z band.

    origin: (x0, y0) world coordinate of cell (0,0) lower-left corner; shape (ny, nx).
    Returns uint8 grid with 1 = occupied (row 0 = y0).
    """
    ny, nx = shape
    img = Image.new('L', (nx, ny), 0) if grid is None else Image.fromarray((grid * 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    for row in np.asarray(rows, float).reshape(-1, 9):
        cs = box_corners(row)
        if cs[:, 2].max() < zmin or cs[:, 2].min() > zmax:
            continue
        pts = (cs[:, :2] - np.asarray(origin)) / res
        hull = convex_hull(pts)
        if len(hull) >= 3:
            draw.polygon([(float(x), float(y)) for x, y in hull], fill=255, outline=255)
        else:
            x, y = pts.mean(axis=0)
            draw.point((float(x), float(y)), fill=255)
    return (np.asarray(img) > 127).astype(np.uint8)


def rasterize_polygons(polys, origin, res, shape, value=1, grid=None):
    ny, nx = shape
    img = Image.new('L', (nx, ny), 0)
    draw = ImageDraw.Draw(img)
    for poly in polys:
        pts = (np.asarray(poly, float)[:, :2] - np.asarray(origin)) / res
        if len(pts) >= 3:
            draw.polygon([(float(x), float(y)) for x, y in pts], fill=255, outline=255)
    m = np.asarray(img) > 127
    out = np.zeros(shape, np.uint8) if grid is None else grid.copy()
    out[m] = value
    return out


def convex_hull(points):
    pts = sorted(set(map(tuple, np.round(np.asarray(points, float), 6))))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def disk_kernel(radius_cells):
    r = int(math.ceil(radius_cells))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= radius_cells * radius_cells


def dilate(grid, radius_cells):
    """Binary dilation by a disk (scipy if available, numpy fallback)."""
    try:
        from scipy.ndimage import binary_dilation
        return binary_dilation(grid.astype(bool), structure=disk_kernel(radius_cells)).astype(np.uint8)
    except ImportError:  # pragma: no cover
        k = disk_kernel(radius_cells)
        r = k.shape[0] // 2
        out = np.zeros_like(grid, bool)
        g = np.pad(grid.astype(bool), r)
        for dy, dx in zip(*np.nonzero(k)):
            out |= g[dy:dy + grid.shape[0], dx:dx + grid.shape[1]]
        return out.astype(np.uint8)


def flood_fill(free, seed_rc):
    """4-connected reachable region from seed (row, col) in boolean free grid."""
    from scipy.ndimage import label
    lab, _ = label(free.astype(bool))
    r, c = seed_rc
    if not (0 <= r < free.shape[0] and 0 <= c < free.shape[1]) or lab[r, c] == 0:
        return np.zeros_like(free, bool)
    return lab == lab[r, c]


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi
