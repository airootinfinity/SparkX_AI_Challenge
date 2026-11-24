"""Heat sources: things at body temperature that are not people.

A burning district is full of them: a drum that stood next to a fire, a beam still smouldering, a
steel locker heated through. In the thermal camera each is a blob at 304-313 K with the size of a
person sitting, lying or standing, so a detector that reports every warm blob of the right size
reports them. They exist in worlds with `smoky` lighting, where the fires are, and are what makes
thermal imaging alone insufficient there: a robot has to look at what the warm thing is (its
shape in the thermal image, in the depth image or LiDAR, its appearance in the colour image)
before it drives up to it and files a report. Mannequin decoys are the opposite trap: the shape
of a person, and cold.

Positions are part of the answer sheet (private/scenario.yaml, `heat_sources`). Reporting one is
an ordinary rejected report (no survivor in range).
"""
import math

import numpy as np
from scipy import ndimage

from .sdfgen import fmt, thermal_plugin

COUNTS = {'small': 6, 'medium': 10, 'large': 14}
BODY_BAND_K = (304.0, 313.0)       # people are 303-312 K
KEEP_FROM_PEOPLE_M = 6.0           # survivors and decoys: never in the robot's approach, never mistaken for the person next to it
KEEP_FROM_FIRE_M = 4.5             # outside every fire's hazard zone, so looking at one is safe
KEEP_APART_M = 7.0
KEEP_FROM_START_M = 9.0
CLEAR_M = 2.3                      # free ground all round: a street stays passable on both sides

# kind -> (size x, y, z of the box, colour); each is as tall and wide as a person in one posture
KINDS = {
    'drum': ((0.58, 0.58, 0.88), (0.20, 0.13, 0.10)),      # sitting
    'beam': ((1.75, 0.42, 0.36), (0.13, 0.10, 0.09)),      # lying
    'locker': ((0.50, 0.38, 1.72), (0.22, 0.20, 0.19)),    # standing
}


def _model(uid, kind, x, y, yaw, temp):
    (sx, sy, sz), col = KINDS[kind]
    if kind == 'drum':
        geom = f'<cylinder><radius>{sx / 2:.2f}</radius><length>{sz:.2f}</length></cylinder>'
    else:
        geom = f'<box><size>{sx:.2f} {sy:.2f} {sz:.2f}</size></box>'
    mat = (f'<material><ambient>{fmt(col)} 1</ambient><diffuse>{fmt(col)} 1</diffuse><specular>0.05 0.05 0.05 1</specular>'
           f'<emissive>0.10 0.03 0.0 1</emissive></material>')
    return (f'<model name="{uid}"><static>true</static><pose>{x:.3f} {y:.3f} 0 0 0 {yaw:.3f}</pose><link name="link">'
            f'<collision name="c"><pose>0 0 {sz / 2:.3f} 0 0 0</pose><geometry><box><size>{sx:.2f} {sy:.2f} {sz:.2f}</size></box>'
            f'</geometry></collision>'
            f'<visual name="v"><pose>0 0 {sz / 2:.3f} 0 0 0</pose><geometry>{geom}</geometry>{mat}{thermal_plugin(temp)}</visual>'
            f'</link></model>')


def place_heat_sources(scene, gt, street_pts, people, size, rng):
    """Stand heat sources on open street ground. Returns their records; models and collisions go
    into the scene. `rng` must be a generator of its own: this may not change anything else."""
    clear = ndimage.distance_transform_edt(~(gt.occ > 0)) * gt.res
    fires = [(f['x'], f['y']) for f in scene.fires]
    out = []
    kinds = list(KINDS)
    for attempt in range(600):
        if len(out) >= COUNTS[size] or not street_pts:
            break
        sx, sy = street_pts[int(rng.integers(len(street_pts)))]
        x, y = float(sx) + float(rng.uniform(-3.5, 3.5)), float(sy) + float(rng.uniform(-3.5, 3.5))
        kind = kinds[len(out) % len(kinds)]
        dims = KINDS[kind][0]
        yaw = float(rng.uniform(-math.pi, math.pi))
        j, i = gt.cell(x, y)
        if not (0 <= j < gt.shape[0] and 0 <= i < gt.shape[1]) or clear[j, i] < CLEAR_M or not gt.reachable(x, y):
            continue
        if any(math.hypot(x - p['x'], y - p['y']) < KEEP_FROM_PEOPLE_M for p in people) or \
                any(math.hypot(x - fx, y - fy) < KEEP_FROM_FIRE_M for fx, fy in fires) or \
                any(math.hypot(x - h['x'], y - h['y']) < KEEP_APART_M for h in out) or \
                math.hypot(x - gt.start[0], y - gt.start[1]) < KEEP_FROM_START_M:
            continue
        row = [x, y, dims[2] / 2, dims[0], dims[1], dims[2], 0, 0, yaw]
        if not scene.placer.box_free(row, 0.6, ignore_reserved=True):
            continue
        uid = f'heat_{len(out)}'
        temp = float(rng.uniform(*BODY_BAND_K))
        scene.models.append(_model(uid, kind, x, y, yaw, temp))
        scene.placer.mark_box(row)
        scene.extra_boxes.append((row, 'heat'))
        out.append(dict(id=uid, kind=kind, x=round(x, 3), y=round(y, 3), yaw=round(yaw, 3), temperature=round(temp, 1),
                        size=[round(float(v), 2) for v in dims]))
    return out
