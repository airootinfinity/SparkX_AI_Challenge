"""Survivor and decoy selection (organizer ground truth)."""
import math

from . import props
from .gt import street_visibility

SURVIVOR_MODELS = {
    'standing': ['sparkx_survivor_randy', 'sparkx_survivor_male', 'sparkx_survivor_female', 'sparkx_survivor_medic'],
    'lying': ['sparkx_survivor_randy', 'sparkx_survivor_male', 'sparkx_survivor_female', 'sparkx_survivor_medic'],
    'sitting': ['sparkx_survivor_randy_sitting'],
}
POSTURES = {
    'room': (['lying', 'sitting', 'standing'], [0.45, 0.3, 0.25]),
    'rubble': (['lying', 'sitting', 'standing'], [0.55, 0.3, 0.15]),
    'alley': (['lying', 'sitting', 'standing'], [0.4, 0.3, 0.3]),
    'street': (['lying', 'sitting', 'standing'], [0.35, 0.35, 0.3]),
    'yard': (['sitting', 'standing', 'lying'], [0.35, 0.4, 0.25]),
    'open': (['standing', 'sitting', 'lying'], [0.45, 0.35, 0.2]),
}
COUNTS = {'small': 5, 'medium': 7, 'large': 9}
TORSO_Z = {'standing': 1.05, 'sitting': 0.45, 'lying': 0.2}


def _clear_of(x, y, items, dist):
    return all(math.hypot(x - a, y - b) >= dist for a, b in items)


MAX_INDOOR_PATH_M = 12.0   # a person in a room is at most this much driving from an outside entrance


def indoor_path(scene, gt, slot):
    b = next((b for b in scene.buildings if b.id == slot.get('building')), None)
    if b is None:
        return 0.0
    pts = gt.approach_points(slot['x'], slot['y'], 0.6)
    return min((gt.indoor_path(p[0], p[1], b.rect) for p in pts[:4]), default=math.inf)


def select_survivors(scene, ctx, gt, spts, size, difficulty, rng):
    n_target = COUNTS[size] + {'easy': -1, 'normal': 0, 'hard': 1}[difficulty]
    sx, sy = gt.start
    fires = [(f['x'], f['y'], f['hazard_radius']) for f in scene.fires]
    cands = []
    for s in scene.survivor_slots:
        if math.hypot(s['x'] - sx, s['y'] - sy) < 12 or not scene.placer.point_free(s['x'], s['y'], 0.55, True):
            continue
        if any(math.hypot(s['x'] - fx, s['y'] - fy) < r + 2.5 for fx, fy, r in fires):
            continue
        if not gt.approach_points(s['x'], s['y'], 0.6):
            continue
        if s['kind'] == 'room':
            # never deep inside a building: a chain of five doorways to one person is out of
            # proportion for a rover that is a metre long
            s['indoor_path_m'] = indoor_path(scene, gt, s)
            if s['indoor_path_m'] > MAX_INDOOR_PATH_M:
                continue
        cands.append(s)
    rng.shuffle(cands)
    # prefer a mix: rooms first (hidden people), then others
    rooms = [c for c in cands if c['kind'] == 'room']
    others = [c for c in cands if c['kind'] != 'room']
    n_rooms = min(len(rooms), max(2, int(round(n_target * 0.45))))
    order = rooms[:n_rooms] + others + rooms[n_rooms:]
    chosen, used_rooms = [], set()
    for s in order:
        if len(chosen) >= n_target:
            break
        if not _clear_of(s['x'], s['y'], [(c['x'], c['y']) for c in chosen], 7.0):
            continue
        if s.get('room') and s['room'] in used_rooms:
            continue
        chosen.append(s)
        if s.get('room'):
            used_rooms.add(s['room'])
    survivors = []
    for k, s in enumerate(chosen):
        postures, p = POSTURES.get(s['kind'], POSTURES['open'])
        for _try in range(4):
            posture = str(rng.choice(postures, p=p))
            model = str(rng.choice(SURVIVOR_MODELS[posture]))
            yaw = float(s['yaw'] + rng.normal(0, 0.6))
            e = ctx.cat[model]
            pose, row = props.survivor_pose(e, posture, s['x'], s['y'], yaw)
            if scene.placer.box_free(row, 0.15, ignore_reserved=True):
                break
        else:
            continue
        sid = f'S{k + 1:02d}'
        rec = props.survivor(scene, ctx.cat, f'survivor_{sid.lower()}', model, posture, s['x'], s['y'], yaw)
        rec['id'] = sid
        rec['slot'] = {kk: v for kk, v in s.items() if kk not in ('x', 'y', 'yaw')}
        survivors.append(rec)
    return survivors


def finalize_survivors(scene, gt, spts, survivors):
    """Recompute approach points / visibility with bodies in the world; drop unreachable ones."""
    keep = []
    for s in survivors:
        pts = gt.approach_points(s['x'], s['y'], s['z'], own_row=s['row'])
        if not pts:
            continue
        # farthest stand-off points first: a rover parked there is inside the 2 m rescue radius
        # but clear of the body (a person lying down is 1.8 m long)
        pts = sorted(pts, key=lambda q: -q[2])
        s['approach_points'] = [[round(p[0], 2), round(p[1], 2)] for p in pts[:12]]
        s['street_visibility'] = street_visibility(gt, spts, s['x'], s['y'], s['z'], own_row=s['row'])
        s['path_from_start_m'] = round(gt.path_length(gt.start, pts[0][:2]), 1)
        keep.append(s)
    return keep


def select_decoys(scene, ctx, gt, spts, survivors, difficulty, rng):
    n = {'easy': 1, 'normal': 2, 'hard': 3}[difficulty]
    taken = [(s['x'], s['y']) for s in survivors]
    cands = [s for s in scene.survivor_slots if s['kind'] in ('open', 'yard', 'street', 'alley', 'rubble')]
    rng.shuffle(cands)
    decoys = []
    for s in cands:
        if len(decoys) >= n:
            break
        if not _clear_of(s['x'], s['y'], taken, 6.0) or not scene.placer.point_free(s['x'], s['y'], 0.55, True):
            continue
        if street_visibility(gt, spts, s['x'], s['y'], 1.0) == 0:
            continue
        model = str(rng.choice(['sparkx_survivor_male', 'sparkx_survivor_female', 'sparkx_survivor_medic']))
        posture = 'standing' if rng.random() < 0.7 else 'lying'
        pose, row = props.survivor_pose(ctx.cat[model], posture, s['x'], s['y'], s['yaw'])
        if not scene.placer.box_free(row, 0.15, ignore_reserved=True):
            continue
        did = f'D{len(decoys) + 1:02d}'
        rec = props.survivor(scene, ctx.cat, f'mannequin_{did.lower()}', model, posture, s['x'], s['y'], s['yaw'],
                             decoy=True)
        rec['id'] = did
        decoys.append(rec)
        taken.append((s['x'], s['y']))
    return decoys
