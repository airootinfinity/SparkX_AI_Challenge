"""City block builders. Each builder fills one block rectangle and appends survivor slots."""
import math

import numpy as np

from . import kit
from . import landmarks as lmk
from . import props
from .buildings import make_building, emit_wall
from .ruins import ruin_collisions
from .sdfgen import emitter, include

FACADES = ['brick', 'brick_grey', 'plaster', 'plaster_blue', 'plaster_yellow', 'plaster_damaged', 'plaster_red',
           'concrete']


class Ctx:
    """Generation context shared by the block builders."""

    def __init__(self, cat, models_dir, mesh_dir, uri_prefix, rng, sign_pool):
        self.cat = cat
        self.models_dir = models_dir
        self.mesh_dir = mesh_dir
        self.uri = uri_prefix
        self.rng = rng
        self.sign_pool = list(sign_pool)
        self.pools = {}

    def color(self, cls, options):
        pool = self.pools.get(cls)
        if not pool:
            pool = list(options)
            self.rng.shuffle(pool)
            self.pools[cls] = pool
        return pool.pop()

    def sign(self):
        return self.sign_pool.pop() if self.sign_pool else None


TANK_COLORS = ['red', 'blue', 'green', 'yellow', 'white']
CONTAINER_COLORS = ['red', 'blue', 'green', 'yellow', 'orange', 'white', 'gray']
TENT_COLORS = ['blue', 'white', 'orange', 'green', 'yellow']
CARS = ['sparkx_car_red', 'sparkx_car_white', 'sparkx_car_blue', 'sparkx_car_yellow', 'sparkx_car_green',
        'sparkx_suv', 'sparkx_pickup']


def _try(scene, row, margin=0.4):
    return scene.placer.box_free(row, margin)


def _mark_group(scene, gname):
    for row in scene.groups[gname].collisions:
        scene.placer.mark_box(row)


def inside_building(scene, x, y, clearance=0.0):
    """True when (x, y) lies inside a building footprint or closer than `clearance` to one. Room
    interiors look free to the placer (only the walls are marked), so anything that must stand
    outdoors has to ask this as well."""
    return any(b.contains(x, y, -clearance) for b in scene.buildings)


def place_landmark(scene, ctx, kind, x, y, yaw, **kw):
    """Place a procedural landmark if its footprint is free and outdoors. Returns landmark record or None."""
    size = {'water_tank': (2.7, 2.7), 'container': (6.2, 2.7), 'tent': (3.8, 3.8), 'fountain': (4.8, 4.8)}[kind]
    row = [x, y, 1.0, size[0], size[1], 2.0, 0, 0, yaw]
    if inside_building(scene, x, y, 0.5 * math.hypot(*size) + 0.4) or not _try(scene, row, 0.5):
        return None
    if kind == 'water_tank':
        rec = lmk.water_tank(scene, x, y, kw.get('color') or ctx.color('water_tank', TANK_COLORS), yaw)
    elif kind == 'container':
        rec = lmk.container(scene, x, y, kw.get('color') or ctx.color('container', CONTAINER_COLORS), yaw,
                            damaged=kw.get('damaged', False))
    elif kind == 'tent':
        rec = lmk.tent(scene, x, y, kw.get('color') or ctx.color('tent', TENT_COLORS), yaw)
    else:
        rec = lmk.fountain(scene, x, y)
    _mark_group(scene, rec['model'])
    return rec


def random_point(rng, rect, margin):
    x0, y0, x1, y1 = rect
    return float(rng.uniform(x0 + margin, x1 - margin)), float(rng.uniform(y0 + margin, y1 - margin))


def scatter(scene, ctx, rect, kinds, n, margin=2.0, tries=30):
    """Scatter n objects of random kinds inside rect."""
    rng = ctx.rng
    placed = []
    for _ in range(n):
        for _t in range(tries):
            x, y = random_point(rng, rect, margin)
            yaw = float(rng.choice([0, math.pi / 2, math.pi, -math.pi / 2]) + rng.normal(0, 0.15))
            kind = str(rng.choice(kinds))
            rec = None
            if kind in ('car', 'dumpster', 'hydrant', 'barrel', 'barrier') and inside_building(scene, x, y, 2.8 if kind == 'car' else 1.2):
                continue                                           # vehicles and street furniture stay outdoors
            if kind in ('water_tank', 'container', 'tent'):
                rec = place_landmark(scene, ctx, kind, x, y, yaw, damaged=(kind == 'container' and rng.random() < 0.25))
            elif kind == 'car':
                rec = props.place_catalog(scene, ctx.cat, str(rng.choice(CARS)), x, y, yaw, margin=0.5)
            elif kind in ('dumpster', 'hydrant', 'barrel', 'barrier'):
                name = {'dumpster': 'sparkx_dumpster', 'hydrant': 'sparkx_hydrant', 'barrel': 'sparkx_traffic_barrel',
                        'barrier': 'sparkx_jersey_barrier'}[kind]
                rec = props.place_catalog(scene, ctx.cat, name, x, y, yaw, margin=0.4)
            elif kind == 'rubble':
                rec = props.rubble_pile(scene, scene.group(f'debris_{scene.uid("d")}'), ctx.cat, x, y,
                                        float(rng.uniform(1.0, 2.2)), float(rng.uniform(0.6, 1.3)))
            elif kind == 'rock':
                rec = props.rock(scene, ctx.cat, x, y, float(rng.uniform(0.8, 2.0)))
            if rec:
                placed.append((kind, x, y, yaw, rec))
                break
    return placed


def add_slots(scene, kind, pts, area, **extra):
    for x, y, yaw in pts:
        s = dict(kind=kind, x=float(x), y=float(y), yaw=float(yaw), area=area)
        s.update(extra)
        scene.survivor_slots.append(s)


def room_slots(scene, rng, b, per_room=2):
    pts = []
    for room in b.rooms:
        if room['collapsed']:
            continue
        x0, y0, x1, y1 = room['rect']
        for _ in range(per_room * 4):
            if len([p for p in pts if p[3] == room['id']]) >= per_room:
                break
            x, y = float(rng.uniform(x0 + 0.9, x1 - 0.9)), float(rng.uniform(y0 + 0.9, y1 - 0.9))
            if scene.placer.point_free(x, y, 0.9):
                pts.append((x, y, float(rng.uniform(-math.pi, math.pi)), room['id']))
    for x, y, yaw, rid in pts:
        scene.survivor_slots.append(dict(kind='room', x=x, y=y, yaw=yaw, area='room', building=b.id, room=rid))


def near_slots(scene, rng, cx, cy, r0, r1, n, area, kind='open', **extra):
    got = 0
    for _ in range(n * 10):
        if got >= n:
            break
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(r0, r1)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if scene.placer.point_free(x, y, 0.8) and not inside_building(scene, x, y, 0.6):
            add_slots(scene, kind, [(x, y, a + math.pi)], area, **extra)
            got += 1


# ----------------------------------------------------------------------------------------------
def build_base(scene, ctx, blk):
    """Rescue base: branded start pad, start gate over the east exit, relief tent, ambulance,
    container, floodlights and sponsor flags."""
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('concrete').add_rect_xy(x0, y0, x1, y1, z=0.008, tile=4.0)
    cx, cy = x0 + 8.0, y0 + 8.0
    g.mesh('basepad').add_quad_centered((cx, cy), 8.0, 8.0, 0.0, 0.014)
    scene.placer.reserve_rect(cx - 5, cy - 5, cx + 5, cy + 5)
    scene.placer.reserve_rect(cx, cy - 2, x1 + 1, cy + 2)       # exit corridor east
    scene.placer.reserve_rect(cx - 2, cy, cx + 2, y1 + 1)       # exit corridor north
    rng = ctx.rng

    def solid(row, tag='base'):
        g.box(row[:3], row[3:6], None, rpy=row[6:9], tag=tag)
        scene.placer.mark_box(row)

    # start gate spanning the east exit corridor (towers stand clear of the 4 m lane)
    gx = x1 - 1.6
    for sy in (-1, 1):
        solid([gx, cy + sy * 3.6, 2.65, 0.9, 0.9, 5.3, 0, 0, 0])
    kit.place(g, 'gantry', (gx, cy, 0.0), 0.0)
    for yaw, off in ((0.0, 0.24), (math.pi, -0.24)):
        g.mesh('brand_gantry').add_panel((gx + off, cy, 4.8), 7.0, 1.0, yaw)
    # relief tent and container boards (artwork by partner priority: see branding.py)
    tx, ty = x0 + 3.5, y1 - 4.0
    if place_landmark(scene, ctx, 'tent', tx, ty, 0.0, color='white'):
        g.mesh('brand_airoot').add_panel((tx, ty - 1.9, 1.05), 2.4, 1.2, -math.pi / 2)
    props.place_catalog(scene, ctx.cat, 'sparkx_ambulance', x1 - 7.0, y0 + 3.0, 0.0, margin=0.3)
    kx, ky, kyaw = x1 - 5.0, y1 - 3.0, math.pi / 2 * rng.integers(0, 2)
    if place_landmark(scene, ctx, 'container', kx, ky, kyaw):
        n = -math.pi / 2 if abs(math.sin(kyaw)) < 0.5 else math.pi           # the long side that faces the pad
        g.mesh('brand_stemlearn').add_panel((kx + 1.26 * math.cos(n), ky + 1.26 * math.sin(n), 1.45), 3.0, 1.5, n)
    # floodlight towers and sponsor flags around the pad
    for fx, fy, fyaw in ((cx - 5.6, cy - 5.6, math.pi / 4), (cx - 5.6, cy + 5.6, -math.pi / 4)):
        solid([fx, fy, 0.5, 0.9, 0.9, 1.0, 0, 0, fyaw])
        solid([fx, fy, 2.4, 0.12, 0.12, 3.6, 0, 0, fyaw])
        kit.place(g, 'floodlight', (fx, fy, 0.0), fyaw)
    for k, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
        fx, fy = cx + sx * 4.7, cy + sy * 4.7
        fyaw = math.atan2(-sy, -sx) + math.pi / 2
        solid([fx, fy, 2.1, 0.12, 0.12, 4.2, 0, 0, 0])
        kit.place(g, 'flag', (fx, fy, 0.0), fyaw)
        sail = (fx + 0.45 * math.cos(fyaw), fy + 0.45 * math.sin(fyaw), 2.6)
        g.mesh('brand_flag_airoot' if k % 2 == 0 else 'brand_flag_stemlearn').add_panel(sail, 0.8, 3.0, fyaw + math.pi / 2,
                                                                                         double=True)
    for k in range(4):
        props.place_catalog(scene, ctx.cat, 'sparkx_traffic_barrel', cx - 4.8 + 3.2 * k, cy - 6.4, 0.0, margin=0.1)
    return (cx, cy, 0.0)


def _building_in_block(scene, ctx, blk, rect, storeys=None, sign=True):
    rng = ctx.rng
    facade = str(rng.choice(FACADES))
    st = storeys or (2 if rng.random() < 0.45 else 1)
    b = make_building(rng, scene.group(blk['name']), scene.placer, len(scene.buildings), rect, 'NSEW',
                      blk['damage'], facade, height=3.4, storeys=st, sign_label=ctx.sign() if sign else None)
    scene.buildings.append(b)
    for s in b.signs:
        lmk.sign(scene, ctx.mesh_dir, ctx.uri, s, b.id)
    room_slots(scene, rng, b)
    return b


def build_building(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('dirt').add_rect_xy(x0, y0, x1, y1, z=0.006, tile=6.0)
    W, D = float(rng.uniform(13, 18.5)), float(rng.uniform(10, 15))
    front = str(rng.choice(list('NSEW')))
    sb = 1.5
    if front in 'SN':
        bx0 = float(rng.uniform(x0 + sb, x1 - sb - W))
        by0 = y0 + sb if front == 'S' else y1 - sb - D
    else:
        W, D = D, W
        by0 = float(rng.uniform(y0 + sb, y1 - sb - D))
        bx0 = x0 + sb if front == 'W' else x1 - sb - W
    b = _building_in_block(scene, ctx, blk, (bx0, by0, bx0 + W, by0 + D))
    # yard on the remaining side
    yard = {'S': (x0, by0 + D, x1, y1), 'N': (x0, y0, x1, by0), 'W': (bx0 + W, y0, x1, y1),
            'E': (x0, y0, bx0, y1)}[front]
    kinds = ['water_tank', 'container', 'car', 'car', 'dumpster', 'rubble', 'rock']
    placed = scatter(scene, ctx, yard, kinds, int(rng.integers(2, 4)), margin=1.8)
    for kind, px, py, yaw, rec in placed:
        if kind in ('container', 'car', 'rubble', 'water_tank'):
            near_slots(scene, rng, px, py, 2.2, 4.0, 1, 'open_area' if kind != 'rubble' else 'rubble',
                       kind='yard', near=kind)
    if blk['damage'] > 0.4:  # rubble spilling from breaches
        for e in b.entrances:
            if e['kind'] == 'breach':
                px, py = e['x'] + e['nx'] * 2.0, e['y'] + e['ny'] * 2.0
                props.rubble_pile(scene, g, ctx.cat, px + e['ny'] * 1.8, py + e['nx'] * 1.8, 1.2, 0.8)
    return b


def build_twin(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('concrete_dark').add_rect_xy(x0, y0, x1, y1, z=0.006, tile=5.0)
    alley = float(rng.uniform(3.0, 4.0))
    sb = 1.5
    avail = (x1 - x0) - 2 * sb - alley
    lo = max(6.5, 0.35 * avail)
    if rng.random() < 0.5:  # split along x
        wa = float(rng.uniform(lo, avail - lo))
        r1 = (x0 + sb, y0 + sb + float(rng.uniform(0, 3)), x0 + sb + wa, y1 - sb - float(rng.uniform(0, 3)))
        r2 = (x0 + sb + wa + alley, y0 + sb + float(rng.uniform(0, 3)), x1 - sb, y1 - sb - float(rng.uniform(0, 3)))
    else:
        ha = float(rng.uniform(lo, avail - lo))
        r1 = (x0 + sb + float(rng.uniform(0, 3)), y0 + sb, x1 - sb - float(rng.uniform(0, 3)), y0 + sb + ha)
        r2 = (x0 + sb + float(rng.uniform(0, 3)), y0 + sb + ha + alley, x1 - sb - float(rng.uniform(0, 3)), y1 - sb)
    b1 = _building_in_block(scene, ctx, blk, r1)
    b2 = _building_in_block(scene, ctx, blk, r2, sign=rng.random() < 0.6)
    ax = (r1[2] + r2[0]) / 2 if r2[0] > r1[2] else (x0 + x1) / 2
    ay = (r1[3] + r2[1]) / 2 if r2[1] > r1[3] else (y0 + y1) / 2
    if rng.random() < 0.7:  # debris in the alley
        placed = scatter(scene, ctx, (min(ax, x0 + 3), min(ay, y0 + 3), max(ax, x1 - 3), max(ay, y1 - 3)),
                         ['dumpster', 'rubble', 'rock'], 2, margin=1.0)
        for kind, px, py, yaw, rec in placed:
            near_slots(scene, rng, px, py, 1.8, 3.0, 1, 'rubble', kind='alley', near=kind)
    return b1, b2


def build_ruin(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('rubble').add_rect_xy(x0, y0, x1, y1, z=0.006, tile=4.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for name in rng.permutation(['sparkx_ruin_house', 'sparkx_ruin_police', 'sparkx_ruin_industrial',
                                 'sparkx_ruin_firestation']):
        e = dict(ctx.cat[str(name)])
        e['_name'] = str(name)
        if name == 'sparkx_ruin_firestation':
            e['scale'] = 0.8
        for yaw in rng.permutation([0.0, math.pi / 2, math.pi, -math.pi / 2]):
            pose = (cx, cy, 0.0, 0.0, 0.0, float(yaw))
            rows = ruin_collisions(ctx.models_dir, e, pose)
            r = np.array(rows)
            if (r[:, 0] - r[:, 3] / 2).min() < x0 - 0.3 or (r[:, 0] + r[:, 3] / 2).max() > x1 + 0.3 or \
               (r[:, 1] - r[:, 4] / 2).min() < y0 - 0.3 or (r[:, 1] + r[:, 4] / 2).max() > y1 + 0.3:
                continue
            uid = scene.uid('ruin')
            s = e.get('scale', 1.0)
            if s != ctx.cat[str(name)].get('scale', 1.0):
                sdf = (f'<model name="{uid}"><static>true</static><pose>{cx} {cy} 0 0 0 {yaw}</pose><link name="link">'
                       f'<visual name="visual"><geometry><mesh><uri>model://{name}/{e["mesh"]}</uri><scale>{s} {s} {s}'
                       f'</scale></mesh></geometry></visual></link></model>')
            else:
                sdf = include(f'model://{name}', uid, pose)
            scene.models.append(sdf)
            rg = scene.group(f'{uid}_collision')
            for row in rows:
                rg.box(row[:3], row[3:6], None, tag='ruin')
                scene.placer.mark_box(row)
            scene.models.append(emitter(f'{uid}_dust', (cx, cy, 3.0), 'dust', 4.0))
            # slots along the footprint boundary (people trapped at the edge of the collapse)
            occ = r
            for _ in range(40):
                k = int(rng.integers(0, len(occ)))
                rx, ry = occ[k, 0], occ[k, 1]
                a = math.atan2(ry - cy, rx - cx)
                px, py = rx + math.cos(a) * (occ[k, 3] / 2 + 1.0), ry + math.sin(a) * (occ[k, 4] / 2 + 1.0)
                if x0 + 1 < px < x1 - 1 and y0 + 1 < py < y1 - 1 and scene.placer.point_free(px, py, 0.8):
                    add_slots(scene, 'rubble', [(px, py, a + math.pi)], 'rubble', near='ruin')
            scatter(scene, ctx, blk['rect'], ['rubble', 'rock', 'rock'], int(rng.integers(2, 5)), margin=1.2)
            return uid
    return build_yard(scene, ctx, blk)


def build_plaza(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('sidewalk').add_rect_xy(x0, y0, x1, y1, z=0.008, tile=6.0)
    cx, cy = (x0 + x1) / 2 + float(rng.uniform(-3, 3)), (y0 + y1) / 2 + float(rng.uniform(-3, 3))
    f = place_landmark(scene, ctx, 'fountain', cx, cy, 0.0)
    if f:
        near_slots(scene, rng, cx, cy, 3.3, 4.5, 1, 'open_area', kind='open', near='fountain')
    for _ in range(4):  # lamp posts and benches
        px, py = random_point(rng, blk['rect'], 1.5)
        row = [px, py, 2.0, 0.18, 0.18, 4.0, 0, 0, 0]
        if _try(scene, row, 0.8):
            g.box(row[:3], (0.22, 0.22, 4.0), None, tag='post')
            lean = float(rng.uniform(0.03, 0.16)) if rng.random() < 0.4 else 0.0
            kit.place(g, 'street_lamp', (px, py, 0.0), rpy=(lean, 0.0, float(rng.uniform(0, 6.28))))
            scene.placer.mark_box(row)
        yaw = float(rng.choice([0, math.pi / 2]))
        px, py = random_point(rng, blk['rect'], 1.5)
        row = [px, py, 0.23, 1.8, 0.5, 0.45, 0, 0, yaw]
        if _try(scene, row, 0.6):
            g.box(row[:3], row[3:6], None, rpy=(0, 0, yaw), tag='bench')
            kit.place(g, 'bench', (px, py, 0.0), yaw)
            scene.placer.mark_box(row)
    placed = scatter(scene, ctx, blk['rect'], ['tent', 'tent', 'tent', 'water_tank', 'rubble', 'car'],
                     int(rng.integers(3, 5)), margin=2.5)
    for kind, px, py, yaw, rec in placed:
        near_slots(scene, rng, px, py, 2.6, 4.0, 1, 'open_area', kind='open', near=kind)


def build_yard(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('concrete').add_rect_xy(x0, y0, x1, y1, z=0.006, tile=5.0)
    # small shed (single room) - good 'inside' hint target
    sx, sy = float(rng.uniform(5.5, 7.0)), float(rng.uniform(5.0, 6.0))
    corner = int(rng.integers(0, 4))
    bx0 = x0 + 1.5 if corner in (0, 3) else x1 - 1.5 - sx
    by0 = y0 + 1.5 if corner in (0, 1) else y1 - 1.5 - sy
    b = make_building(rng, g, scene.placer, len(scene.buildings), (bx0, by0, bx0 + sx, by0 + sy), 'NSEW',
                      blk['damage'], str(rng.choice(['brick_grey', 'concrete', 'plaster'])), height=3.0)
    scene.buildings.append(b)
    room_slots(scene, rng, b, per_room=1)
    placed = scatter(scene, ctx, blk['rect'], ['container', 'container', 'container', 'water_tank', 'car', 'dumpster',
                                               'rubble'], int(rng.integers(4, 7)), margin=2.0)
    for kind, px, py, yaw, rec in placed:
        if kind in ('container', 'water_tank', 'car'):
            near_slots(scene, rng, px, py, 2.4, 4.0, 1, 'open_area', kind='yard', near=kind)


def build_crater(scene, ctx, blk):
    rng = ctx.rng
    x0, y0, x1, y1 = blk['rect']
    g = scene.group(blk['name'])
    g.mesh('scorched').add_rect_xy(x0, y0, x1, y1, z=0.006, tile=5.0)
    cx, cy = (x0 + x1) / 2 + float(rng.uniform(-1.5, 1.5)), (y0 + y1) / 2 + float(rng.uniform(-1.5, 1.5))
    R = float(rng.uniform(5.5, 7.0))
    g.mesh('scorched').add_heightfield_ring((cx, cy), [0.0, 0.5 * R], [0.02, 0.05], segments=36)
    g.mesh('rubble').add_heightfield_ring((cx, cy), [0.5 * R, 0.75 * R, R, 1.3 * R], [0.05, 0.9, 1.2, 0.03],
                                          segments=36, jitter=0.06, rng=rng)
    n = 18
    for k in range(n):
        a = 2 * math.pi * k / n
        rr = 0.88 * R
        L = 2 * math.pi * rr / n * 1.25
        row = [cx + rr * math.cos(a), cy + rr * math.sin(a), 0.5, L, 0.35 * R, 1.0, 0, 0, a + math.pi / 2]
        g.box(row[:3], row[3:6], None, rpy=row[6:9], tag='crater')
        scene.placer.mark_box(row)
    scene.placer.reserve_rect(cx - R, cy - R, cx + R, cy + R)
    prof_r, prof_h = [0.5 * R, 0.75 * R, R, 1.3 * R], [0.05, 0.9, 1.2, 0.03]
    for k in range(90):                                            # ejecta piled on the rim (inside its collision ring)
        a = float(rng.uniform(0, 2 * math.pi))
        rr = R * float(rng.uniform(0.62, 1.08))
        sz = (float(rng.uniform(0.4, 1.5)), float(rng.uniform(0.35, 1.1)), float(rng.uniform(0.2, 0.7)))
        z = float(np.interp(rr, prof_r, prof_h)) + sz[2] * 0.2
        row = [cx + rr * math.cos(a), cy + rr * math.sin(a), z, *sz, float(rng.uniform(-0.5, 0.5)), float(rng.uniform(-0.5, 0.5)),
               float(rng.uniform(-3.1, 3.1))]
        props.rubble_chunk(g, rng, row, str(rng.choice(['rubble', 'concrete', 'concrete_dark', 'brick', 'scorched'])))
    g.mesh('scorched').add_blob((cx, cy), 1.75 * R, rng, z=0.012, n=28, jitter=0.12)
    for k in range(int(rng.integers(5, 9))):
        a = rng.uniform(0, 2 * math.pi)
        props.rock(scene, ctx.cat, cx + 1.05 * R * math.cos(a), cy + 1.05 * R * math.sin(a),
                   float(rng.uniform(0.9, 2.2)), check=False)
    scene.add_landmark('crater', '', cx, cy, 0.0, 0.0, (2.6 * R, 2.6 * R, 1.2), model=blk['name'],
                       footprint=[cx, cy, 0.6, 2 * R, 2 * R, 1.2, 0, 0, 0])
    scene.models.append(emitter(scene.uid('crater_smoke'), (cx, cy, 0.5), 'smoke', 3.0, scatter=0.15))
    scene.epicenter = (cx, cy, R)
    # wall remnants in two corners
    for corner in rng.permutation(4)[:2]:
        wx = x0 + 2.0 if corner in (0, 3) else x1 - 2.0
        wy = y0 + 2.0 if corner in (0, 1) else y1 - 2.0
        sx = 1 if corner in (0, 3) else -1
        sy = 1 if corner in (0, 1) else -1
        mat = str(rng.choice(FACADES))
        la, lb = float(rng.uniform(4, 7)), float(rng.uniform(3, 6))
        h = float(rng.uniform(1.6, 3.2))
        xa, xb = sorted((wx, wx + sx * la))
        ya, yb = sorted((wy, wy + sy * lb))
        emit_wall(g, 'x', wy, xa, xb, 0.3, h, [], mat, tag='wall')
        emit_wall(g, 'y', wx, ya, yb, 0.3, h * 0.8, [], mat, tag='wall')
        for row in g.collisions[-2:]:
            scene.placer.mark_box(row)
        add_slots(scene, 'rubble', [(wx + sx * 1.2, wy + sy * 1.2, 0.0)], 'rubble', near='wall')
    placed = scatter(scene, ctx, blk['rect'], ['rubble', 'rock'], int(rng.integers(3, 5)), margin=1.5)
    for kind, px, py, yaw, rec in placed:
        near_slots(scene, rng, px, py, 1.8, 3.0, 1, 'rubble', kind='rubble', near=kind)
    for k in range(int(rng.integers(2, 4))):
        a = rng.uniform(0, 2 * math.pi)
        rr = R * float(rng.uniform(1.5, 1.9))
        props.burnt_car(scene, ctx.cat, cx + rr * math.cos(a), cy + rr * math.sin(a), float(a + math.pi / 2))
    for k in range(int(rng.integers(2, 4))):
        a = rng.uniform(0, 2 * math.pi)
        rr = R * float(rng.uniform(1.35, 1.6))
        px, py = cx + rr * math.cos(a), cy + rr * math.sin(a)
        if scene.placer.point_free(px, py, 1.0):
            props.fire(scene, px, py, float(rng.uniform(0.8, 1.4)))
