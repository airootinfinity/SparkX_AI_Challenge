"""Hint generation: every hint references a unique, street-visible landmark and a spatial relation
that actually holds for the target survivor. Hints never contain coordinates."""
import math

import numpy as np

from .gt import street_visibility
from .markers import marker_reference

DISPLAY = {'water_tank': 'water tank', 'fire_truck': 'fire truck', 'container': 'shipping container',
           'tent': 'relief tent', 'dumpster': 'dumpster', 'bus': 'bus', 'ambulance': 'ambulance', 'car': 'car',
           'fountain': 'fountain', 'crater': 'blast crater', 'sign': 'sign'}
CARD_TEXT = {'north_of': 'north', 'south_of': 'south', 'east_of': 'east', 'west_of': 'west'}
WEIGHT = {'inside': 0.75, 'beside': 0.9, 'behind': 0.75, 'opposite': 0.75, 'near': 0.6, 'north_of': 0.55,
          'south_of': 0.55, 'east_of': 0.55, 'west_of': 0.55}


def signature(lm):
    return (lm['cls'], lm.get('color', '') if lm['cls'] not in ('sign', 'fountain', 'crater') else '',
            lm.get('label', ''))


def landmark_name(lm):
    if lm['cls'] == 'sign':
        return f'{lm["label"]} sign'
    col = lm.get('color', '')
    return f'{col} {DISPLAY[lm["cls"]]}'.strip() if lm['cls'] not in ('fountain', 'crater') else DISPLAY[lm['cls']]


def _box_dist(lm, x, y):
    fp = lm.get('footprint')
    if not fp:
        return math.hypot(x - lm['x'], y - lm['y'])
    c, s = math.cos(-fp[8]), math.sin(-fp[8])
    dx, dy = x - fp[0], y - fp[1]
    lx, ly = dx * c - dy * s, dx * s + dy * c
    ex, ey = max(abs(lx) - fp[3] / 2, 0), max(abs(ly) - fp[4] / 2, 0)
    return math.hypot(ex, ey)


def relations(scene, lm, t, street_pts):
    """Valid (relation, distance) pairs between landmark lm and target survivor t."""
    x, y = t['x'], t['y']
    d = math.hypot(x - lm['x'], y - lm['y'])
    out = []
    if lm['cls'] == 'sign' and t['slot'].get('building') == lm.get('building'):
        out.append(('inside', d))
    if lm['cls'] == 'sign':
        return out
    bd = _box_dist(lm, x, y)
    if bd <= 4.0:
        out.append(('beside', d))
    if d <= 9.0:
        out.append(('near', d))
    # behind: on the far side of the landmark from its nearest street point
    if street_pts and d <= 8.0:
        sp = min(street_pts, key=lambda p: math.hypot(p[0] - lm['x'], p[1] - lm['y']))
        vs = np.array([sp[0] - lm['x'], sp[1] - lm['y']])
        vt = np.array([x - lm['x'], y - lm['y']])
        if np.linalg.norm(vs) > 1.0 and np.dot(vs, vt) / (np.linalg.norm(vs) * np.linalg.norm(vt) + 1e-9) < -0.5:
            out.append(('behind', d))
    # opposite: a street centre line separates the landmark and the target
    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        if seg['axis'] == 'x':
            cy = (y0 + y1) / 2
            if x0 - 2 <= x <= x1 + 2 and x0 - 2 <= lm['x'] <= x1 + 2 and (lm['y'] - cy) * (y - cy) < 0 \
                    and abs(lm['y'] - cy) < 11 and abs(y - cy) < 11 and abs(x - lm['x']) < 8:
                out.append(('opposite', d))
                break
        else:
            cx = (x0 + x1) / 2
            if y0 - 2 <= y <= y1 + 2 and y0 - 2 <= lm['y'] <= y1 + 2 and (lm['x'] - cx) * (x - cx) < 0 \
                    and abs(lm['x'] - cx) < 11 and abs(x - cx) < 11 and abs(y - lm['y']) < 8:
                out.append(('opposite', d))
                break
    if 5.0 <= d <= 16.0:
        a = math.degrees(math.atan2(y - lm['y'], x - lm['x']))
        for rel, ang in (('east_of', 0), ('north_of', 90), ('west_of', 180), ('south_of', -90)):
            if abs((a - ang + 180) % 360 - 180) <= 30:
                out.append((rel, d))
    return out


def hint_text(rel, lm, area, dist, count=1):
    who = 'Someone is' if count == 1 else f'{count} people are'
    name = landmark_name(lm)
    if rel == 'inside':
        return f'{who} trapped inside the building with the {name}.'
    if rel == 'beside':
        where = 'in the room ' if area == 'room' else ''
        return f'{who} {where}beside the {name}.'
    if rel == 'near':
        return f'{who} near the {name}, roughly {int(round(dist))} m from it.'
    if rel == 'behind':
        return f'{who} behind the {name}.'
    if rel == 'opposite':
        return f'{who} across the street from the {name}.'
    return f'{who} about {int(round(dist))} m {CARD_TEXT[rel]} of the {name}.'


def usable_landmarks(scene, gt, street_pts):
    counts = {}
    for lm in scene.landmarks:
        counts[signature(lm)] = counts.get(signature(lm), 0) + 1
    out = []
    for lm in scene.landmarks:
        if counts[signature(lm)] != 1:
            continue
        z = lm['z'] if lm['cls'] == 'sign' else max(0.8, 0.5 * lm['size'][2])
        vis = street_visibility(gt, street_pts, lm['x'], lm['y'], z, own_row=lm.get('footprint'), max_range=25.0)
        if lm['cls'] == 'sign' or lm.get('footprint') is None:
            # signs are on facades: test from a point just in front of the plate
            fx, fy = lm['x'] + 0.3 * math.cos(lm['yaw']), lm['y'] + 0.3 * math.sin(lm['yaw'])
            vis = street_visibility(gt, street_pts, fx, fy, z, max_range=25.0)
        lm['street_visibility'] = vis
        if vis > 0:
            out.append(lm)
    return out


def best_hint(scene, t, lms, street_pts, rng):
    cands = []
    for lm in lms:
        for rel, d in relations(scene, lm, t, street_pts):
            score = WEIGHT[rel] * (1.0 + 0.02 * min(lm['street_visibility'], 20)) * rng.uniform(0.8, 1.2)
            cands.append((score, rel, d, lm))
    if not cands:
        return None
    score, rel, d, lm = max(cands, key=lambda c: c[0])
    area = {'room': 'room', 'rubble': 'rubble', 'street': 'street', 'alley': 'street'}.get(t['slot']['kind'],
                                                                                          'open_area')
    if rel == 'inside':
        area = 'building'
    return dict(relation=rel, landmark=dict(cls=lm['cls'], color=signature(lm)[1], label=lm.get('label', ''),
                                            id=lm['id']),
                area_type=area, approx_distance_m=float(round(d)) if rel not in ('inside', 'beside') else 0.0,
                people_count=1, text=hint_text(rel, lm, area, d))


def _area(t):
    return {'room': 'room', 'rubble': 'rubble', 'street': 'street', 'alley': 'street'}.get(t['slot']['kind'], 'open_area')


def with_marker(h, ref, t):
    """Combine the landmark clue h (may be None) with the marker reference ref (may be None)."""
    if ref is None:
        if h is not None:
            h['marker'] = None
        return h
    if h is None:
        rel = ('north_of', 'east_of', 'south_of', 'west_of')[int(round(ref['bearing_deg'] / 90.0)) % 4]
        h = dict(relation=rel, landmark=dict(cls='marker', color='', label=str(ref['id']), id=f'mk_{ref["id"]}'),
                 area_type=_area(t), approx_distance_m=ref['distance_m'], people_count=1,
                 text=f'Someone is {ref["text"]}.')
    else:
        h = dict(h)
        h['text'] = h['text'].rstrip('.') + f', {ref["text"]}.'
    h['marker'] = dict(id=ref['id'], bearing_deg=ref['bearing_deg'], distance_m=ref['distance_m'])
    return h


def build_hints(scene, gt, street_pts, survivors, rng, markers=(), lms=None):
    """Chain hints: rescuing a source survivor releases a hint about a (preferably hidden) target.
    With markers in the world every survivor can be the subject of a clue, so the people who cannot
    be seen from a street are always among the targets."""
    if lms is None:
        lms = usable_landmarks(scene, gt, street_pts)
    hintable = {}
    for s in survivors:
        h = with_marker(best_hint(scene, s, lms, street_pts, rng), marker_reference(markers, s['x'], s['y']), s)
        if h:
            hintable[s['id']] = h
    hidden = sorted([s for s in survivors if s['id'] in hintable],
                    key=lambda s: (s['street_visibility'], -s['path_from_start_m']))
    n_targets = max(1, min(len(hidden), int(math.ceil(len(survivors) * 0.5))))
    targets = hidden[:n_targets]
    sources = [s for s in survivors if s not in targets]
    hints, used_src = [], set()
    sx, sy = gt.start
    # 1) guaranteed clue-driven return: target nearest to the base <- source far away from it
    if targets and sources:
        t0 = min(targets, key=lambda s: math.hypot(s['x'] - sx, s['y'] - sy))
        s0 = max(sources, key=lambda s: math.hypot(s['x'] - t0['x'], s['y'] - t0['y']))
        hints.append((s0, t0))
        used_src.add(s0['id'])
        remaining = [t for t in targets if t is not t0]
    else:
        remaining = list(targets)
    # 2) other targets: from unused sources or previous targets (chains)
    pool = [s for s in sources if s['id'] not in used_src] + [t for _, t in hints]
    for t in remaining:
        options = [s for s in pool if s['id'] not in used_src and s is not t]
        if not options:
            options = [s for s in survivors if s['id'] not in used_src and s is not t]
        if not options:
            break
        far = [s for s in options if math.hypot(s['x'] - t['x'], s['y'] - t['y']) > 15]
        src = (far or options)[int(rng.integers(0, len(far or options)))]
        hints.append((src, t))
        used_src.add(src['id'])
        pool.append(t)
    out = []
    for k, (src, t) in enumerate(hints):
        h = dict(hintable[t['id']])
        h.update(id=f'H{k + 1:02d}', source=src['id'], target=t['id'])
        out.append(h)
        src.setdefault('releases', []).append(h['id'])
    return out, lms


def aftershock_candidates(scene, gt, survivors, lay, max_n=12):
    """Street segments that can be blocked mid-mission while the base still reaches every survivor
    on a route that keeps clear of every fire.
    Checked on the full-resolution ground-truth grid: the barrier (grown by the robot radius) is
    added to the inflated obstacle map and reachability is flood-filled again."""
    from .geometry import flood_fill, rasterize_boxes
    from .gt import ROBOT_RADIUS
    base_rect = lay.block_rect(0, 0)
    out = []
    for seg in scene.street_segments:
        if seg['blocked']:
            continue
        x0, y0, x1, y1 = seg['rect']
        if x0 < base_rect[2] + 2 and y0 < base_rect[3] + 2:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        yaw = math.pi / 2 if seg['axis'] == 'x' else 0.0
        core = [cx, cy, 0.5, lay.S + 0.6, 2.2, 1.0, 0, 0, yaw]
        grown = [cx, cy, 0.5, core[3] + 2 * ROBOT_RADIUS, core[4] + 2 * ROBOT_RADIUS, 1.0, 0, 0, yaw]
        wall = rasterize_boxes([grown], gt.origin, gt.res, gt.shape, -1e9, 1e9)
        reach = flood_fill((gt.inflated == 0) & (wall == 0) & ~gt.fire_zone, gt.cell(*gt.start))

        def reachable(px, py):
            j, i = gt.cell(px, py)
            return 0 <= j < gt.shape[0] and 0 <= i < gt.shape[1] and bool(reach[j, i])
        if all(any(reachable(px, py) for px, py in s['approach_points']) for s in survivors):
            out.append(dict(segment=seg['id'], x=cx, y=cy, yaw=yaw, width=lay.S + 0.6, depth=2.2, core=core))
        if len(out) >= max_n:
            break
    return out
