"""Ground truth utilities (organizer side): occupancy grid in the robot height band, reachable free
space for the SparkX UGV, line-of-sight tests and survivor approach points."""
import math

import numpy as np

from .geometry import BoxSet, dilate, flood_fill, rasterize_boxes

ROBOT_RADIUS = 0.45    # inscribed half-width 0.335 m + margin
BAND = (0.12, 0.85)    # chassis bottom .. mast top used for traversability
CAMERA_Z = 0.55
OCCLUDER_MIN_TOP = 0.35  # boxes lower than this never block line of sight
# Every survivor can be reached by a route on which the robot's centre stays this far from the centre
# of every fire. The largest hazard radius is 2.5 m, so a team that keeps 2.7 m clear of every fire
# it sees (plus its own half-width) still has a way to every person.
FIRE_ROUTE_CLEAR_M = 3.4


class GroundTruth:
    def __init__(self, rows, tags, bounds, start_xy, res=0.1, pad=3.0, fires=()):
        xmin, ymin, xmax, ymax = bounds
        self.res = res
        self.origin = (xmin - pad, ymin - pad)
        self.shape = (int(math.ceil((ymax - ymin + 2 * pad) / res)), int(math.ceil((xmax - xmin + 2 * pad) / res)))
        self.rows = np.asarray(rows, float).reshape(-1, 9)
        self.tags = list(tags)
        self.start = start_xy
        self.fires = [(float(f[0]), float(f[1])) for f in fires]      # fire centres (x, y)
        self.update()

    def update(self):
        solid = [r for r, t in zip(self.rows, self.tags) if t not in ('survivor_body',)]
        self.occ = rasterize_boxes(solid, self.origin, self.res, self.shape, *BAND)
        self.inflated = dilate(self.occ, ROBOT_RADIUS / self.res)
        self.reach = flood_fill(self.inflated == 0, self.cell(*self.start))
        # `safe`: the part of `reach` that can be driven to without passing near a fire
        self.fire_zone = np.zeros(self.shape, bool)
        if self.fires:
            yy, xx = np.mgrid[0:self.shape[0], 0:self.shape[1]]
            wx, wy = self.origin[0] + (xx + 0.5) * self.res, self.origin[1] + (yy + 0.5) * self.res
            for fx, fy in self.fires:
                self.fire_zone |= (wx - fx) ** 2 + (wy - fy) ** 2 < FIRE_ROUTE_CLEAR_M ** 2
            self.safe = flood_fill((self.inflated == 0) & ~self.fire_zone, self.cell(*self.start))
        else:
            self.safe = self.reach
        tops = self.rows[:, 2] + 0.5 * np.abs(self.rows[:, 5]) if len(self.rows) else np.zeros(0)
        sel = [i for i, (t, top) in enumerate(zip(self.tags, tops)) if top >= OCCLUDER_MIN_TOP]
        self.occ_idx = np.array(sel, int)
        self.occluders = BoxSet(self.rows[sel], [self.tags[i] for i in sel])

    def add_boxes(self, rows, tag):
        for r in rows:
            self.rows = np.vstack([self.rows, np.asarray(r, float)[None]])
            self.tags.append(tag)
        self.update()

    def cell(self, x, y):
        return int((y - self.origin[1]) / self.res), int((x - self.origin[0]) / self.res)

    def world(self, j, i):
        return self.origin[0] + (i + 0.5) * self.res, self.origin[1] + (j + 0.5) * self.res

    def reachable(self, x, y):
        j, i = self.cell(x, y)
        return 0 <= j < self.shape[0] and 0 <= i < self.shape[1] and bool(self.reach[j, i])

    def safely_reachable(self, x, y):
        """Reachable from the start without coming within FIRE_ROUTE_CLEAR_M of a fire."""
        j, i = self.cell(x, y)
        return 0 <= j < self.shape[0] and 0 <= i < self.shape[1] and bool(self.safe[j, i])

    def los(self, p0, p1, exclude_rows=()):
        """True if the segment p0->p1 (3D) is not blocked by any occluder box."""
        idx, hit = self.occluders.segment_hits(p0, p1, shrink=0.02)
        if not len(idx) or not hit.any():
            return True
        if exclude_rows:
            ex = [np.asarray(r, float) for r in exclude_rows]
            for k in idx[hit]:
                if not any(np.allclose(self.occluders.rows[k], e, atol=1e-4) for e in ex):
                    return False
            return True
        return False

    def approach_points(self, sx, sy, sz, own_row=None, radii=(1.0, 1.3, 1.6, 1.85), n=16):
        """Robot positions near a survivor with a clear line of sight to it, reachable from the start
        on a route that keeps clear of every fire."""
        out = []
        ex = [own_row] if own_row is not None else ()
        for r in radii:
            for k in range(n):
                a = 2 * math.pi * k / n
                px, py = sx + r * math.cos(a), sy + r * math.sin(a)
                if self.safely_reachable(px, py) and self.los((px, py, CAMERA_Z), (sx, sy, sz), ex):
                    out.append((px, py, r))
        return out

    def indoor_path(self, x, y, rect, margin=1.0, limit=60.0):
        """Driving distance (m) from (x, y) to the nearest point outside the building `rect`
        (x0, y0, x1, y1), over cells the robot can occupy on a fire-safe route; inf if there is no
        way out."""
        import heapq
        j0, i0 = self.cell(rect[0] - margin - 0.5, rect[1] - margin - 0.5)
        j1, i1 = self.cell(rect[2] + margin + 0.5, rect[3] + margin + 0.5)
        j0, i0, j1, i1 = max(j0, 0), max(i0, 0), min(j1, self.shape[0] - 1), min(i1, self.shape[1] - 1)
        free = self.safe[j0:j1 + 1, i0:i1 + 1]
        sj, si = self.cell(x, y)
        sj, si = sj - j0, si - i0
        if not (0 <= sj < free.shape[0] and 0 <= si < free.shape[1]):
            return 0.0
        if not free[sj, si]:                              # start from the nearest drivable cell
            jj, ii = np.nonzero(free)
            if len(jj) == 0:
                return math.inf
            k = int(np.argmin((jj - sj) ** 2 + (ii - si) ** 2))
            if math.hypot(jj[k] - sj, ii[k] - si) * self.res > 2.5:
                return math.inf
            sj, si = int(jj[k]), int(ii[k])
        dist = np.full(free.shape, np.inf)
        dist[sj, si] = 0.0
        pq = [(0.0, sj, si)]
        while pq:
            d, j, i = heapq.heappop(pq)
            if d > dist[j, i]:
                continue
            wx, wy = self.world(j + j0, i + i0)
            if wx < rect[0] - margin or wx > rect[2] + margin or wy < rect[1] - margin or wy > rect[3] + margin:
                return d
            if d > limit:
                break
            for dj, di, c in ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414),
                              (-1, 1, 1.414), (-1, -1, 1.414)):
                a, b = j + dj, i + di
                if 0 <= a < free.shape[0] and 0 <= b < free.shape[1] and free[a, b]:
                    nd = d + c * self.res
                    if nd < dist[a, b]:
                        dist[a, b] = nd
                        heapq.heappush(pq, (nd, a, b))
        return math.inf

    def path_length(self, a, b, step=0.5):
        """Shortest fire-safe path length between two points (coarse grid Dijkstra), inf if none."""
        from scipy.sparse import csgraph, csr_matrix
        k = max(1, int(round(step / self.res)))
        free = self.safe[::k, ::k]
        ny, nx = free.shape
        ids = -np.ones(free.shape, int)
        ids[free] = np.arange(free.sum())
        rows, cols, w = [], [], []
        for dj, di, c in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2))):
            sr, dr = slice(max(0, -dj), ny - max(0, dj)), slice(max(0, dj), ny - max(0, -dj))
            sc, dc = slice(max(0, -di), nx - max(0, di)), slice(max(0, di), nx - max(0, -di))
            src, dst = ids[sr, sc], ids[dr, dc]
            m = (src >= 0) & (dst >= 0)
            rows.append(src[m]); cols.append(dst[m]); w.append(np.full(m.sum(), c * step))
        g = csr_matrix((np.concatenate(w), (np.concatenate(rows), np.concatenate(cols))),
                       shape=(int(free.sum()),) * 2)

        def node(p):
            j, i = self.cell(*p)
            j, i = j // k, i // k
            best = None
            for dj in range(-2, 3):
                for di in range(-2, 3):
                    jj, ii = j + dj, i + di
                    if 0 <= jj < ny and 0 <= ii < nx and ids[jj, ii] >= 0:
                        d = dj * dj + di * di
                        if best is None or d < best[0]:
                            best = (d, ids[jj, ii])
            return None if best is None else best[1]

        na, nb = node(a), node(b)
        d = math.inf if na is None or nb is None else float(csgraph.dijkstra(g, directed=False, indices=na)[nb])
        if not math.isfinite(d) and k > 1:
            # the coarse grid can lose a narrow doorway; retry on a finer one before giving up
            return self.path_length(a, b, step=max(self.res, step / 2))
        return d


def street_points(scene, gt, spacing=2.0):
    pts = []
    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        if seg['axis'] == 'x':
            ys = (y0 + y1) / 2
            pts += [(x, ys) for x in np.arange(x0 - 4, x1 + 4, spacing)]
        else:
            xs = (x0 + x1) / 2
            pts += [(xs, y) for y in np.arange(y0 - 4, y1 + 4, spacing)]
    return [p for p in pts if gt.reachable(*p)]


def street_visibility(gt, spts, x, y, z, own_row=None, max_range=14.0):
    ex = [own_row] if own_row is not None else ()
    n = 0
    for px, py in spts:
        if math.hypot(px - x, py - y) <= max_range and gt.los((px, py, CAMERA_Z), (x, y, z), ex):
            n += 1
    return n
