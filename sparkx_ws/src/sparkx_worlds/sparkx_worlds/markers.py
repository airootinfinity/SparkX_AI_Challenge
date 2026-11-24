"""Numbered location markers ("tags").

A marker is a four-sided beacon on a post. Each side shows the same ArUco tag (dictionary
DICT_4X4_100) with its number printed underneath, so a camera reads the number from any direction
and people can read it too. One stands at every street junction and one beside every landmark a
clue can name. Clues give a person's position relative to a marker ("about 15 m west of marker
12"), which a robot can act on without having to recognise a blue car or a water tank.

Marker positions are part of the answer sheet (private/scenario.yaml). Teams are told only how many
there are and what they look like: the robot has to find a marker before it can use it.
"""
import math

from .gt import street_visibility

DICTIONARY = 'DICT_4X4_100'
ATLAS = (8, 8)                 # tags per row, rows: ids 0..63 on one texture
CELL = (256, 320)              # pixels per tag on the atlas (tag + printed number)
FIRST_ID, LAST_ID = 1, 63
HEAD_W = 1.10                  # width of one face (m); the tag itself is 0.825 m square
HEAD_H = HEAD_W * CELL[1] / CELL[0]
HEAD_Z0 = 1.55                 # underside of the head: above the rover (0.9 m) and its LiDAR beams' obstacles band
POLE = 0.16
KEEP_CLEAR_M = 4.5             # never this close to a survivor or a decoy: the post must stay out of the robot's approach

COMPASS = ['north', 'north-north-east', 'north-east', 'east-north-east', 'east', 'east-south-east', 'south-east',
           'south-south-east', 'south', 'south-south-west', 'south-west', 'west-south-west', 'west',
           'west-north-west', 'north-west', 'north-north-west']


def atlas_image():
    """The tag atlas as a PIL image (white boards, black tags, the number printed below)."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    d = cv2.aruco.Dictionary_get(getattr(cv2.aruco, DICTIONARY))
    cw, ch = CELL
    img = Image.new('RGB', (ATLAS[0] * cw, ATLAS[1] * ch), (246, 246, 244))
    draw = ImageDraw.Draw(img)
    font = None
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                 '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'):
        try:
            font = ImageFont.truetype(path, 62)
            break
        except OSError:
            continue
    tag_px = 192                                   # 6 modules x 32 px (4x4 bits + the black border)
    for mid in range(ATLAS[0] * ATLAS[1]):
        x0, y0 = (mid % ATLAS[0]) * cw, (mid // ATLAS[0]) * ch
        tag = cv2.aruco.drawMarker(d, mid, tag_px)
        img.paste(Image.fromarray(tag).convert('RGB'), (x0 + (cw - tag_px) // 2, y0 + 26))
        draw.rectangle([x0 + 20, y0 + 232, x0 + cw - 20, y0 + 238], fill=(229, 2, 39))       # Airoot crimson rule
        text = str(mid)
        if font is not None:
            w = draw.textlength(text, font=font)
            draw.text((x0 + (cw - w) / 2, y0 + 242), text, fill=(25, 25, 25), font=font)
        else:
            draw.text((x0 + cw / 2 - 8, y0 + 262), text, fill=(25, 25, 25))
        draw.rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], outline=(25, 25, 25), width=3)
    return img


def cell_uv(mid):
    col, row = mid % ATLAS[0], mid // ATLAS[0]
    return (col / ATLAS[0], 1.0 - (row + 1) / ATLAS[1]), ((col + 1) / ATLAS[0], 1.0 - row / ATLAS[1])


def _beacon(g, x, y, mid):
    """Geometry of one marker: post (with collision), head with four tag faces, caps."""
    g.box((x, y, HEAD_Z0 / 2), (POLE, POLE, HEAD_Z0), 'brand_ink', tag='post')
    cz = HEAD_Z0 + HEAD_H / 2
    m = g.mesh('marker_tags')
    uv = cell_uv(mid)
    for k in range(4):
        yaw = k * math.pi / 2
        m.add_panel((x + HEAD_W / 2 * math.cos(yaw), y + HEAD_W / 2 * math.sin(yaw), cz), HEAD_W, HEAD_H, yaw, uv)
    caps = g.mesh('brand_crimson')
    for z in (HEAD_Z0 - 0.04, HEAD_Z0 + HEAD_H + 0.04):
        caps.add_box((x, y, z), (HEAD_W + 0.08, HEAD_W + 0.08, 0.08))
    g.mesh('brand_ink').add_box((x, y, 0.06), (0.5, 0.5, 0.12))          # foot plate


def _free(scene, gt, x, y, people):
    row = [x, y, HEAD_Z0 / 2, POLE, POLE, HEAD_Z0, 0, 0, 0]
    if not scene.placer.box_free(row, 0.45, ignore_reserved=True):
        return None
    j, i = gt.cell(x, y)
    if not (0 <= j < gt.shape[0] and 0 <= i < gt.shape[1]) or gt.occ[j, i]:
        return None
    if any(math.hypot(x - p['x'], y - p['y']) < KEEP_CLEAR_M for p in people):
        return None
    return row


def place_markers(scene, lay, gt, street_pts, landmarks, people, rng):
    """Put a marker at every street junction and beside every landmark in `landmarks` (the ones a
    clue can name). Returns the marker records; geometry and collisions go into the scene.

    `rng` must be a generator of its own: marker placement may not change anything else in the
    world."""
    g = scene.group('markers')
    spots = []
    # 1) junctions: on the pavement at one corner of the crossing
    inset = lay.S / 2 - 0.8
    for k in range(lay.nx + 1):
        for l in range(lay.ny + 1):
            cx, cy = k * lay.P + lay.S / 2, l * lay.P + lay.S / 2
            corners = [(cx + sx * inset, cy + sy * inset) for sx in (-1, 1) for sy in (-1, 1)]
            for q in rng.permutation(len(corners)):
                x, y = corners[int(q)]
                row = _free(scene, gt, x, y, people)
                if row is not None:
                    scene.placer.mark_box(row)
                    spots.append(dict(x=x, y=y, kind='junction', landmark=''))
                    break
    # 2) landmarks: a couple of metres from the landmark, on its street side
    for lm in landmarks:
        if not street_pts:
            break
        sp = min(street_pts, key=lambda p: math.hypot(p[0] - lm['x'], p[1] - lm['y']))
        base = math.atan2(sp[1] - lm['y'], sp[0] - lm['x'])
        fp = lm.get('footprint')
        reach = 0.5 * math.hypot(fp[3], fp[4]) if fp else 0.3
        best = None
        for r in (reach + 1.0, reach + 1.6, reach + 2.2, reach + 3.0):
            for da in (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5):
                x, y = lm['x'] + r * math.cos(base + da), lm['y'] + r * math.sin(base + da)
                row = _free(scene, gt, x, y, people)
                if row is None or any(math.hypot(x - s['x'], y - s['y']) < 4.0 for s in spots):
                    continue
                if street_visibility(gt, street_pts, x, y, HEAD_Z0 + HEAD_H / 2, max_range=20.0) <= 0:
                    continue
                best = (x, y, row)
                break
            if best:
                break
        if best:
            scene.placer.mark_box(best[2])
            spots.append(dict(x=best[0], y=best[1], kind='landmark', landmark=lm['id']))
    ids = [int(v) for v in rng.permutation(range(FIRST_ID, LAST_ID + 1))[:len(spots)]]
    out = []
    for s, mid in zip(spots, ids):          # more spots than ids cannot happen on the published map sizes
        _beacon(g, s['x'], s['y'], mid)
        out.append(dict(id=mid, x=round(s['x'], 3), y=round(s['y'], 3), z=round(HEAD_Z0 + HEAD_H / 2, 3),
                        kind=s['kind'], landmark=s['landmark']))
    return out


def marker_reference(markers, x, y, min_d=3.0, max_d=40.0):
    """The marker a clue about the point (x, y) is measured from: the nearest one that is not right
    on top of the person. Returns dict(id, bearing_deg, distance_m, text) or None.

    bearing_deg is a compass bearing from the marker to the person (0 = north = +Y, 90 = east),
    rounded to 5 degrees; distance_m is rounded to whole metres. The rounding moves the stated
    point by at most about 2 m at 40 m."""
    best = None
    for m in markers:
        d = math.hypot(x - m['x'], y - m['y'])
        if min_d <= d <= max_d and (best is None or d < best[0]):
            best = (d, m)
    if best is None:
        return None
    d, m = best
    brg = math.degrees(math.atan2(x - m['x'], y - m['y'])) % 360.0
    brg5 = (round(brg / 5.0) * 5.0) % 360.0
    dist = float(round(d))
    word = COMPASS[int(round(brg / 22.5)) % 16]
    return dict(id=int(m['id']), bearing_deg=brg5, distance_m=dist, text=f'about {int(dist)} m {word} of marker {m["id"]}')


def stated_point(markers, ref):
    """Where a marker reference says the person is (used by the self-tests)."""
    m = next(k for k in markers if k['id'] == ref['id'])
    a = math.radians(ref['bearing_deg'])
    return m['x'] + ref['distance_m'] * math.sin(a), m['y'] + ref['distance_m'] * math.cos(a)
