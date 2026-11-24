"""Collision boxes for complex visual meshes (Fuel ruins) derived from their footprint in the
robot height band, so physics, LiDAR-scale obstacles and ground-truth maps agree."""
import math
import os

import numpy as np

from . import meshio
from .geometry import rasterize_polygons


def footprint_rects(tris, zmin=0.12, zmax=1.0, res=0.25, min_cells=2):
    """Return list of axis-aligned rectangles (x0, y0, x1, y1) covering the mesh footprint."""
    polys = meshio.clip_band(tris, zmin, zmax)
    if not polys:
        return []
    pts = np.concatenate(polys)
    x0, y0 = pts.min(axis=0) - res
    x1, y1 = pts.max(axis=0) + res
    nx, ny = int(math.ceil((x1 - x0) / res)), int(math.ceil((y1 - y0) / res))
    grid = np.zeros((ny, nx), np.uint8)
    for p in polys:
        if len(p) >= 3:
            grid = rasterize_polygons([p], (x0, y0), res, (ny, nx), 1, grid)
        else:
            for q in p:
                i, j = int((q[0] - x0) / res), int((q[1] - y0) / res)
                if 0 <= i < nx and 0 <= j < ny:
                    grid[j, i] = 1
    # close small holes so the robot cannot slip into mesh cracks
    from scipy.ndimage import binary_closing, binary_fill_holes
    g = binary_fill_holes(binary_closing(grid.astype(bool), iterations=2))
    rects = []
    used = np.zeros_like(g)
    for j in range(ny):
        i = 0
        while i < nx:
            if g[j, i] and not used[j, i]:
                i2 = i
                while i2 + 1 < nx and g[j, i2 + 1] and not used[j, i2 + 1]:
                    i2 += 1
                j2 = j
                while j2 + 1 < ny and g[j2 + 1, i:i2 + 1].all() and not used[j2 + 1, i:i2 + 1].any():
                    j2 += 1
                used[j:j2 + 1, i:i2 + 1] = True
                if (i2 - i + 1) * (j2 - j + 1) >= min_cells:
                    rects.append((x0 + i * res, y0 + j * res, x0 + (i2 + 1) * res, y0 + (j2 + 1) * res))
                i = i2 + 1
            else:
                i += 1
    return rects


def ruin_collisions(models_dir, entry, pose, height=1.6):
    """Collision rows for a catalog ruin placed at pose=(x, y, z, r, p, yaw)."""
    tris = meshio.load_mesh(os.path.join(models_dir, entry['_name'], entry['mesh']))
    s = entry.get('scale', 1.0)
    tris = meshio.transform(tris, (s, s, s), entry.get('mesh_pose', (0, 0, 0, 0, 0, 0)))
    tris = meshio.transform(tris, (1, 1, 1), pose)
    rows = []
    for x0, y0, x1, y1 in footprint_rects(tris):
        rows.append([(x0 + x1) / 2, (y0 + y1) / 2, height / 2, x1 - x0, y1 - y0, height, 0, 0, 0])
    return rows
