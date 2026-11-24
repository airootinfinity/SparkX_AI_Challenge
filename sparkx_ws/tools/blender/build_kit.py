"""SparkX world kit: detailed parts the city generator places and bakes into each world.

  blender -b --python build_kit.py [-- --render DIR]

Writes sparkx_worlds/models/sparkx_kit/<asset>.obj (+ kit.yaml). Each OBJ is split by `usemtl`
into material ROLES ("body", "frame", "glass" ...); the generator maps roles to its scanned PBR
materials and re-projects UVs at true scale, so one part can be painted any colour. Parts are in
metres, +Z up, origin at the centre of the footprint on the ground unless noted.

Rule for anything without its own collision shape: stay inside the collision box of the object
it dresses (or above 1.2 m), so the robot's LiDAR never sees an obstacle that is not really there.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import sparkx_bpy as sb  # noqa: E402

OUT = os.path.join(sb.SRC, 'sparkx_worlds', 'models', 'sparkx_kit')
PI = math.pi

PREVIEW = {  # role -> preview colour (roles are re-mapped to scanned materials by the generator)
    'body': (0.62, 0.16, 0.12), 'frame': (0.25, 0.25, 0.27), 'steel': (0.45, 0.46, 0.48), 'dark': (0.08, 0.08, 0.09),
    'glass': (0.05, 0.07, 0.09), 'wood': (0.42, 0.3, 0.2), 'canvas': (0.85, 0.84, 0.8), 'stone': (0.6, 0.59, 0.56),
    'stone_dark': (0.4, 0.4, 0.4), 'concrete': (0.58, 0.57, 0.55), 'rebar': (0.35, 0.2, 0.12), 'rust': (0.4, 0.22, 0.12),
    'charred': (0.06, 0.05, 0.05), 'white': (0.9, 0.9, 0.88), 'lamp': (0.95, 0.95, 0.85), 'rubber': (0.04, 0.04, 0.04),
    'crimson': sb.CRIMSON, 'ink': sb.INK, 'offwhite': sb.OFFWHITE, 'yellow': (0.9, 0.72, 0.08), 'plastic': (0.2, 0.3, 0.5),
    'cardboard': (0.62, 0.48, 0.32),
}


def R(role):
    return sb.mat(role, PREVIEW[role], rough=0.15 if role == 'glass' else 0.7,
                  metal=0.8 if role in ('steel', 'frame', 'rebar') else 0.0)


def rnd(seed):
    return random.Random(seed)


def strip_wall(name, pts, z0, z1, role, flip=False):
    """Vertical ribbon through a 2D polyline (corrugated sheet)."""
    bm = bmesh.new()
    lo = [bm.verts.new((x, y, z0)) for x, y in pts]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts]
    for i in range(len(pts) - 1):
        f = (lo[i], lo[i + 1], hi[i + 1], hi[i])
        bm.faces.new(f[::-1] if flip else f)
    return sb._new_object(name, bm, R(role))


def corrugation(a, b, depth, pitch):
    """Trapezoid wave along one axis: list of (t, offset)."""
    out, t, k = [], a, 0
    q = pitch / 4
    while t < b - 1e-6:
        d = depth if (k // 2) % 2 == 0 else 0.0
        out.append((t, d if k % 2 == 0 else (depth if ((k + 1) // 2) % 2 == 0 else 0.0)))
        t += q
        k += 1
    pts, t, up = [], a, False
    while t < b - 1e-6:
        pts += [(t, depth if up else 0.0), (min(t + pitch * 0.32, b), depth if up else 0.0)]
        t += pitch / 2
        up = not up
    pts.append((b, pts[-1][1]))
    return pts


# ======================================================================================= landmarks
def container():
    """ISO 20 ft shipping container, 6.06 x 2.44 x 2.59 m, doors at +X."""
    L, W, H = 6.06, 2.44, 2.59
    o = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            o.append(sb.box('post', (0.16, 0.16, H), (sx * (L / 2 - 0.08), sy * (W / 2 - 0.08), H / 2), R('body'), bev=0.01))
            for z in (0.059, H - 0.059):
                o.append(sb.box('casting', (0.18, 0.165, 0.118), (sx * (L / 2 - 0.09), sy * (W / 2 - 0.0825), z), R('frame'),
                                bev=0.008))
    for sy in (-1, 1):
        for z in (0.07, H - 0.06):
            o.append(sb.box('rail', (L - 0.3, 0.1, 0.12), (0, sy * (W / 2 - 0.05), z), R('body'), bev=0.008))
        wave = corrugation(-L / 2 + 0.16, L / 2 - 0.16, 0.036, 0.278)
        o.append(strip_wall('side', [(t, sy * (W / 2 - 0.045 - d)) for t, d in wave], 0.13, H - 0.12, 'body', flip=sy > 0))
    for sx in (-1, 1):
        for z in (0.07, H - 0.06):
            o.append(sb.box('rail_end', (0.1, W - 0.3, 0.12), (sx * (L / 2 - 0.05), 0, z), R('body'), bev=0.008))
    wave = corrugation(-W / 2 + 0.16, W / 2 - 0.16, 0.036, 0.278)
    o.append(strip_wall('end', [(-L / 2 + 0.045 + d, t) for t, d in wave], 0.13, H - 0.12, 'body', flip=True))
    o.append(sb.box('roof', (L - 0.2, W - 0.2, 0.03), (0, 0, H - 0.03), R('body')))
    for k in range(9):                                            # roof bows
        o.append(sb.box('bow', (0.09, W - 0.24, 0.02), (-L / 2 + 0.5 + k * 0.63, 0, H - 0.006), R('body'), bev=0.006))
    o.append(sb.box('floor', (L - 0.2, W - 0.2, 0.05), (0, 0, 0.15), R('dark')))
    for sy in (-1, 1):                                            # doors + locking gear
        o.append(sb.box('door', (0.04, W / 2 - 0.1, H - 0.28), (L / 2 - 0.04, sy * (W / 4 - 0.025), H / 2), R('body'),
                        bev=0.006))
        for k in (0.22, 0.78):
            y = sy * (W / 2 - 0.1) * k + (0 if k < 0.5 else 0)
            y = sy * (0.14 + (W / 2 - 0.3) * (k - 0.22) / 0.56)
            o.append(sb.cyl('bar', 0.017, H - 0.2, (L / 2 - 0.005, y, H / 2), R('steel'), verts=10))
            o.append(sb.box('handle', (0.03, 0.22, 0.03), (L / 2 + 0.005, y + sy * 0.08, 1.15), R('steel'), bev=0.005))
            for z in (0.18, H - 0.18):
                o.append(sb.box('keeper', (0.04, 0.07, 0.05), (L / 2 - 0.005, y, z), R('frame')))
        for z in (0.35, H / 2, H - 0.35):
            o.append(sb.box('hinge', (0.05, 0.03, 0.12), (L / 2 - 0.03, sy * (W / 2 - 0.02), z), R('frame')))
    return o


def water_tank():
    """Elevated steel tank: 2.6 m dia, platform at 2.6 m, top ~5.2 m. Legs at +-0.95 m."""
    o = []
    leg_h, r, th = 2.6, 1.3, 2.2
    for sx in (-1, 1):
        for sy in (-1, 1):
            o.append(sb.box('leg', (0.14, 0.14, leg_h), (sx * 0.95, sy * 0.95, leg_h / 2), R('steel'), bev=0.008))
            o.append(sb.box('foot', (0.34, 0.34, 0.05), (sx * 0.95, sy * 0.95, 0.025), R('frame')))
    for (ax, s) in (('x', -1), ('x', 1), ('y', -1), ('y', 1)):   # ring beams + X braces, all above 1.25 m
        for z in (1.32, leg_h - 0.05):
            size = (1.9, 0.07, 0.09) if ax == 'x' else (0.07, 1.9, 0.09)
            loc = (0, s * 0.95, z) if ax == 'x' else (s * 0.95, 0, z)
            o.append(sb.box('ring', size, loc, R('steel')))
        for d in (-1, 1):
            ang = d * math.atan2(leg_h - 0.1 - 1.36, 1.9)
            ln = math.hypot(1.9, leg_h - 0.1 - 1.36)
            if ax == 'x':
                o.append(sb.box('brace', (ln, 0.012, 0.06), (0, s * 0.95, (1.36 + leg_h - 0.1) / 2), R('steel'), rot=(0, ang, 0)))
            else:
                o.append(sb.box('brace', (0.012, ln, 0.06), (s * 0.95, 0, (1.36 + leg_h - 0.1) / 2), R('steel'), rot=(ang, 0, 0)))
    o.append(sb.box('deck', (2.3, 2.3, 0.1), (0, 0, leg_h + 0.05), R('steel'), bev=0.01))
    z0 = leg_h + 0.1
    prof = [(0.0, z0), (r, z0)]
    for k in range(5):                                            # rolled stiffening ribs
        zz = z0 + th * (k + 0.5) / 5
        prof += [(r, zz - 0.05), (r + 0.03, zz - 0.02), (r + 0.03, zz + 0.02), (r, zz + 0.05)]
    prof += [(r, z0 + th), (r + 0.04, z0 + th + 0.02), (0.32, z0 + th + 0.42), (0.32, z0 + th + 0.5), (0.0, z0 + th + 0.5)]
    o.append(sb.lathe('tank', prof, R('body'), segments=36, axis='z'))
    o.append(sb.cyl('pipe', 0.06, z0, (0, 0, z0 / 2), R('steel'), verts=14))            # outlet (has a collision box)
    o.append(sb.cyl('valve', 0.11, 0.06, (0, 0, 0.9), R('crimson'), verts=14, axis='x'))
    o.append(sb.box('pipe_base', (0.3, 0.3, 0.08), (0, 0, 0.04), R('frame')))
    for sy in (-1, 1):                                            # ladder from 1.3 m up to the hatch
        o.append(sb.cyl('ladder_rail', 0.02, z0 + th - 1.3, (r + 0.09, sy * 0.21, (1.3 + z0 + th) / 2), R('steel'), verts=8))
    for k in range(int((z0 + th - 1.4) / 0.3)):
        o.append(sb.cyl('rung', 0.012, 0.42, (r + 0.09, 0, 1.45 + 0.3 * k), R('steel'), axis='y', verts=6))
    return o


def tent():
    """Relief tent 3.6 x 3.6 m, eaves 1.8 m, peak 2.9 m. Closed (its collision is a solid box)."""
    o = []
    s, hw, hp = 3.6, 1.8, 2.9
    h = s / 2
    rg = rnd(4)
    bm = bmesh.new()
    n = 8

    def wall(p0, p1, normal):
        grid = []
        for j in range(n + 1):
            row = []
            for i in range(n + 1):
                u, v = i / n, j / n
                x = p0[0] + (p1[0] - p0[0]) * u
                y = p0[1] + (p1[1] - p0[1]) * u
                bulge = 0.07 * math.sin(math.pi * u) * math.sin(math.pi * v) + 0.012 * math.sin(u * 9 + v * 5 + rg.random())
                row.append(bm.verts.new((x + normal[0] * bulge, y + normal[1] * bulge, hw * v)))
            grid.append(row)
        for j in range(n):
            for i in range(n):
                bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
    wall((-h, -h), (h, -h), (0, -1))
    wall((h, -h), (h, h), (1, 0))
    wall((h, h), (-h, h), (0, 1))
    wall((-h, h), (-h, -h), (-1, 0))
    e = h + 0.14                                                   # roof with overhang and sag
    corners = [(-e, -e), (e, -e), (e, e), (-e, e)]
    apex = bm.verts.new((0, 0, hp))
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        prev = None
        for j in range(n + 1):
            t = j / n
            row = []
            for i in range(n + 1):
                u = i / n
                bx, by = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
                x, y = bx * (1 - t), by * (1 - t)
                sag = 0.09 * math.sin(math.pi * u) * math.sin(math.pi * t)
                row.append(apex if j == n else bm.verts.new((x, y, hw - 0.04 + (hp - hw + 0.04) * t - sag)))
            if prev:
                for i in range(n):
                    vs = [prev[i], prev[i + 1], row[i + 1], row[i]]
                    vs = [v for k2, v in enumerate(vs) if v not in vs[:k2]]
                    if len(vs) >= 3:
                        bm.faces.new(vs)
            prev = row
        for i in range(n):                                         # scalloped valance under the eaves
            u0, u1 = i / n, (i + 1) / n
            p0 = (a[0] + (b[0] - a[0]) * u0, a[1] + (b[1] - a[1]) * u0)
            p1 = (a[0] + (b[0] - a[0]) * u1, a[1] + (b[1] - a[1]) * u1)
            pm = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            v = [bm.verts.new((p0[0], p0[1], hw - 0.04)), bm.verts.new((p1[0], p1[1], hw - 0.04)),
                 bm.verts.new((p1[0], p1[1], hw - 0.22)), bm.verts.new((pm[0], pm[1], hw - 0.3)),
                 bm.verts.new((p0[0], p0[1], hw - 0.22))]
            bm.faces.new(v)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    canvas = sb._new_object('canvas', bm, R('canvas'))
    sol = canvas.modifiers.new('sol', 'SOLIDIFY')                  # visible from both sides
    sol.thickness = 0.012
    o.append(canvas)
    for sx in (-1, 1):
        for sy in (-1, 1):
            o.append(sb.cyl('pole', 0.03, hw + 0.02, (sx * (h - 0.03), sy * (h - 0.03), (hw + 0.02) / 2), R('steel'), verts=8))
            o.append(sb.box('sandbag', (0.5, 0.28, 0.14), (sx * (h - 0.3), sy * (h - 0.16), 0.07), R('canvas'), bev=0.05, seg=2,
                            rot=(0, 0, rg.uniform(-0.3, 0.3))))
    o.append(sb.cyl('finial', 0.035, 0.22, (0, 0, hp + 0.06), R('steel'), verts=8, r2=0.008))
    # zipped door on the +X wall
    o.append(sb.box('zip', (0.012, 0.03, 1.55), (h + 0.075, 0, 0.8), R('dark')))
    for sy in (-1, 1):
        o.append(sb.box('door_tie', (0.03, 0.03, 0.16), (h + 0.08, sy * 0.5, 1.5), R('dark')))
    return o


def fountain():
    """Dry stone fountain: 4.6 m basin, column, upper bowl."""
    o = []
    basin = [(0.0, 0.0), (2.3, 0.0), (2.3, 0.08), (2.36, 0.12), (2.36, 0.5), (2.28, 0.6), (2.02, 0.6), (1.98, 0.52),
             (1.98, 0.16), (0.0, 0.16)]
    o.append(sb.lathe('basin', basin, R('stone'), segments=40, axis='z'))
    col = [(0.0, 0.16), (0.5, 0.16), (0.5, 0.3), (0.34, 0.36), (0.28, 0.9), (0.3, 1.3), (0.36, 1.36), (0.3, 1.42), (0.0, 1.42)]
    o.append(sb.lathe('column', col, R('stone_dark'), segments=20, axis='z'))
    bowl = [(0.0, 1.42), (0.3, 1.42), (0.86, 1.6), (1.02, 1.72), (1.02, 1.78), (0.92, 1.78), (0.8, 1.68), (0.3, 1.56), (0.0, 1.56)]
    o.append(sb.lathe('bowl', bowl, R('stone'), segments=28, axis='z'))
    top = [(0.0, 1.56), (0.14, 1.56), (0.1, 1.8), (0.16, 1.86), (0.0, 1.92)]
    o.append(sb.lathe('finial', top, R('stone_dark'), segments=12, axis='z'))
    rg = rnd(8)
    for k in range(7):                                             # debris that fell into the dry basin
        a, rr = rg.uniform(0, 2 * PI), rg.uniform(0.7, 1.7)
        o.append(sb.box('debris', (rg.uniform(0.15, 0.4), rg.uniform(0.12, 0.3), rg.uniform(0.06, 0.16)),
                        (rr * math.cos(a), rr * math.sin(a), 0.22), R('concrete'), bev=0.02,
                        rot=(rg.uniform(-0.3, 0.3), rg.uniform(-0.3, 0.3), rg.uniform(0, PI))))
    return o


# ======================================================================================= rubble
def chunk(seed, flat=False):
    """Broken concrete block fitted to a 1 x 1 x 1 box centred on the origin (scaled by the generator)."""
    rg = rnd(seed)
    bm = bmesh.new()
    pts = []
    for _ in range(16):
        p = Vector((rg.uniform(-1, 1), rg.uniform(-1, 1), rg.uniform(-1, 1)))
        if flat:
            p.z = math.copysign(1.0, p.z) if rg.random() < 0.8 else p.z
        else:
            ax = rg.randrange(3)
            if rg.random() < 0.55:
                p[ax] = math.copysign(1.0, p[ax])
        pts.append(bm.verts.new(p * 0.5))
    bmesh.ops.convex_hull(bm, input=pts)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
    for v in bm.verts:                                             # fill the unit box exactly
        v.co = Vector([(v.co[i] - lo[i]) / max(hi[i] - lo[i], 1e-6) - 0.5 for i in range(3)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = sb._new_object('chunk', bm, R('concrete'))
    sb.bevel(ob, 0.035, 1)
    o = [ob]
    if flat or rg.random() < 0.5:                                  # torn reinforcement bars
        for _ in range(rg.randint(2, 4)):
            side = rg.choice([-1, 1])
            y, z = rg.uniform(-0.35, 0.35), rg.uniform(-0.25, 0.25)
            path = [(side * 0.3, y, z), (side * 0.52, y + rg.uniform(-0.03, 0.03), z + rg.uniform(-0.02, 0.05)),
                    (side * rg.uniform(0.62, 0.8), y + rg.uniform(-0.12, 0.12), z + rg.uniform(-0.05, 0.2))]
            o.append(sb.tube('rebar', path, 0.012, R('rebar'), verts=6))
    return o


def brick_heap(seed):
    """Loose bricks dumped in a heap, inside a 1 x 1 x 1 box centred on the origin."""
    rg = rnd(seed)
    o = []
    for _ in range(14):
        r, a = 0.42 * math.sqrt(rg.random()), rg.uniform(0, 2 * PI)
        z = -0.5 + 0.08 + (0.75 * (1 - r / 0.45)) * rg.random()
        o.append(sb.box('brick', (0.26, 0.13, 0.085), (r * math.cos(a), r * math.sin(a), z), R('body'),
                        rot=(rg.uniform(-0.5, 0.5), rg.uniform(-0.5, 0.5), rg.uniform(0, PI))))
    return o


def fire_debris():
    """Charred beams and embers for a burning pile; fits a 1 x 1 x 1 box sitting on the ground."""
    rg = rnd(31)
    o = []
    for k in range(9):
        a = rg.uniform(0, PI)
        ln = rg.uniform(0.5, 0.95)
        o.append(sb.box('beam', (ln, rg.uniform(0.07, 0.12), rg.uniform(0.07, 0.12)),
                        (rg.uniform(-0.12, 0.12), rg.uniform(-0.12, 0.12), 0.12 + 0.07 * k),
                        R('charred'), bev=0.012, seg=1, rot=(rg.uniform(-0.2, 0.2), rg.uniform(-0.45, 0.45), a)))
    for k in range(10):
        r, a = rg.uniform(0.2, 0.46), rg.uniform(0, 2 * PI)
        o.append(sb.box('coal', (rg.uniform(0.06, 0.16), rg.uniform(0.06, 0.14), rg.uniform(0.04, 0.09)),
                        (r * math.cos(a), r * math.sin(a), 0.04), R('charred'), bev=0.015, seg=1, rot=(0, 0, a)))
    return o


# ======================================================================================= buildings
def window(kind):
    """Window set into a 1.3 x 1.1 m opening of a 0.30 m wall. Origin: opening centre, +Y = outside."""
    w, h, t = 1.3, 1.1, 0.30
    o = []
    rg = rnd(hash(kind) % 1000)
    fr = 0.06
    for sx in (-1, 1):
        o.append(sb.box('jamb', (fr, 0.12, h), (sx * (w / 2 - fr / 2), t / 2 - 0.09, 0), R('frame'), bev=0.006))
    for sz in (-1, 1):
        o.append(sb.box('head', (w, 0.12, fr), (0, t / 2 - 0.09, sz * (h / 2 - fr / 2)), R('frame'), bev=0.006))
    o.append(sb.box('sill', (w + 0.24, 0.2, 0.05), (0, t / 2 + 0.03, -h / 2 - 0.025), R('stone'), bev=0.008))
    o.append(sb.box('lintel', (w + 0.3, 0.06, 0.16), (0, t / 2 + 0.012, h / 2 + 0.08), R('stone'), bev=0.008))
    o.append(sb.box('inner_sill', (w, 0.1, 0.03), (0, -t / 2 + 0.03, -h / 2 + 0.015), R('wood')))
    if kind != 'empty':
        o.append(sb.box('mullion', (0.04, 0.05, h - 2 * fr), (0, t / 2 - 0.09, 0), R('frame')))
    if kind in ('broken', 'bars'):
        o.append(sb.box('transom', (w - 2 * fr, 0.05, 0.04), (0, t / 2 - 0.09, 0.12), R('frame')))
        y = t / 2 - 0.09
        for sx in (-1, 1):                                         # jagged glass left in the frame
            x0, x1 = (sx * (w / 2 - fr), sx * 0.02)
            for k in range(5):
                za = -h / 2 + fr + (h - 2 * fr) * k / 5
                zb = za + (h - 2 * fr) / 5
                tip = x0 + (x1 - x0) * rg.uniform(0.15, 0.6)
                o.append(sb.flat_tris('shard', [[(x0, za), (x0, zb), (tip, (za + zb) / 2 + rg.uniform(-0.05, 0.05))]],
                                      (0, y, 0), (1, 0, 0), (0, 0, 1), R('glass'), flip=sx > 0))
            for k in range(3):
                xa = x0 + (x1 - x0) * k / 3
                xb = x0 + (x1 - x0) * (k + 1) / 3
                o.append(sb.flat_tris('shard', [[(xa, -h / 2 + fr), (xb, -h / 2 + fr),
                                                 ((xa + xb) / 2, -h / 2 + fr + rg.uniform(0.06, 0.3))]],
                                      (0, y, 0), (1, 0, 0), (0, 0, 1), R('glass'), flip=sx < 0))
    if kind == 'intact':
        o.append(sb.box('pane', (w - 2 * fr, 0.008, h - 2 * fr), (0, t / 2 - 0.09, 0), R('glass')))
    if kind == 'boarded':
        for k in range(4):
            o.append(sb.box('board', (w + 0.1, 0.025, 0.17), (rg.uniform(-0.03, 0.03), t / 2 - 0.015, -0.36 + 0.24 * k),
                            R('wood'), bev=0.004, seg=1, rot=(0, rg.uniform(-0.09, 0.09), 0)))
    if kind == 'bars':
        for k in range(6):
            x = -w / 2 + fr + (w - 2 * fr) * (k + 0.5) / 6
            bend = rg.uniform(-0.05, 0.05) if k in (2, 3) else 0.0
            o.append(sb.tube('bar', [(x, t / 2 - 0.02, -h / 2 + fr), (x + bend, t / 2 - 0.02 + abs(bend), 0),
                                     (x, t / 2 - 0.02, h / 2 - fr)], 0.009, R('dark'), verts=6))
    if kind == 'shutter':
        for sx in (-1, 1):                                         # louvred shutters folded back on the wall
            o.append(sb.box('shutter', (w / 2 - 0.02, 0.03, h), (sx * (w * 0.75 + 0.02), t / 2 + 0.02, 0), R('wood'),
                            bev=0.004, rot=(0, rg.uniform(-0.06, 0.06) if sx > 0 else 0, 0)))
            for k in range(8):
                o.append(sb.box('louvre', (w / 2 - 0.1, 0.012, 0.02), (sx * (w * 0.75 + 0.02), t / 2 + 0.04, -h / 2 + 0.1 + k * 0.125),
                                R('wood')))
    return o


def door(width, kind):
    """Door set for an opening `width` x 2.3 m in a wall of thickness t. Origin: opening centre on
    the ground, +Y = outside. Leaves are folded flat against the outside wall or missing."""
    t = 0.30 if kind != 'interior' else 0.15
    h = 2.3
    o = []
    rg = rnd(int(width * 100) + len(kind))
    fr = 0.07
    for sx in (-1, 1):
        o.append(sb.box('jamb', (fr, t + 0.04, h), (sx * (width / 2 - fr / 2 + 0.005), 0, h / 2), R('frame'), bev=0.008))
    o.append(sb.box('head', (width + 0.02, t + 0.04, fr), (0, 0, h - fr / 2 + 0.005), R('frame'), bev=0.008))
    if kind == 'interior':
        return o
    o.append(sb.box('lintel', (width + 0.5, 0.07, 0.22), (0, t / 2 + 0.02, h + 0.14), R('stone'), bev=0.01))
    o.append(sb.box('step', (width + 0.3, 0.32, 0.03), (0, t / 2 + 0.14, 0.015), R('stone'), bev=0.008))
    lw = width / 2 - fr
    if kind in ('double', 'one_leaf'):
        sides = (-1, 1) if kind == 'double' else (1,)
        for sx in sides:                                           # leaf swung 180 degrees, lying on the facade
            sag = rg.uniform(-0.035, 0.0)
            leaf = sb.box('leaf', (lw, 0.045, h - 0.1), (sx * (width / 2 + lw / 2 + 0.02), t / 2 + 0.035, h / 2 + 0.01), R('wood'),
                          bev=0.006, rot=(0, sag * sx * 1.5, 0))
            o.append(leaf)
            o.append(sb.box('panel', (lw - 0.24, 0.012, 0.7), (sx * (width / 2 + lw / 2 + 0.02), t / 2 + 0.062, 0.6), R('wood')))
            o.append(sb.box('glazing', (lw - 0.24, 0.012, 0.8), (sx * (width / 2 + lw / 2 + 0.02), t / 2 + 0.062, 1.62), R('glass')))
            o.append(sb.cyl('knob', 0.03, 0.05, (sx * (width / 2 + lw - 0.05), t / 2 + 0.08, 1.05), R('steel'), axis='y', verts=10))
    return o


def awning(color_role='canvas'):
    """Torn shop awning over a 2.4 m entrance. Origin: wall face above the door (z = bottom edge)."""
    o = []
    w, d, drop = 3.0, 1.1, 0.5
    bm = bmesh.new()
    n = 10
    rg = rnd(12)
    rows = []
    for j in range(5):
        v = j / 4
        row = []
        for i in range(n + 1):
            u = i / n
            sag = 0.06 * math.sin(PI * u) * math.sin(PI * v)
            tear = 0.0 if not (j == 4 and i in (6, 7)) else 0.25
            row.append(bm.verts.new((-w / 2 + w * u, d * v, drop * (1 - v) + 0.0 - sag - tear * 0 + (0.02 * rg.random()))))
        rows.append(row)
    for j in range(4):
        for i in range(n):
            if j == 3 and i in (6,):
                continue                                           # a ripped-out panel
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    for i in range(n):                                             # front valance
        a, b = rows[4][i], rows[4][i + 1]
        if i == 6:
            continue
        c = bm.verts.new((b.co.x, b.co.y + 0.01, b.co.z - 0.2))
        e = bm.verts.new((a.co.x, a.co.y + 0.01, a.co.z - 0.2 - 0.04 * (i % 2)))
        bm.faces.new((a, b, c, e))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    cv = sb._new_object('awning', bm, R(color_role))
    sol = cv.modifiers.new('sol', 'SOLIDIFY')
    sol.thickness = 0.01
    o.append(cv)
    for sx in (-1, 1):
        o.append(sb.tube('arm', [(sx * (w / 2 - 0.05), 0.0, drop), (sx * (w / 2 - 0.05), d, 0.0)], 0.015, R('steel'), verts=6))
        o.append(sb.tube('stay', [(sx * (w / 2 - 0.05), 0.0, 0.0), (sx * (w / 2 - 0.05), d, 0.0)], 0.012, R('steel'), verts=6))
    o.append(sb.tube('front', [(-w / 2 + 0.05, d, 0.0), (w / 2 - 0.05, d, 0.0)], 0.015, R('steel'), verts=6))
    return o


def ac_unit():
    """Wall-mounted air-conditioner condenser (0.8 x 0.3 x 0.55). Origin: wall face, bottom centre."""
    o = [sb.box('case', (0.8, 0.3, 0.55), (0, 0.17, 0.275), R('white'), bev=0.015)]
    o.append(sb.cyl('fan_ring', 0.21, 0.02, (-0.12, 0.325, 0.28), R('dark'), axis='y', verts=20))
    for k in range(6):
        o.append(sb.box('grille', (0.42, 0.006, 0.012), (-0.12, 0.337, 0.12 + k * 0.064), R('steel')))
    for sx in (-1, 1):
        o.append(sb.box('bracket', (0.03, 0.34, 0.03), (sx * 0.3, 0.17, -0.015), R('steel')))
    o.append(sb.tube('hose', [(0.36, 0.1, 0.4), (0.44, 0.02, 0.5), (0.44, 0.02, 1.1)], 0.015, R('dark'), verts=6))
    return o


def rooftop(kind):
    o = []
    if kind == 'tank':                                             # plastic roof tank on a stand
        o.append(sb.lathe('tank', [(0, 0.4), (0.55, 0.4), (0.57, 0.5), (0.57, 1.35), (0.5, 1.5), (0.2, 1.58), (0, 1.58)],
                          R('dark'), segments=20, axis='z'))
        for sx in (-1, 1):
            for sy in (-1, 1):
                o.append(sb.box('leg', (0.06, 0.06, 0.4), (sx * 0.4, sy * 0.4, 0.2), R('steel')))
        o.append(sb.box('stand', (1.0, 1.0, 0.04), (0, 0, 0.4), R('steel')))
    elif kind == 'dish':
        o.append(sb.cyl('mast', 0.025, 1.2, (0, 0, 0.6), R('steel'), verts=8))
        dish = sb.lathe('dish', [(0, 0), (0.25, 0.03), (0.42, 0.12), (0.43, 0.12), (0.25, 0.02), (0, -0.015)], R('white'),
                        segments=20, axis='z')
        o.append(sb.place(dish, (0.08, 0, 1.15), (0, PI / 2 - 0.5, 0)))
        o.append(sb.box('base', (0.4, 0.4, 0.05), (0, 0, 0.025), R('stone')))
    elif kind == 'hvac':
        o.append(sb.box('unit', (1.6, 1.0, 0.8), (0, 0, 0.5), R('steel'), bev=0.02))
        o.append(sb.cyl('fan', 0.34, 0.06, (-0.35, 0, 0.92), R('dark'), verts=20))
        o.append(sb.cyl('fan', 0.34, 0.06, (0.4, 0, 0.92), R('dark'), verts=20))
        for sx in (-1, 1):
            o.append(sb.box('skid', (0.08, 1.0, 0.1), (sx * 0.6, 0, 0.05), R('dark')))
    elif kind == 'antenna':
        o.append(sb.cyl('mast', 0.03, 3.2, (0, 0, 1.6), R('steel'), verts=8))
        for k in range(5):
            o.append(sb.box('element', (0.9 - 0.12 * k, 0.015, 0.015), (0, 0, 2.2 + 0.2 * k), R('steel')))
        o.append(sb.box('base', (0.3, 0.3, 0.05), (0, 0, 0.025), R('stone')))
    return o


def furniture(kind):
    """Office / shop furniture; each fills its collision box (origin: centre of the footprint)."""
    o = []
    rg = rnd(len(kind) * 7)
    if kind == 'table':                                            # 1.4 x 0.8 x 0.75 desk
        o.append(sb.box('top', (1.4, 0.8, 0.04), (0, 0, 0.73), R('wood'), bev=0.008))
        for sx in (-1, 1):
            o.append(sb.box('side', (0.03, 0.74, 0.7), (sx * 0.66, 0, 0.35), R('steel')))
        o.append(sb.box('modesty', (1.3, 0.02, 0.4), (0, 0.33, 0.48), R('steel')))
        o.append(sb.box('drawers', (0.4, 0.6, 0.55), (0.42, -0.02, 0.43), R('steel'), bev=0.006))
        for k in range(3):
            o.append(sb.box('pull', (0.14, 0.02, 0.015), (0.42, -0.33, 0.26 + 0.17 * k), R('dark')))
        o.append(sb.box('monitor', (0.5, 0.05, 0.32), (-0.25, 0.15, 0.95), R('dark'), bev=0.006, rot=(-0.3, 0, 0.5)))
        o.append(sb.box('papers', (0.3, 0.22, 0.02), (0.2, -0.1, 0.76), R('white'), rot=(0, 0, 0.3)))
    elif kind == 'shelf':                                          # 1.6 x 0.45 x 1.8 racking
        for sx in (-1, 1):
            for sy in (-1, 1):
                o.append(sb.box('upright', (0.04, 0.04, 1.8), (sx * 0.78, sy * 0.2, 0.9), R('steel')))
        for k in range(5):
            o.append(sb.box('board', (1.56, 0.42, 0.025), (0, 0, 0.08 + 0.42 * k), R('wood')))
        for k in range(4):
            for j in range(3):
                if rg.random() < 0.75:
                    sz = (rg.uniform(0.3, 0.45), rg.uniform(0.28, 0.38), rg.uniform(0.18, 0.34))
                    o.append(sb.box('carton', sz, (-0.5 + 0.5 * j + rg.uniform(-0.04, 0.04), 0, 0.1 + 0.42 * k + sz[2] / 2),
                                    R('cardboard'), bev=0.006, seg=1, rot=(0, 0, rg.uniform(-0.2, 0.2))))
    elif kind == 'cabinet':                                        # 0.7 x 0.6 x 1.2 filing cabinet
        o.append(sb.box('body', (0.7, 0.6, 1.2), (0, 0, 0.6), R('steel'), bev=0.01))
        for k in range(3):
            o.append(sb.box('front', (0.64, 0.02, 0.34), (0, -0.292 - (0.03 if k == 1 else 0), 0.22 + 0.38 * k), R('steel'), bev=0.005))
            o.append(sb.box('pull', (0.2, 0.025, 0.02), (0, -0.31 - (0.03 if k == 1 else 0), 0.3 + 0.38 * k), R('dark')))
    elif kind == 'crate':                                          # 0.9 x 0.9 x 0.8 slatted crate
        for sx in (-1, 1):
            for sy in (-1, 1):
                o.append(sb.box('corner', (0.07, 0.07, 0.8), (sx * 0.415, sy * 0.415, 0.4), R('wood')))
        for k in range(5):
            z = 0.08 + 0.16 * k
            for sy in (-1, 1):
                o.append(sb.box('slat', (0.9, 0.025, 0.12), (0, sy * 0.437, z), R('wood'), bev=0.004, seg=1))
                o.append(sb.box('slat', (0.025, 0.9, 0.12), (sy * 0.437, 0, z), R('wood'), bev=0.004, seg=1))
        o.append(sb.box('lid', (0.9, 0.9, 0.03), (0.04, 0.02, 0.785), R('wood'), rot=(0, 0, 0.06)))
        o.append(sb.box('fill', (0.8, 0.8, 0.7), (0, 0, 0.36), R('dark')))
    return o


# ======================================================================================= street
def street_lamp():
    """6.5 m street light with a 1.6 m arm toward +X. Collision: 0.22 m square post."""
    o = [sb.box('base', (0.36, 0.36, 0.06), (0, 0, 0.03), R('frame'), bev=0.01)]
    o.append(sb.cyl('skirt', 0.11, 0.9, (0, 0, 0.45), R('frame'), verts=12, r2=0.08))
    o.append(sb.cyl('pole', 0.08, 5.6, (0, 0, 3.7), R('frame'), verts=12, r2=0.055))
    o.append(sb.tube('arm', [(0, 0, 6.3), (0.25, 0, 6.52), (0.9, 0, 6.62), (1.5, 0, 6.6)], 0.045, R('frame'), verts=8))
    o.append(sb.box('head', (0.62, 0.26, 0.11), (1.72, 0, 6.58), R('frame'), bev=0.03))
    o.append(sb.box('lens', (0.46, 0.2, 0.02), (1.72, 0, 6.52), R('lamp')))
    o.append(sb.box('hatch', (0.012, 0.09, 0.22), (0.105, 0, 0.6), R('steel')))
    return o


def utility_pole():
    """8.5 m timber pole with a crossarm (wires attach at +-0.9 m along Y, z = 8.0)."""
    o = [sb.cyl('pole', 0.14, 8.5, (0, 0, 4.25), R('wood'), verts=10, r2=0.1)]
    o.append(sb.box('crossarm', (0.1, 2.1, 0.12), (0, 0, 8.0), R('wood'), bev=0.008))
    for y in (-0.9, -0.3, 0.3, 0.9):
        o.append(sb.cyl('insulator', 0.035, 0.14, (0, y, 8.13), R('white'), verts=8))
    o.append(sb.box('transformer', (0.5, 0.5, 0.75), (0.0, 0.42, 6.6), R('steel'), bev=0.06, seg=2))
    o.append(sb.box('brace', (0.03, 0.9, 0.03), (0, 0.45, 7.6), R('steel'), rot=(0.75, 0, 0)))
    return o


def traffic_sign(kind):
    """Road sign on a 2.6 m post. Collision: 0.12 m square post. Face toward -Y."""
    o = [sb.cyl('post', 0.03, 2.9, (0, 0, 1.45), R('steel'), verts=8)]
    if kind == 'stop':
        o.append(sb.cyl('plate', 0.38, 0.012, (0, -0.04, 2.5), R('crimson'), axis='y', verts=8))
        o.append(sb.cyl('rim', 0.32, 0.014, (0, -0.042, 2.5), R('white'), axis='y', verts=8))
        o.append(sb.cyl('inner', 0.3, 0.016, (0, -0.044, 2.5), R('crimson'), axis='y', verts=8))
    elif kind == 'warning':
        o.append(sb.flat_tris('plate', [[(-0.42, -0.24), (0.42, -0.24), (0.0, 0.49)]], (0, -0.04, 2.45), (1, 0, 0), (0, 0, 1),
                              R('yellow')))
        o.append(sb.flat_tris('plate_back', [[(-0.42, -0.24), (0.42, -0.24), (0.0, 0.49)]], (0, -0.036, 2.45), (1, 0, 0),
                              (0, 0, 1), R('steel'), flip=True))
        o.append(sb.box('mark', (0.05, 0.016, 0.24), (0, -0.05, 2.5), R('dark')))
        o.append(sb.box('dot', (0.05, 0.016, 0.05), (0, -0.05, 2.29), R('dark')))
    else:                                                          # blue arrow / information plate
        o.append(sb.box('plate', (0.6, 0.012, 0.6), (0, -0.04, 2.5), R('plastic'), bev=0.004))
        o.append(sb.box('arrow', (0.34, 0.016, 0.09), (0, -0.05, 2.5), R('white')))
    return o


def bench():
    """1.8 x 0.5 x 0.45 park bench with a back rest."""
    o = []
    for sx in (-1, 1):
        o.append(sb.box('leg', (0.06, 0.46, 0.42), (sx * 0.75, 0, 0.21), R('frame'), bev=0.008))
        o.append(sb.box('back_post', (0.05, 0.05, 0.45), (sx * 0.75, 0.21, 0.66), R('frame')))
    for k in range(4):
        o.append(sb.box('slat', (1.8, 0.095, 0.03), (0, -0.17 + 0.115 * k, 0.435), R('wood'), bev=0.004, seg=1))
    for k in range(2):
        o.append(sb.box('back', (1.8, 0.025, 0.1), (0, 0.235, 0.62 + 0.15 * k), R('wood'), bev=0.004, seg=1))
    return o


def bin_can():
    """Dented street litter bin, 0.5 m dia x 0.9 m."""
    o = [sb.lathe('can', [(0, 0), (0.22, 0), (0.25, 0.05), (0.25, 0.82), (0.27, 0.84), (0.27, 0.9), (0.23, 0.9), (0.23, 0.06),
                          (0, 0.06)], R('steel'), segments=16, axis='z')]
    o.append(sb.cyl('band', 0.256, 0.04, (0, 0, 0.45), R('dark'), verts=16))
    return o


# ======================================================================================= base camp
def floodlight():
    """Portable floodlight tower, 4.2 m, on a 0.9 m square skid. Collision: 0.9 x 0.9 x 1.0 skid."""
    o = [sb.box('skid', (0.9, 0.9, 0.12), (0, 0, 0.1), R('ink'), bev=0.02)]
    o.append(sb.box('genset', (0.7, 0.55, 0.55), (0, 0, 0.44), R('ink'), bev=0.03))
    o.append(sb.box('stripe', (0.705, 0.555, 0.04), (0, 0, 0.6), R('crimson')))
    o.append(sb.box('line', (0.705, 0.555, 0.008), (0, 0, 0.25), R('offwhite')))
    o.append(sb.cyl('mast', 0.045, 3.4, (0, 0, 2.4), R('steel'), verts=10, r2=0.03))
    o.append(sb.box('yoke', (0.06, 1.3, 0.06), (0, 0, 4.1), R('steel')))
    for y in (-0.5, -0.17, 0.17, 0.5):
        o.append(sb.box('head', (0.1, 0.28, 0.2), (0.04, y, 4.22), R('ink'), bev=0.01, rot=(0, 0.45, 0)))
        o.append(sb.box('lens', (0.012, 0.24, 0.16), (0.09, y, 4.2), R('lamp'), rot=(0, 0.45, 0)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            o.append(sb.cyl('wheel', 0.09, 0.05, (sx * 0.36, sy * 0.47, 0.09), R('rubber'), axis='y', verts=12))
    return o


def gantry():
    """Start gate: two 0.5 m truss towers 7.2 m apart (along Y), beam at 4.3..5.3 m. Origin: centre.
    The banner faces are added by the generator (brand panels on both sides of the beam)."""
    o = []
    span, top = 7.2, 5.3
    for sy in (-1, 1):
        for dx in (-1, 1):
            for dy in (-1, 1):
                o.append(sb.cyl('chord', 0.028, top, (dx * 0.2, sy * span / 2 + dy * 0.2, top / 2), R('steel'), verts=8))
        for k in range(8):                                         # lacing
            z = 0.35 + k * 0.62
            for dy in (-1, 1):
                o.append(sb.tube('lace', [(-0.2, sy * span / 2 + dy * 0.2, z), (0.2, sy * span / 2 + dy * 0.2, z + 0.62)], 0.012,
                                 R('steel'), verts=5))
            for dx in (-1, 1):
                o.append(sb.tube('lace', [(dx * 0.2, sy * span / 2 - 0.2, z), (dx * 0.2, sy * span / 2 + 0.2, z + 0.62)], 0.012,
                                 R('steel'), verts=5))
        o.append(sb.box('ballast', (0.9, 0.9, 0.3), (0, sy * span / 2, 0.15), R('ink'), bev=0.03))
        o.append(sb.box('ballast_line', (0.905, 0.905, 0.03), (0, sy * span / 2, 0.24), R('crimson')))
    for z in (4.3, top):
        for dx in (-1, 1):
            o.append(sb.cyl('beam', 0.028, span + 0.4, (dx * 0.2, 0, z), R('steel'), axis='y', verts=8))
    for k in range(12):
        y = -span / 2 + 0.3 + k * 0.6
        for dx in (-1, 1):
            o.append(sb.tube('lace', [(dx * 0.2, y, 4.3), (dx * 0.2, y + 0.6, top)], 0.012, R('steel'), verts=5))
    return o


def flag():
    """Feather flag, 4.2 m. The printed sail (0.8 x 3.0 m) is added by the generator. Collision:
    0.4 m base plate."""
    o = [sb.box('base', (0.5, 0.5, 0.05), (0, 0, 0.025), R('ink'), bev=0.01)]
    o.append(sb.cyl('pole', 0.018, 4.2, (0, 0, 2.1), R('steel'), verts=8))
    o.append(sb.tube('top', [(0, 0, 4.2), (0.3, 0, 4.35), (0.85, 0, 4.28)], 0.012, R('steel'), verts=6))
    return o


def barrier_tape_post():
    """Cordon post with a weighted base (0.9 m)."""
    o = [sb.cyl('base', 0.17, 0.06, (0, 0, 0.03), R('rubber'), verts=14)]
    o.append(sb.cyl('post', 0.022, 0.92, (0, 0, 0.5), R('crimson'), verts=8))
    o.append(sb.cyl('cap', 0.03, 0.05, (0, 0, 0.96), R('offwhite'), verts=8))
    return o


ASSETS = {
    'container': container, 'water_tank': water_tank, 'tent': tent, 'fountain': fountain,
    'chunk_a': lambda: chunk(1), 'chunk_b': lambda: chunk(2), 'chunk_c': lambda: chunk(3), 'chunk_d': lambda: chunk(4),
    'chunk_e': lambda: chunk(5), 'chunk_f': lambda: chunk(6), 'slab_a': lambda: chunk(11, True), 'slab_b': lambda: chunk(12, True),
    'slab_c': lambda: chunk(13, True), 'bricks_a': lambda: brick_heap(1), 'bricks_b': lambda: brick_heap(2),
    'fire_debris': fire_debris,
    'window_broken': lambda: window('broken'), 'window_boarded': lambda: window('boarded'), 'window_bars': lambda: window('bars'),
    'window_empty': lambda: window('empty'), 'window_intact': lambda: window('intact'), 'window_shutter': lambda: window('shutter'),
    'door_double': lambda: door(2.4, 'double'), 'door_one_leaf': lambda: door(2.4, 'one_leaf'), 'door_open': lambda: door(2.4, 'none'),
    'door_interior': lambda: door(1.7, 'interior'), 'door_interior_narrow': lambda: door(1.5, 'interior'),
    'awning': awning, 'ac_unit': ac_unit, 'roof_tank': lambda: rooftop('tank'), 'roof_dish': lambda: rooftop('dish'),
    'roof_hvac': lambda: rooftop('hvac'), 'roof_antenna': lambda: rooftop('antenna'),
    'table': lambda: furniture('table'), 'shelf': lambda: furniture('shelf'), 'cabinet': lambda: furniture('cabinet'),
    'crate': lambda: furniture('crate'),
    'street_lamp': street_lamp, 'utility_pole': utility_pole, 'sign_stop': lambda: traffic_sign('stop'),
    'sign_warning': lambda: traffic_sign('warning'), 'sign_info': lambda: traffic_sign('info'), 'bench': bench, 'bin': bin_can,
    'floodlight': floodlight, 'gantry': gantry, 'flag': flag, 'cordon_post': barrier_tape_post,
}


def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    render_dir = args[args.index('--render') + 1] if '--render' in args else None
    os.makedirs(OUT, exist_ok=True)
    index = {}
    idx_path = os.path.join(OUT, 'kit.yaml')
    for name, fn in ASSETS.items():
        if only and name not in only:
            continue
        sb.reset()
        sb._MATS.clear()
        ob = sb.finalize([x for x in fn() if x is not None], name)
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.quads_convert_to_tris()
        bpy.ops.object.mode_set(mode='OBJECT')
        cs = [v.co for v in ob.data.vertices]
        lo = [round(min(c[i] for c in cs), 4) for i in range(3)]
        hi = [round(max(c[i] for c in cs), 4) for i in range(3)]
        index[name] = dict(min=lo, max=hi, tris=len(ob.data.polygons), roles=sorted(m.name for m in ob.data.materials))
        sb.export_obj(ob, os.path.join(OUT, name + '.obj'))
        mtl = os.path.join(OUT, name + '.mtl')
        if os.path.exists(mtl):
            os.remove(mtl)                                         # roles are mapped by the generator
        print(f'[kit] {name:22s} {index[name]["tris"]:6d} tris  {lo} .. {hi}')
        if render_dir:
            ext = max(hi[i] - lo[i] for i in range(3))
            ctr = [(hi[i] + lo[i]) / 2 for i in range(3)]
            sb.render(os.path.join(render_dir, name + '.png'), target=ctr, dist=max(1.2, ext * 2.1), az=-55, el=18,
                      res=(640, 480), samples=24)
    # merge with the existing index when only some assets were rebuilt
    import json
    old = {}
    if os.path.exists(idx_path) and only:
        old = json.load(open(idx_path))
    old.update(index)
    with open(idx_path, 'w') as f:
        json.dump(old, f, indent=1, sort_keys=True)               # JSON is valid YAML


if __name__ == '__main__':
    main()
