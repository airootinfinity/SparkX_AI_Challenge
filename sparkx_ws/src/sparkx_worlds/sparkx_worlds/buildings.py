"""Procedural enterable, damaged buildings: BSP rooms, doorways, windows, wall breaches,
roof holes, collapsed rooms, fallen slabs, furniture and shop signs.

Doorway sizes are chosen for the SparkX UGV (0.67 m wide): interior doors 1.7 m, entrances 2.4 m.
"""
import math

import numpy as np

from . import kit

EXT_T = 0.30
INT_T = 0.15
DOOR_W = 1.7
ENTRANCE_W = 2.4
DOOR_H = 2.3
WIN_W, WIN_Z0, WIN_Z1 = 1.3, 1.0, 2.1


class Building:
    def __init__(self, bid, rect, height):
        self.id = bid
        self.rect = rect            # x0, y0, x1, y1 (outer faces)
        self.height = height
        self.rooms = []             # dicts: id, rect, collapsed, roof
        self.doors = []             # (x, y) centres of interior doorways
        self.entrances = []         # dicts: x, y, nx, ny (outward normal), width, kind
        self.signs = []             # dicts: label, x, y, z, yaw (facing outward)
        self.facade = None
        self.upper = {}             # side -> [(from, to, height)] of the ruined upper storey

    def contains(self, x, y, margin=0.0):
        x0, y0, x1, y1 = self.rect
        return x0 + margin <= x <= x1 - margin and y0 + margin <= y <= y1 - margin

    def room_at(self, x, y):
        for r in self.rooms:
            x0, y0, x1, y1 = r['rect']
            if x0 <= x <= x1 and y0 <= y <= y1:
                return r
        return None


def emit_wall(group, axis, fixed, a, b, t, h, openings, mat_out, mat_in=None, out_sign=1, tag='wall',
              z_base=0.0, collide=True):
    """Axis-aligned wall. axis='x': runs along x from a to b at y=fixed (normal = y).
    openings: (centre, width, z0, z1) measured along the wall / from z_base.
    Collision is one box per solid piece; visuals are split in outer/inner halves so the
    facade material only appears outside (out_sign = side of the outside along the normal)."""
    pieces = []
    cur = a
    for c, w, z0, z1 in sorted(openings):
        s, e = max(c - w / 2, a), min(c + w / 2, b)
        if e <= s:
            continue
        if s > cur + 0.02:
            pieces.append((cur, s, 0.0, h))
        if z0 > 0.02:
            pieces.append((s, e, 0.0, z0))
        if z1 < h - 0.02:
            pieces.append((s, e, z1, h))
        cur = max(cur, e)
    if b > cur + 0.02:
        pieces.append((cur, b, 0.0, h))
    for s, e, z0, z1 in pieces:
        L, cm, zc, hz = e - s, (s + e) / 2, z_base + (z0 + z1) / 2, z1 - z0
        if axis == 'x':
            center, size = (cm, fixed, zc), (L, t, hz)
        else:
            center, size = (fixed, cm, zc), (t, L, hz)
        if collide:
            group.box(center, size, None, tag=tag)
        if mat_in is None or mat_in == mat_out:
            group.box(center, size, mat_out, collide=False)
            continue
        # outer / inner visual halves
        for sgn, mat in ((out_sign, mat_out), (-out_sign, mat_in)):
            off = sgn * t / 4
            if axis == 'x':
                c2, s2 = (cm, fixed + off, zc), (L, t / 2, hz)
            else:
                c2, s2 = (fixed + off, cm, zc), (t / 2, L, hz)
            group.box(c2, s2, mat, collide=False)
    return pieces


def _bsp(rng, rect, min_room=4.8, max_room=9.5):
    leaves, walls = [], []

    def rec(r, depth):
        x0, y0, x1, y1 = r
        w, h = x1 - x0, y1 - y0
        can_x, can_y = w >= 2 * min_room, h >= 2 * min_room
        big = max(w, h) > max_room
        if not (can_x or can_y) or (not big and rng.random() < 0.3 + 0.12 * depth):
            leaves.append(r)
            return
        if can_x and (not can_y or w >= h * rng.uniform(0.8, 1.25)):
            xs = float(rng.uniform(x0 + min_room, x1 - min_room))
            walls.append(('y', xs, y0, y1))
            rec((x0, y0, xs, y1), depth + 1)
            rec((xs, y0, x1, y1), depth + 1)
        else:
            ys = float(rng.uniform(y0 + min_room, y1 - min_room))
            walls.append(('x', ys, x0, x1))
            rec((x0, y0, x1, ys), depth + 1)
            rec((x0, ys, x1, y1), depth + 1)

    rec(rect, 0)
    return leaves, walls


def _junctions(wall, walls, tol=1e-6):
    """Positions along `wall` where walls of `walls` meet it. An exterior wall is given by its centre
    line, half a wall thickness outside the inner rectangle where interior walls end: pass
    tol >= EXT_T / 2 for it (with 1e-6 no interior wall ever met an exterior one, and entrances were
    placed across the end of an interior wall, leaving the rover a 1.1 m gap of a 2.4 m door)."""
    axis, fixed, a, b = wall
    js = []
    for ax2, f2, a2, b2 in walls:
        if ax2 == axis:
            continue
        if a - 1e-6 <= f2 <= b + 1e-6 and (abs(a2 - fixed) < tol or abs(b2 - fixed) < tol):
            js.append(f2)
    return js


def _pick_opening(rng, a, b, width, avoid, clearance=0.45, end_margin=0.8):
    lo, hi = a + end_margin + width / 2, b - end_margin - width / 2
    if hi < lo:
        return None
    for _ in range(40):
        c = float(rng.uniform(lo, hi))
        if all(abs(c - j) > width / 2 + clearance for j in avoid):
            return c
    return None


def make_building(rng, group, placer, bid, rect, street_sides, damage, facade, interior='plaster_int',
                  height=3.4, storeys=1, sign_label=None):
    """Create one building inside rect (outer faces). street_sides: subset of 'NSEW'.
    Returns a Building. Collisions are added to `group` and marked in `placer`."""
    x0, y0, x1, y1 = rect
    b = Building(bid, rect, height)
    b.facade = facade
    t = EXT_T
    inner = (x0 + t, y0 + t, x1 - t, y1 - t)
    leaves, iwalls = _bsp(rng, inner)
    n_col0 = len(group.collisions)

    # --- exterior walls: (side, axis, fixed, a, b, out_sign)
    ext = {
        'S': ('x', y0 + t / 2, x0, x1, -1), 'N': ('x', y1 - t / 2, x0, x1, 1),
        'W': ('y', x0 + t / 2, y0 + t, y1 - t, -1), 'E': ('y', x1 - t / 2, y0 + t, y1 - t, 1),
    }
    openings = {s: [] for s in ext}
    # entrances on street sides (at least one)
    sides = [s for s in 'NSEW' if s in street_sides] or ['S']
    n_ent = 1 if rng.random() < 0.55 or len(sides) == 1 else 2
    rng.shuffle(sides)
    fallback = [s for s in 'NSEW' if s not in sides]
    for side in sides[:n_ent] + fallback:
        if side in fallback and any(e['kind'] == 'door' for e in b.entrances):
            break
        axis, fixed, a, bb, sgn = ext[side]
        avoid = _junctions((axis, fixed, a, bb), iwalls, tol=t) + [a + t, bb - t]
        c = _pick_opening(rng, a, bb, ENTRANCE_W, avoid)
        if c is None:
            continue
        openings[side].append((c, ENTRANCE_W, 0.0, DOOR_H))
        ex, ey = (c, fixed) if axis == 'x' else (fixed, c)
        nx, ny = (0, sgn) if axis == 'x' else (sgn, 0)
        b.entrances.append(dict(x=ex, y=ey, nx=nx, ny=ny, width=ENTRANCE_W, kind='door', side=side))
    # breach (collapsed wall section) grows with damage
    if rng.random() < 0.2 + 0.6 * damage:
        side = str(rng.choice(list('NSEW')))
        axis, fixed, a, bb, sgn = ext[side]
        w = float(rng.uniform(2.6, 4.0))
        avoid = _junctions((axis, fixed, a, bb), iwalls, tol=t) + [o[0] for o in openings[side]]
        c = _pick_opening(rng, a, bb, w, avoid, clearance=0.6)
        if c is not None:
            openings[side].append((c, w, 0.0, height * storeys))
            ex, ey = (c, fixed) if axis == 'x' else (fixed, c)
            nx, ny = (0, sgn) if axis == 'x' else (sgn, 0)
            b.entrances.append(dict(x=ex, y=ey, nx=nx, ny=ny, width=w, kind='breach', side=side))
    # windows
    for side, (axis, fixed, a, bb, sgn) in ext.items():
        avoid = _junctions((axis, fixed, a, bb), iwalls, tol=t) + [o[0] for o in openings[side]]
        widths = {o[0]: o[1] for o in openings[side]}
        pos = a + 1.8
        while pos < bb - 1.8:
            ok = all(abs(pos - j) > WIN_W / 2 + 0.35 for j in avoid if j not in widths)
            ok = ok and all(abs(pos - c) > (w + WIN_W) / 2 + 0.4 for c, w in widths.items())
            if ok and rng.random() < 0.65:
                openings[side].append((pos, WIN_W, WIN_Z0, WIN_Z1))
            pos += float(rng.uniform(2.6, 3.4))
    for side, (axis, fixed, a, bb, sgn) in ext.items():
        emit_wall(group, axis, fixed, a, bb, t, height, openings[side], facade, interior, sgn, tag=f'b{bid}_ext')
        if storeys > 1:
            # upper storey (visual only): shelled. Each stretch of wall stands to its own height,
            # from a knee-high stump to the full storey; windows survive only in the tall parts.
            ups = [(o[0], WIN_W, WIN_Z0, WIN_Z1) for o in openings[side] if o[1] <= WIN_W + 0.01]
            full = [(o[0], o[1]) for o in openings[side] if o[3] >= height * storeys - 0.01]
            b.upper[side] = []
            pos = a
            phase = float(rng.uniform(0, 6.28))
            while pos < bb - 0.05:
                w = min(float(rng.uniform(1.6, 3.4)), bb - pos)
                if bb - pos - w < 1.0:
                    w = bb - pos
                s, e = pos, pos + w
                pos = e
                if any(s < c + cw / 2 and e > c - cw / 2 for c, cw in full):
                    continue                                       # the breach below goes all the way up
                keep = 0.62 + 0.42 * math.sin(phase + (s + e) * 0.21) + float(rng.normal(0, 0.22)) - 0.55 * damage
                hi = float(np.clip(keep, 0.08, 1.0)) * height
                hi = height if hi > height - 0.45 else hi
                ops_u = [o for o in ups if s + 0.25 < o[0] - o[1] / 2 and o[0] + o[1] / 2 < e - 0.25] if hi > WIN_Z1 + 0.25 else []
                emit_wall(group, axis, fixed, s, e, t, hi, ops_u, facade, interior, sgn, z_base=height, collide=False)
                b.upper[side].append((s, e, hi))

    # --- interior walls with doorways (+ damage holes)
    int_doors = []
    for w in iwalls:
        axis, fixed, a, bb = w
        avoid = _junctions(w, iwalls)
        ops = []
        c = None
        for width in (DOOR_W, 1.5):
            c = _pick_opening(rng, a, bb, width, avoid, end_margin=0.5)
            if c is not None:
                ops.append((c, width, 0.0, DOOR_H))
                b.doors.append((c, fixed) if axis == 'x' else (fixed, c))
                int_doors.append((axis, fixed, c, width))
                break
        if rng.random() < 0.5 * damage:
            hw = float(rng.uniform(1.4, 2.6))
            c2 = _pick_opening(rng, a, bb, hw, avoid + ([c] if c is not None else []), clearance=0.8, end_margin=0.4)
            if c2 is not None:
                ops.append((c2, hw, 0.0, height))
                b.doors.append((c2, fixed) if axis == 'x' else (fixed, c2))
        emit_wall(group, axis, fixed, a, bb, INT_T, height, ops, interior, tag=f'b{bid}_int')

    # mark walls in the placer, reserve doorways / entrances
    for row in group.collisions[n_col0:]:
        placer.mark_box(row)
    for dx, dy in b.doors:
        placer.reserve_rect(dx - 1.2, dy - 1.2, dx + 1.2, dy + 1.2)
    for e in b.entrances:
        cx, cy = e['x'] + e['nx'] * 0.2, e['y'] + e['ny'] * 0.2
        r = e['width'] / 2 + 0.4
        placer.reserve_rect(cx - r - abs(e['nx']) * 1.6, cy - r - abs(e['ny']) * 1.6,
                            cx + r + abs(e['nx']) * 1.6, cy + r + abs(e['ny']) * 1.6)

    # --- floor, ceilings (roof holes), rooms
    group.mesh('floor_tiles').add_rect_xy(inner[0], inner[1], inner[2], inner[3], z=0.012, tile=3.0)
    for i, (rx0, ry0, rx1, ry1) in enumerate(leaves):
        roof = rng.random() > 0.15 + 0.55 * damage
        if roof:
            group.box(((rx0 + rx1) / 2, (ry0 + ry1) / 2, height + 0.1), (rx1 - rx0 + 0.3, ry1 - ry0 + 0.3, 0.2),
                      'concrete_dark', collide=False, tile=3.0)
        b.rooms.append(dict(id=f'b{bid}_r{i}', rect=(rx0, ry0, rx1, ry1), collapsed=False, roof=roof))
    if storeys > 1:
        # what is left of the upper floor: slabs hanging over some rooms, the rest fell in
        for (rx0, ry0, rx1, ry1) in leaves:
            if rng.random() < 0.45 * (1.0 - 0.6 * damage):
                group.box(((rx0 + rx1) / 2, (ry0 + ry1) / 2, 2 * height + 0.1), (rx1 - rx0 + 0.3, ry1 - ry0 + 0.3, 0.2),
                          'concrete_dark', collide=False, tile=3.0)

    # --- collapsed rooms / fallen slabs / furniture
    def rooms_at(x, y, pad=0.4):
        return [k for k, r in enumerate(b.rooms)
                if r['rect'][0] - pad <= x <= r['rect'][2] + pad and r['rect'][1] - pad <= y <= r['rect'][3] + pad]

    adj = {k: set() for k in range(len(b.rooms))}
    for dx, dy in b.doors:
        ks = rooms_at(dx, dy)
        for k1 in ks:
            adj[k1].update(k2 for k2 in ks if k2 != k1)
    entry_rooms = {k for e in b.entrances for k in rooms_at(e['x'], e['y'], EXT_T + 0.2)}

    def all_connected(collapsed):
        start = [k for k in entry_rooms if k not in collapsed]
        seen, stack = set(start), list(start)
        while stack:
            for n in adj[stack.pop()]:
                if n not in seen and n not in collapsed:
                    seen.add(n)
                    stack.append(n)
        return len(seen) == len(b.rooms) - len(collapsed)

    collapsed = set()
    for k in range(len(b.rooms)):
        if len(b.rooms) > 2 and k not in entry_rooms and rng.random() < 0.3 * damage:
            if all_connected(collapsed | {k}):
                collapsed.add(k)

    for k, room in enumerate(b.rooms):
        rx0, ry0, rx1, ry1 = room['rect']
        cx, cy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
        if k in collapsed:
            room['collapsed'] = True
            ang = float(rng.uniform(0.35, 0.6))
            sx, sy = rx1 - rx0 - 0.4, ry1 - ry0 - 0.4
            yaw = 0.0 if sx > sy else math.pi / 2
            L, W = (sx, sy) if yaw == 0.0 else (sy, sx)
            row = [cx, cy, 0.5 * L * math.sin(ang) + 0.1, L, W, 0.25, 0.0, ang, yaw]
            group.box(row[:3], row[3:6], 'concrete', rpy=row[6:9], tag='slab')
            placer.mark_box(row)
            continue
        if rng.random() < 0.4 * damage:  # fallen ceiling slab leaning on a wall
            sl, sw = float(rng.uniform(2.0, 3.2)), float(rng.uniform(1.2, 2.0))
            px = float(rng.uniform(rx0 + sl / 2 + 0.3, max(rx0 + sl / 2 + 0.31, rx1 - sl / 2 - 0.3)))
            py = float(rng.uniform(ry0 + sw / 2 + 0.3, max(ry0 + sw / 2 + 0.31, ry1 - sw / 2 - 0.3)))
            ang = float(rng.uniform(0.3, 0.7))
            row = [px, py, 0.5 * sl * math.sin(ang) + 0.05, sl, sw, 0.2, 0.0, ang, float(rng.choice([0, math.pi / 2]))]
            if placer.box_free(row, 0.1):
                group.box(row[:3], row[3:6], 'concrete', rpy=row[6:9], tag='slab')
                placer.mark_box(row)
        for _ in range(int(rng.integers(1, 4))):
            kind = rng.choice(['table', 'shelf', 'cabinet', 'crate'])
            sz = {'table': (1.4, 0.8, 0.75), 'shelf': (1.6, 0.45, 1.8), 'cabinet': (0.7, 0.6, 1.2),
                  'crate': (0.9, 0.9, 0.8)}[kind]
            for _try in range(8):
                yaw = float(rng.choice([0, math.pi / 2]))
                ex = sz[0] if yaw == 0 else sz[1]
                ey = sz[1] if yaw == 0 else sz[0]
                # hug a wall
                if rng.random() < 0.5:
                    px = float(rng.uniform(rx0 + ex / 2 + 0.1, max(rx0 + ex / 2 + 0.11, rx1 - ex / 2 - 0.1)))
                    py = ry0 + ey / 2 + 0.1 if rng.random() < 0.5 else ry1 - ey / 2 - 0.1
                else:
                    py = float(rng.uniform(ry0 + ey / 2 + 0.1, max(ry0 + ey / 2 + 0.11, ry1 - ey / 2 - 0.1)))
                    px = rx0 + ex / 2 + 0.1 if rng.random() < 0.5 else rx1 - ex / 2 - 0.1
                row = [px, py, sz[2] / 2, sz[0], sz[1], sz[2], 0.0, 0.0, yaw]
                if placer.box_free(row, 0.05):
                    group.box(row[:3], row[3:6], None, rpy=row[6:9], tag='furniture')
                    steel = str(rng.choice(['paint_gray', 'paint_white', 'paint_green', 'paint_blue']))
                    kit.place(group, str(kind), (px, py, 0.0), yaw + (math.pi if rng.random() < 0.5 else 0.0),
                              roles={'steel': steel})
                    placer.mark_box(row)
                    break

    dress_building(rng, group, b, ext, openings, int_doors, damage, facade, height, storeys, has_sign=bool(sign_label))

    # --- shop sign above the main entrance
    doors = [e for e in b.entrances if e['kind'] == 'door']
    if sign_label and doors:
        e = doors[0]
        yaw = math.atan2(e['ny'], e['nx'])
        sx = e['x'] + e['nx'] * (t / 2 + 0.04)
        sy = e['y'] + e['ny'] * (t / 2 + 0.04)
        b.signs.append(dict(label=sign_label, x=sx, y=sy, z=DOOR_H + 0.55, yaw=yaw, w=2.8, h=0.7))
    return b


WINDOW_KINDS = ['window_broken', 'window_empty', 'window_boarded', 'window_bars', 'window_intact', 'window_shutter']
TRIMS = ['paint_white', 'paint_black', 'wood', 'paint_gray', 'paint_green']


def dress_building(rng, group, b, ext, openings, int_doors, damage, facade, height, storeys, has_sign=False):
    """Visual detail on top of the box walls: window and door sets, broken masonry around breaches,
    parapet, rooftop plant, wall-mounted AC units and awnings. Nothing here has collision, and all
    of it either hugs existing walls or sits above the robot."""
    trim = str(rng.choice(TRIMS))
    p_kind = np.array([0.34, 0.18, 0.16, 0.1, 0.12 * (1.2 - damage), 0.1])
    p_kind /= p_kind.sum()
    x0, y0, x1, y1 = b.rect
    top = height * storeys
    for side, (axis, fixed, a, bb, sgn) in ext.items():
        yaw = (0.0 if sgn > 0 else math.pi) if axis == 'x' else (-math.pi / 2 if sgn > 0 else math.pi / 2)
        nx, ny = (0.0, float(sgn)) if axis == 'x' else (float(sgn), 0.0)

        def at(c, off=0.0):
            return (c + nx * off, fixed + ny * off) if axis == 'x' else (fixed + nx * off, c + ny * off)
        ops = openings[side]
        wins = [o for o in ops if o[2] > 0.5]
        for c, w, z0, z1 in ops:
            px, py = at(c)
            if z0 > 0.5:                                           # window (+ the one above it)
                for level in range(storeys):
                    if level > 0 and not any(s + 0.25 < c - w / 2 and c + w / 2 < e - 0.25 and hi > WIN_Z1 + 0.25
                                             for s, e, hi in b.upper.get(side, [])):
                        continue                                   # that part of the upper wall is gone
                    if level == 0 and rng.random() < 0.25 + 0.45 * damage and top - z1 > 0.9:
                        sh = min(2.6, top - z1 - 0.05)             # fire has licked out of this window
                        sx_, sy_ = at(c, EXT_T / 2 + 0.03)
                        group.mesh(str(rng.choice(['decal_soot_a', 'decal_soot_b']))).add_panel(
                            (sx_, sy_, z1 + sh / 2 - 0.1), 1.7, sh, yaw + math.pi / 2)
                    kind = str(rng.choice(WINDOW_KINDS, p=p_kind))
                    kit.place(group, kind, (px, py, level * height + (z0 + z1) / 2), yaw,
                              roles={'frame': trim, 'stone': 'concrete'})
            elif z1 <= DOOR_H + 0.01:                              # entrance
                crowded = any(abs(o[0] - c) < 2.7 for o in wins)
                kind = 'door_open' if crowded or rng.random() < 0.35 else str(rng.choice(['door_double', 'door_one_leaf']))
                kit.place(group, kind, (px, py, 0.0), yaw, roles={'frame': trim, 'stone': 'concrete'})
                if not has_sign and not crowded and rng.random() < 0.6:
                    ax_, ay_ = at(c, EXT_T / 2)
                    kit.place(group, 'awning', (ax_, ay_, DOOR_H + 0.12), yaw,
                              roles={'canvas': 'fabric_' + str(rng.choice(['red', 'green', 'blue', 'orange', 'yellow']))})
            else:                                                  # breach: ragged masonry on both edges
                for edge in (c - w / 2, c + w / 2):
                    inward = 1.0 if edge < c else -1.0
                    z = 0.0
                    while z < min(top, height) - 0.2:
                        hh = float(rng.uniform(0.35, 0.7))
                        ww = float(rng.uniform(0.3, 0.75))
                        ex_, ey_ = at(edge - inward * (ww / 2 - float(rng.uniform(0.02, 0.14))))
                        row = [ex_, ey_, z + hh / 2, ww if axis == 'x' else EXT_T + 0.06, EXT_T + 0.06 if axis == 'x' else ww,
                               hh, float(rng.uniform(-0.12, 0.12)), float(rng.uniform(-0.12, 0.12)), float(rng.uniform(-0.1, 0.1))]
                        kit.fit(group, str(rng.choice(['chunk_b', 'chunk_c', 'chunk_d', 'chunk_e'])), row,
                                roles={'concrete': str(rng.choice(['brick', 'concrete', 'rubble']))})
                        z += hh * 0.8
        # wall-mounted condensers, high on the facade between openings
        for _ in range(int(rng.integers(0, 3))):
            c = float(rng.uniform(a + 1.2, bb - 1.2))
            if all(abs(c - o[0]) > o[1] / 2 + 0.7 for o in ops):
                ax_, ay_ = at(c, EXT_T / 2)
                kit.place(group, 'ac_unit', (ax_, ay_, float(rng.uniform(2.35, 2.7))),
                          yaw)
        # shell strikes and cracks on the ground-floor wall, clear of every opening
        for _ in range(int(rng.poisson(0.6 + 2.2 * damage))):
            sz = float(rng.uniform(1.5, 2.3))
            c = float(rng.uniform(a + sz / 2 + 0.2, max(a + sz / 2 + 0.21, bb - sz / 2 - 0.2)))
            if all(abs(c - o[0]) > o[1] / 2 + sz / 2 + 0.25 for o in ops):
                dx_, dy_ = at(c, EXT_T / 2 + 0.03)
                name = str(rng.choice(['decal_wallhole_a', 'decal_wallhole_b', 'decal_cracks_a']))
                group.mesh(name).add_panel((dx_, dy_, float(rng.uniform(sz / 2 + 0.15, max(sz / 2 + 0.16, height - sz / 2 - 0.1)))),
                                           sz, sz, yaw + math.pi / 2)
        # parapet (single-storey buildings): lengths of it knocked away
        if storeys == 1:
            pos = a - (EXT_T if axis == 'y' else 0)
            end = bb + (EXT_T if axis == 'y' else 0)
            while pos < end - 0.05:
                w = min(float(rng.uniform(1.8, 4.2)), end - pos)
                if rng.random() > 0.3 * damage + 0.08:
                    cx_, cy_ = at(pos + w / 2)
                    size = (w, 0.22, 0.5) if axis == 'x' else (0.22, w, 0.5)
                    group.box((cx_, cy_, top + 0.25), size, facade, collide=False)
                    group.box((cx_, cy_, top + 0.53), (size[0] + 0.06, size[1] + 0.08, 0.06), 'concrete', collide=False)
                pos += w
    # interior door frames
    for axis, fixed, c, width in int_doors:
        px, py = (c, fixed) if axis == 'x' else (fixed, c)
        kit.place(group, 'door_interior' if width > 1.6 else 'door_interior_narrow', (px, py, 0.0),
                  0.0 if axis == 'x' else math.pi / 2, roles={'frame': trim})
    # rooftop plant on rooms that still have a roof
    roofed = [r for r in b.rooms if r['roof']] if storeys == 1 else []     # a shelled upper storey carries no plant
    rz = top + 0.2
    for r in roofed:
        if rng.random() < 0.55:
            rx0, ry0, rx1, ry1 = r['rect']
            if rx1 - rx0 < 2.6 or ry1 - ry0 < 2.6:
                continue
            kind = str(rng.choice(['roof_tank', 'roof_hvac', 'roof_dish', 'roof_antenna']))
            kit.place(group, kind, (float(rng.uniform(rx0 + 1.2, rx1 - 1.2)), float(rng.uniform(ry0 + 1.2, ry1 - 1.2)), rz),
                      float(rng.uniform(0, 6.28)))
