"""End-of-mission evaluation: map quality vs ground truth, semantic record accuracy, trajectory stats."""
import math

import numpy as np


def evaluate_map(grid_msg, ref, map_to_world):
    """grid_msg: nav_msgs/OccupancyGrid (team map frame). Returns dict with IoU/coverage and score 0..1."""
    if grid_msg is None or grid_msg.info.width == 0:
        return dict(score=0.0, note='no map')
    info = grid_msg.info
    data = np.asarray(grid_msg.data, np.int16).reshape(info.height, info.width)
    oq = info.origin.orientation
    oyaw = math.atan2(2 * (oq.w * oq.z + oq.x * oq.y), 1 - 2 * (oq.y ** 2 + oq.z ** 2))
    jj, ii = np.nonzero(data >= 0)
    if len(jj) == 0:
        return dict(score=0.0, note='empty map')
    lx = (ii + 0.5) * info.resolution
    ly = (jj + 0.5) * info.resolution
    c, s = math.cos(oyaw), math.sin(oyaw)
    mx = info.origin.position.x + c * lx - s * ly
    my = info.origin.position.y + s * lx + c * ly
    wx, wy = map_to_world(mx, my)
    occ_team = data[jj, ii] >= 65
    gi = np.floor((wx - ref.gt_origin[0]) / ref.gt_res).astype(int)
    gj = np.floor((wy - ref.gt_origin[1]) / ref.gt_res).astype(int)
    ok = (gi >= 0) & (gj >= 0) & (gi < ref.gt_occ.shape[1]) & (gj < ref.gt_occ.shape[0])
    outside_free = int((~occ_team & ~ok).sum())                  # "free" claimed outside the arena: wrong (v1.4)
    gi, gj, occ_team = gi[ok], gj[ok], occ_team[ok]
    from scipy.ndimage import binary_dilation
    gt_occ = ref.gt_occ.astype(bool)
    gt_occ_tol = binary_dilation(gt_occ, iterations=3)          # 0.3 m tolerance
    reach = ref.gt_reach.astype(bool)
    # free space is right where the rover could really go (reachable ground, grown by 0.5 m so free cells
    # next to walls still count); "free" inside buildings or outside the arena is wrong (v1.4)
    free_ok_grid = binary_dilation(reach, iterations=5) & ~binary_dilation(gt_occ, iterations=1)
    tp = int((occ_team & gt_occ_tol[gj, gi]).sum())
    fp = int((occ_team & ~gt_occ_tol[gj, gi]).sum())
    free_team = ~occ_team
    free_ok = int((free_team & free_ok_grid[gj, gi]).sum())
    precision_occ = tp / max(1, tp + fp)
    precision_free = free_ok / max(1, int(free_team.sum()) + outside_free)
    seen = np.zeros_like(reach)
    seen[gj[free_team], gi[free_team]] = True
    seen_d = binary_dilation(seen, iterations=2)
    coverage = (seen_d & reach).sum() / max(1, reach.sum())
    # walls next to the space you mapped as free must be on your map too (v1.4): a map that is all
    # "free" plus one wall cell no longer scores
    team_occ_grid = np.zeros_like(reach)
    team_occ_grid[gj[occ_team], gi[occ_team]] = True
    border = gt_occ & binary_dilation(seen, iterations=3)
    recall_occ = (border & binary_dilation(team_occ_grid, iterations=3)).sum() / max(1, border.sum())
    f1_occ = 2 * precision_occ * recall_occ / max(1e-9, precision_occ + recall_occ)
    score = coverage * f1_occ * precision_free
    return dict(score=float(score), coverage=float(coverage), precision_occupied=float(precision_occ),
                recall_occupied=float(recall_occ),
                precision_free=float(precision_free), cells=int(len(gi)))


def evaluate_semantics(objects, ref, map_to_world, tol=2.0):
    """objects: list of dicts(object_class, color, label, x, y, status). Returns score 0..1 and details.
    v1.4: an object that matches a real thing the clues do not use (another landmark, a numbered marker)
    is neutral instead of false; a landmark that has a colour needs the right colour to count (without it: neutral); and false objects
    cost in full (score x precision), so listing objects everywhere no longer pays."""
    lms = [lm for lm in ref.sc['landmarks'] if lm.get('unique')]
    others = [lm for lm in ref.sc['landmarks'] if not lm.get('unique')]
    markers = ref.sc.get('markers') or []
    surv = list(ref.survivors.values())
    hits_lm, hits_sv, false, neutral = 0, 0, 0, 0
    used = set()

    def lm_match(lm, o, wx, wy, colour=True):
        return (lm['cls'] == o['object_class'] and (not colour or not lm['color'] or lm['color'] == o.get('color')) and
                math.hypot(lm['x'] - wx, lm['y'] - wy) <= tol + 0.5 * max(lm['size'][:2]))
    for o in objects:
        wx, wy = map_to_world(o['x'], o['y'])
        if o['object_class'] == 'survivor':
            m = [s for s in surv if math.hypot(s['x'] - wx, s['y'] - wy) <= tol and s['id'] not in used]
        else:
            m = [lm for lm in lms if lm['id'] not in used and lm_match(lm, o, wx, wy)]
        if m:
            used.add(m[0]['id'])
            if o['object_class'] == 'survivor':
                hits_sv += 1
            else:
                hits_lm += 1
        elif o['object_class'] != 'survivor' and (
                any(lm_match(lm, o, wx, wy, colour=False) for lm in others + lms) or
                (o['object_class'] == 'marker' and any(math.hypot(k['x'] - wx, k['y'] - wy) <= tol for k in markers))):
            neutral += 1        # a real object (or a duplicate of one already counted): neither a hit nor false
        else:
            false += 1
    recall_lm = hits_lm / max(1, len(lms))
    recall_sv = hits_sv / max(1, len(surv))
    precision = (hits_lm + hits_sv) / max(1, hits_lm + hits_sv + false)
    return dict(score=float((0.5 * recall_lm + 0.5 * recall_sv) * precision),
                landmarks_found=hits_lm, landmarks_total=len(lms), survivors_mapped=hits_sv,
                survivors_total=len(surv), false_objects=false, neutral_objects=neutral)


def localization_error(samples):
    """samples: (t, (wx, wy) gt world, (tx, ty) team pose converted to world). Returns RMSE / max in m."""
    if not samples:
        return dict(rmse=-1.0, max=-1.0, n=0)
    e = np.array([math.hypot(a[0] - b[0], a[1] - b[1]) for _, a, b in samples])
    e = e[np.isfinite(e)]
    if not len(e):
        return dict(rmse=-1.0, max=-1.0, n=0)
    return dict(rmse=float(np.sqrt((e ** 2).mean())), max=float(e.max()), n=int(len(e)))
