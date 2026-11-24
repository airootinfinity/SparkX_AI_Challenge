"""Placement raster used while generating a world: prevents overlapping objects and keeps
reserved corridors (drive lanes, doorways, base zone) clear of random clutter."""
import math

import numpy as np

from .geometry import rasterize_boxes


class Placer:
    def __init__(self, xmin, ymin, xmax, ymax, res=0.2):
        self.res = res
        self.origin = (xmin, ymin)
        self.nx = int(math.ceil((xmax - xmin) / res))
        self.ny = int(math.ceil((ymax - ymin) / res))
        self.occ = np.zeros((self.ny, self.nx), bool)       # physical objects
        self.res_mask = np.zeros((self.ny, self.nx), bool)  # keep-clear zones

    def _cells(self, x0, y0, x1, y1):
        i0 = max(int((x0 - self.origin[0]) / self.res), 0)
        j0 = max(int((y0 - self.origin[1]) / self.res), 0)
        i1 = min(int(math.ceil((x1 - self.origin[0]) / self.res)), self.nx)
        j1 = min(int(math.ceil((y1 - self.origin[1]) / self.res)), self.ny)
        return j0, j1, i0, i1

    def reserve_rect(self, x0, y0, x1, y1):
        j0, j1, i0, i1 = self._cells(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self.res_mask[j0:j1, i0:i1] = True

    def _local_mask(self, row, margin):
        """Rasterize the (inflated) box footprint into its own window. Returns (mask, j0, i0)."""
        r = list(row)
        r[3] += 2 * margin
        r[4] += 2 * margin
        rad = 0.5 * math.hypot(r[3], r[4]) + self.res
        j0, j1, i0, i1 = self._cells(r[0] - rad, r[1] - rad, r[0] + rad, r[1] + rad)
        if j1 <= j0 or i1 <= i0:
            return np.zeros((0, 0), bool), j0, i0
        org = (self.origin[0] + i0 * self.res, self.origin[1] + j0 * self.res)
        m = rasterize_boxes([r], org, self.res, (j1 - j0, i1 - i0), -1e9, 1e9).astype(bool)
        return m, j0, i0

    def inside(self, x, y, rad=0.0):
        return (self.origin[0] + rad <= x <= self.origin[0] + self.nx * self.res - rad and
                self.origin[1] + rad <= y <= self.origin[1] + self.ny * self.res - rad)

    def box_free(self, row, margin=0.1, ignore_reserved=False):
        """row = [cx cy cz sx sy sz roll pitch yaw]; tests the XY footprint."""
        rad = 0.5 * math.hypot(row[3], row[4]) + margin
        if not self.inside(row[0], row[1], rad):
            return False
        m, j0, i0 = self._local_mask(row, margin)
        h, w = m.shape
        if (m & self.occ[j0:j0 + h, i0:i0 + w]).any():
            return False
        return ignore_reserved or not (m & self.res_mask[j0:j0 + h, i0:i0 + w]).any()

    def mark_box(self, row, margin=0.0):
        m, j0, i0 = self._local_mask(row, margin)
        h, w = m.shape
        self.occ[j0:j0 + h, i0:i0 + w] |= m

    def point_free(self, x, y, radius=0.3, ignore_reserved=False):
        return self.box_free([x, y, 0, 2 * radius, 2 * radius, 1, 0, 0, 0], 0.0, ignore_reserved)
