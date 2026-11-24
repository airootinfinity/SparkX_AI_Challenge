"""City layout: street grid, ground, perimeter, block assignment, street clutter, blockages, fires."""
import math

import numpy as np

from . import blocks as B
from . import kit
from . import props
from . import warzone
from .sdfgen import emitter

SIZES = {'small': (2, 2), 'medium': (3, 2), 'large': (3, 3)}
DIFFICULTY = {
    #          extra fires, static blockages, parked vehicles per segment, street debris prob
    'easy': dict(fires=1, blockages=0, park=1.0, debris=0.3),
    'normal': dict(fires=3, blockages=1, park=1.5, debris=0.5),
    'hard': dict(fires=5, blockages=2, park=2.0, debris=0.8),
}
SW = 1.5  # sidewalk width


class Layout:
    def __init__(self, nx, ny, block=24.0, street=10.0):
        self.nx, self.ny, self.B, self.S = nx, ny, block, street
        self.P = block + street
        self.W = nx * self.P + street
        self.H = ny * self.P + street

    def block_rect(self, i, j):
        x0, y0 = self.S + i * self.P, self.S + j * self.P
        return (x0, y0, x0 + self.B, y0 + self.B)

    def segments(self):
        segs = []
        for l in range(self.ny + 1):
            for k in range(self.nx):
                x0, y0 = k * self.P + self.S, l * self.P
                segs.append(dict(id=f'h{l}_{k}', axis='x', rect=(x0, y0, x0 + self.B, y0 + self.S),
                                 ends=((k, l), (k + 1, l))))
        for k in range(self.nx + 1):
            for l in range(self.ny):
                x0, y0 = k * self.P, l * self.P + self.S
                segs.append(dict(id=f'v{k}_{l}', axis='y', rect=(x0, y0, x0 + self.S, y0 + self.B),
                                 ends=((k, l), (k, l + 1))))
        return segs

    def intersections(self):
        return [(k, l, (k * self.P, l * self.P, k * self.P + self.S, l * self.P + self.S))
                for k in range(self.nx + 1) for l in range(self.ny + 1)]


def build_ground(scene, lay):
    g = scene.group('streets')
    for seg in lay.segments():
        x0, y0, x1, y1 = seg['rect']
        if seg['axis'] == 'x':
            g.mesh('asphalt_lane').add_rect_xy(x0, y0 + SW, x1, y1 - SW, z=0.004, tile=12.0, u_along='x')
            g.mesh('sidewalk').add_rect_xy(x0, y0, x1, y0 + SW, z=0.01, tile=3.0)
            g.mesh('sidewalk').add_rect_xy(x0, y1 - SW, x1, y1, z=0.01, tile=3.0)
            cy = (y0 + y1) / 2
            scene.placer.reserve_rect(x0, cy - 1.3, x1, cy + 1.3)
        else:
            g.mesh('asphalt_lane').add_rect_xy(x0 + SW, y0, x1 - SW, y1, z=0.004, tile=12.0, u_along='y')
            g.mesh('sidewalk').add_rect_xy(x0, y0, x0 + SW, y1, z=0.01, tile=3.0)
            g.mesh('sidewalk').add_rect_xy(x1 - SW, y0, x1, y1, z=0.01, tile=3.0)
            cx = (x0 + x1) / 2
            scene.placer.reserve_rect(cx - 1.3, y0, cx + 1.3, y1)
        scene.street_segments.append(dict(seg, blocked=False))
    for k, l, (x0, y0, x1, y1) in lay.intersections():
        g.mesh('asphalt').add_rect_xy(x0, y0, x1, y1, z=0.004, tile=6.0)
        scene.placer.reserve_rect(x0 + 1.0, y0 + 1.0, x1 - 1.0, y1 - 1.0)
    # distant ground
    g.mesh('dirt').add_rect_xy(-60, -60, lay.W + 60, lay.H + 60, z=-0.002, tile=8.0)


SIDES = ('-x', '+x', '-y', '+y')
BACKDROP = ['facade_a', 'facade_b', 'facade_c', 'facade_d', 'facade_e']


def build_perimeter(scene, lay, rng):
    """Arena boundary (collision) dressed as a shelled terrace with a broken roofline, scarred by
    shell strikes and hung with sponsor banners, in front of a visual-only skyline of bombed-out
    towers, some of them still burning."""
    g = scene.group('perimeter')
    t, h = 1.0, 7.0
    W, H = lay.W, lay.H
    sides = [  # (start xy, direction xy, length, inward normal yaw)
        ((-t, -t / 2), (1, 0), W + 2 * t, math.pi / 2), ((-t, H + t / 2), (1, 0), W + 2 * t, -math.pi / 2),
        ((-t / 2, 0.0), (0, 1), H, 0.0), ((W + t / 2, 0.0), (0, 1), H, math.pi)]
    for (sx, sy), (dx, dy), L, inward in sides:
        g.box((sx + dx * L / 2, sy + dy * L / 2, h / 2), (L if dx else t, L if dy else t, h), None, tag='perimeter')
        pos = 0.0
        while pos < L - 0.01:
            w = min(float(rng.uniform(10.5, 17.5)), L - pos)
            if L - pos - w < 6.0:
                w = L - pos
            warzone.jagged_wall(g, rng, (sx + dx * pos, sy + dy * pos), (dx, dy), w, t, h, str(rng.choice(BACKDROP)), inward)
            mx, my = sx + dx * (pos + w / 2) + math.cos(inward) * t / 2, sy + dy * (pos + w / 2) + math.sin(inward) * t / 2
            warzone.scar_wall(g, rng, mx, my, inward, 1.6, 6.0, 0.7, length=w * 0.9)
            pos += w
        n = max(2, int(L // 26))                                   # sponsor banners / event billboards
        for k in range(n):
            s = L * (k + 0.5) / n + float(rng.uniform(-2, 2))
            bx, by = sx + dx * s + math.cos(inward) * (t / 2 + 0.06), sy + dy * s + math.sin(inward) * (t / 2 + 0.06)
            if k % 2 == 0:
                g.mesh('brand_banner').add_panel((bx, by, 5.1), 8.0, 2.0, inward)
            else:
                g.mesh('brand_billboard').add_panel((bx, by, 5.0), 5.6, 2.8, inward)
    sk = scene.group('skyline')
    towers = []
    for side in range(4):
        L = W if side < 2 else H
        pos = -5.0
        while pos < L + 5:
            w = float(rng.uniform(10.5, 17.5))
            d = float(rng.uniform(10.5, 14.0))
            hh = float(rng.uniform(14.0, 31.5)) if rng.random() > 0.2 else float(rng.uniform(8.0, 12.0))
            c = pos + w / 2
            off = t + 1.5 + d / 2
            center = ((c, -off), (c, H + off), (-off, c), (W + off, c))[side]
            size = (w, d) if side < 2 else (d, w)
            facade = str(rng.choice(BACKDROP))
            if rng.random() < 0.8:
                warzone.ruined_shell(sk, rng, center[0], center[1], size[0], size[1], hh, facade,
                                     damage=float(rng.uniform(0.35, 0.95)))
            else:
                sk.box((center[0], center[1], hh / 2), (size[0], size[1], hh), facade, collide=False, faces=SIDES)
                sk.box((center[0], center[1], hh / 2), (size[0], size[1], hh), 'concrete_dark', collide=False, faces=('top',))
            towers.append((center[0], center[1], hh))
            pos += w + float(rng.uniform(0.0, 3.0))
    for k in rng.permutation(len(towers))[:5]:                     # towers still burning beyond the cordon
        x, y, hh = towers[int(k)]
        scene.models.append(emitter(scene.uid('far_smoke'), (x, y, hh * 0.55), 'smoke', float(rng.uniform(3.0, 4.5)), scatter=0.3))


def assign_blocks(lay, rng):
    cells = [(i, j) for i in range(lay.nx) for j in range(lay.ny)]
    base = (0, 0)
    far = sorted(cells, key=lambda c: -(c[0] ** 2 + c[1] ** 2))
    crater = far[int(rng.integers(0, min(2, len(far) - 1)))] if len(far) > 2 else far[0]
    rest = [c for c in cells if c not in (base, crater)]
    rng.shuffle(rest)
    types = []
    n = len(rest)
    types += ['building'] * max(1, n // 3)
    types += ['twin'] * max(1, n // 4) if n >= 2 else []
    if n >= 3:
        types += [str(rng.choice(['plaza', 'yard']))]
    if n >= 4:
        types += ['ruin']
    while len(types) < n:
        types.append(str(rng.choice(['building', 'twin', 'plaza', 'yard', 'ruin'], p=[0.3, 0.25, 0.15, 0.15, 0.15])))
    types = types[:n]
    rng.shuffle(types)
    out = {base: 'base', crater: 'crater'}
    out.update({c: t for c, t in zip(rest, types)})
    return out, crater


def build_blocks(scene, ctx, lay, rng):
    types, crater = assign_blocks(lay, rng)
    cr = lay.block_rect(*crater)
    ex, ey = (cr[0] + cr[2]) / 2, (cr[1] + cr[3]) / 2
    diag = math.hypot(lay.W, lay.H)
    scene.blocks = []
    start = None
    order = sorted(types.items(), key=lambda kv: {'base': 0, 'crater': 1}.get(kv[1], 2))
    for (i, j), typ in order:
        rect = lay.block_rect(i, j)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        dmg = float(np.clip(1.1 - math.hypot(cx - ex, cy - ey) / (0.75 * diag), 0.1, 1.0))
        blk = dict(i=i, j=j, rect=rect, type=typ, damage=0.1 if typ == 'base' else dmg, name=f'block_{i}_{j}')
        scene.blocks.append(blk)
        fn = {'base': B.build_base, 'crater': B.build_crater, 'building': B.build_building, 'twin': B.build_twin,
              'ruin': B.build_ruin, 'plaza': B.build_plaza, 'yard': B.build_yard}[typ]
        res = fn(scene, ctx, blk)
        if typ == 'base':
            start = res
    return start


def street_clutter(scene, ctx, lay, diff, rng):
    ex, ey, _ = scene.epicenter
    diag = math.hypot(lay.W, lay.H)
    special = ['sparkx_bus', 'sparkx_fire_truck']
    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dmg = float(np.clip(1.1 - math.hypot(cx - ex, cy - ey) / (0.75 * diag), 0.05, 1.0))
        along = seg['axis'] == 'x'
        L = (x1 - x0) if along else (y1 - y0)
        # parked / abandoned vehicles along the kerb
        for _ in range(int(rng.poisson(diff['park']))):
            side = float(rng.choice([-1, 1]))
            t = float(rng.uniform(3, L - 3))
            off = side * (lay.S / 2 - SW - 0.95)
            px, py = (x0 + t, cy + off) if along else (cx + off, y0 + t)
            yaw = (0.0 if along else math.pi / 2) + (math.pi if rng.random() < 0.5 else 0) + float(rng.normal(0, 0.08))
            if rng.random() < 0.6 * dmg:
                props.burnt_car(scene, ctx.cat, px, py, yaw, margin=0.15)
            elif special and rng.random() < 0.3:
                name = special[int(rng.integers(0, len(special)))]
                if props.place_catalog(scene, ctx.cat, name, px + (side * 0.3 if not along else 0),
                                       py + (side * 0.3 if along else 0), yaw, margin=0.2, ignore_reserved=True):
                    special.remove(name)
            else:
                props.place_catalog(scene, ctx.cat, str(rng.choice(B.CARS)), px, py, yaw, margin=0.15)
        # debris on sidewalks / street sides
        if rng.random() < diff['debris'] * (0.4 + dmg):
            side = float(rng.choice([-1, 1]))
            t = float(rng.uniform(3, L - 3))
            off = side * (lay.S / 2 - 1.6)
            px, py = (x0 + t, cy + off) if along else (cx + off, y0 + t)
            props.rubble_pile(scene, scene.group(f'debris_{scene.uid("d")}'), ctx.cat, px, py,
                              float(rng.uniform(1.0, 1.8)), float(rng.uniform(0.6, 1.2)))
            B.near_slots(scene, rng, px, py, 1.8, 2.8, 1, 'street', kind='street', near='rubble')
        if rng.random() < 0.35 * dmg:
            t = float(rng.uniform(4, L - 4))
            off = float(rng.choice([-1, 1])) * (lay.S / 2 - 1.2)
            px, py = (x0 + t, cy + off) if along else (cx + off, y0 + t)
            props.rock(scene, ctx.cat, px, py, float(rng.uniform(1.2, 2.4)))
    # a few police/cordon barriers near the epicenter
    for _ in range(3):
        a = rng.uniform(0, 2 * math.pi)
        r = float(rng.uniform(14, 20))
        props.place_catalog(scene, ctx.cat, 'sparkx_jersey_barrier', ex + r * math.cos(a), ey + r * math.sin(a),
                            float(a + math.pi / 2), margin=0.3)


def ensure_landmarks(scene, ctx, rng, minimum=None):
    """Guarantee a few colour landmarks exist (hint anchors), placed in open block areas."""
    minimum = minimum or {'water_tank': 2, 'tent': 1, 'container': 2}
    open_blocks = [b for b in scene.blocks if b['type'] in ('building', 'twin', 'yard', 'plaza', 'ruin')]
    for kind, n in minimum.items():
        have = sum(1 for lm in scene.landmarks if lm['cls'] == kind)
        for _ in range(max(0, n - have)):
            rng.shuffle(open_blocks)
            for blk in open_blocks:
                got = B.scatter(scene, ctx, blk['rect'], [kind], 1, margin=2.0, tries=40)
                if got:
                    _k, px, py, _yaw, _rec = got[0]
                    B.near_slots(scene, rng, px, py, 2.4, 4.0, 1, 'open_area', kind='yard', near=kind)
                    break


def street_blockage(scene, ctx, lay, seg, group):
    """Impassable rubble barrier across a street segment (full width)."""
    x0, y0, x1, y1 = seg['rect']
    rng = ctx.rng
    along = seg['axis'] == 'x'
    t = float(rng.uniform(0.35, 0.65))
    if along:
        px, py, yaw = x0 + t * (x1 - x0), (y0 + y1) / 2, math.pi / 2
    else:
        px, py, yaw = (x0 + x1) / 2, y0 + t * (y1 - y0), 0.0
    props.rubble_pile(scene, group, ctx.cat, px, py, lay.S / 2, 1.4, density=1.3, rocks=0,
                      solid_core=(lay.S + 0.6, 2.2, yaw), ignore_reserved=True)
    return dict(segment=seg['id'], x=float(px), y=float(py), yaw=float(yaw), width=float(lay.S + 0.6), depth=2.2)


def static_blockages(scene, ctx, lay, diff, rng):
    base_i = lay.block_rect(0, 0)
    cands = [s for s in scene.street_segments
             if not (s['rect'][0] < base_i[2] + 1 and s['rect'][1] < base_i[3] + 1)]
    ex, ey, _ = scene.epicenter
    cands.sort(key=lambda s: math.hypot((s['rect'][0] + s['rect'][2]) / 2 - ex, (s['rect'][1] + s['rect'][3]) / 2 - ey))
    n = min(diff['blockages'], max(0, len(cands) // 5))
    for seg in cands[:n * 2][::2][:n]:
        rec = street_blockage(scene, ctx, lay, seg, scene.group(f'blockage_{seg["id"]}'))
        seg['blocked'] = True
        scene.blockages.append(rec)


def extra_fires(scene, ctx, n, rng):
    """Fires inside damaged buildings (roofless rooms) and on streets near the epicenter."""
    ex, ey, _ = scene.epicenter
    cands = []
    for b in scene.buildings:
        for r in b.rooms:
            if not r['collapsed'] and not r['roof']:
                x0, y0, x1, y1 = r['rect']
                cands.append(((x0 + x1) / 2, (y0 + y1) / 2, 1.0))
    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        d = math.hypot(cx - ex, cy - ey)
        off = (0, (y1 - y0) / 2 - 2.0) if seg['axis'] == 'x' else ((x1 - x0) / 2 - 2.0, 0)
        for sgn in (-1, 1):
            cands.append((cx + sgn * off[0], cy + sgn * off[1], 1.0 / (1.0 + d / 20.0)))
    rng.shuffle(cands)
    cands.sort(key=lambda c: -c[2] * rng.uniform(0.5, 1.5))
    placed = 0
    for x, y, _w in cands:
        if placed >= n:
            break
        if all(math.hypot(x - f['x'], y - f['y']) > 12 for f in scene.fires) and scene.placer.point_free(x, y, 1.0):
            props.fire(scene, x, y, float(rng.uniform(0.7, 1.3)))
            placed += 1


def street_furniture(scene, ctx, lay, rng):
    """Zebra crossings, street lights (some knocked askew), road signs, and utility poles with
    sagging overhead lines. Every post has a small collision box and is recorded in the placer."""
    g = scene.group('street_furniture')

    def post(x, y, size, height):
        row = [x, y, height / 2, size, size, height, 0, 0, 0]
        if not scene.placer.box_free(row, 0.25, ignore_reserved=True):
            return False
        g.box(row[:3], row[3:6], None, tag='post')
        scene.placer.mark_box(row)
        return True

    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        along = seg['axis'] == 'x'
        L = (x1 - x0) if along else (y1 - y0)
        m = g.mesh('crosswalk')
        for s0 in (0.4, L - 3.4):                                  # crossings at both ends of the block
            if along:
                xa, xb = x0 + s0, x0 + s0 + 3.0
                m.add_poly([(xa, y0 + SW, 0.007), (xb, y0 + SW, 0.007), (xb, y1 - SW, 0.007), (xa, y1 - SW, 0.007)],
                           [(0, 0), (1, 0), (1, 1), (0, 1)], (0, 0, 1.0))
            else:
                ya, yb = y0 + s0, y0 + s0 + 3.0
                m.add_poly([(x0 + SW, ya, 0.007), (x1 - SW, ya, 0.007), (x1 - SW, yb, 0.007), (x0 + SW, yb, 0.007)],
                           [(0, 0), (0, 1), (1, 1), (1, 0)], (0, 0, 1.0))
        k, s = 0, float(rng.uniform(5.0, 9.0))
        while s < L - 4.0:                                         # street lights, alternating sides
            side = 1 if k % 2 == 0 else -1
            off = side * (lay.S / 2 - SW + 0.3)
            px, py = (x0 + s, (y0 + y1) / 2 + off) if along else ((x0 + x1) / 2 + off, y0 + s)
            yaw = (-side * math.pi / 2) if along else (math.pi if side > 0 else 0.0)
            if post(px, py, 0.22, 4.0):
                lean = float(rng.uniform(0.04, 0.2)) if rng.random() < 0.3 else 0.0
                kit.place(g, 'street_lamp', (px, py, 0.0), rpy=(lean, 0.0, yaw + (float(rng.uniform(-0.5, 0.5)) if lean else 0.0)))
            s += float(rng.uniform(15.0, 19.0))
            k += 1
        if rng.random() < 0.55:                                    # a road sign near one end
            side = float(rng.choice([-1, 1]))
            off = side * (lay.S / 2 - 0.45)
            s = 2.2 if rng.random() < 0.5 else L - 2.2
            px, py = (x0 + s, (y0 + y1) / 2 + off) if along else ((x0 + x1) / 2 + off, y0 + s)
            if post(px, py, 0.12, 2.9):
                face = (math.pi / 2 if s < L / 2 else -math.pi / 2) if along else (math.pi if s < L / 2 else 0.0)
                kit.place(g, str(rng.choice(['sign_stop', 'sign_warning', 'sign_info'])), (px, py, 0.0),
                          rpy=(float(rng.uniform(-0.12, 0.12)), 0.0, face))
    # utility poles on block corners, joined by overhead lines
    poles = {}
    for k in range(lay.nx + 1):
        for l in range(lay.ny + 1):
            px, py = k * lay.P + lay.S - 0.5, l * lay.P + lay.S - 0.5
            if k < lay.nx and l < lay.ny and post(px, py, 0.3, 8.5):
                kit.place(g, 'utility_pole', (px, py, 0.0), 0.0)
                poles[(k, l)] = (px, py)
    for (k, l), (px, py) in poles.items():
        for nk, nl in ((k + 1, l), (k, l + 1)):
            if (nk, nl) not in poles:
                continue
            qx, qy = poles[(nk, nl)]
            for off in ((-0.9, 0.3, 0.9) if nk > k else (-0.3, 0.3)):
                if rng.random() < 0.12:
                    continue                                       # a line brought down by the blast
                ox, oy = (0.0, off) if nk > k else (off, 0.0)
                sag = float(rng.uniform(0.6, 1.3))
                path = [(px + ox + (qx - px) * u, py + oy + (qy - py) * u, (8.13 if nk > k else 7.7) - sag * 4 * u * (1 - u))
                        for u in np.linspace(0, 1, 9)]
                kit.tube(g, 'rubber', path, 0.018, sides=3)
