"""Blender-RENDERED artwork for the bombed-city look: real 3D scenes rendered with Cycles and
imported into Gazebo as textures.

  blender -b --python render_decals.py [-- --only crater_a,debris_a] [--samples 48]

Writes into sparkx_worlds/models/sparkx_media/textures/:
  decal_debris_{a,b,c}.png   4 x 4 m top-down debris fields (rubble, bricks, planks, rebar, dust)
  decal_crater_{a,b}.png     6 x 6 m shell craters (displaced ground, raised rim, scorch, ejecta)
  decal_wallhole_{a,b}.png   3 x 3 m shell-holes for facades (exposed brick, dark void, cracks)
  sky_war.jpg                4096 x 1024 panorama for the sky dome: hazy low sun over a ruined skyline

Decals are RGBA with a hard (cut-out) alpha: Gazebo's ogre2 renderer alpha-tests textures, it does
not blend them, so every decal is an irregular opaque patch with its own lighting baked in.
The generator lays ground decals flat (they are a few millimetres thick, the rover drives over
them) and hangs wall decals on facades (the wall behind stays solid).
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector, noise  # noqa: E402

import build_kit as kit  # noqa: E402
import sparkx_bpy as sb  # noqa: E402

TEX = os.path.join(sb.MEDIA, 'textures')
PI = math.pi


def scan(name, base, scale=1.0, rough=0.9):
    """Material from one of the scanned PBR sets, box-projected in object space."""
    key = f'{name}_{base}_{scale}'
    if key in sb._MATS:
        return sb._MATS[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = rough
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (scale, scale, scale)
    img = nt.nodes.new('ShaderNodeTexImage')
    img.image = bpy.data.images.load(os.path.join(TEX, base + '.jpg'), check_existing=True)
    img.projection, img.projection_blend = 'BOX', 0.2
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    nt.links.new(mp.outputs['Vector'], img.inputs['Vector'])
    nt.links.new(img.outputs['Color'], b.inputs['Base Color'])
    nrm = os.path.join(TEX, base + '_n.jpg')
    if os.path.exists(nrm):
        ni = nt.nodes.new('ShaderNodeTexImage')
        ni.image = bpy.data.images.load(nrm, check_existing=True)
        ni.image.colorspace_settings.name = 'Non-Color'
        ni.projection, ni.projection_blend = 'BOX', 0.2
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nt.links.new(mp.outputs['Vector'], ni.inputs['Vector'])
        nt.links.new(ni.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], b.inputs['Normal'])
    sb._MATS[key] = m
    return m


def flat(name, color, rough=0.9, emit=0.0):
    return sb.mat(name, color, rough=rough, emit=color if emit else None, emit_strength=emit)


def blob(name, radius, material, seed, z=0.0, n=72, jitter=0.28, freq=2.2, dome=0.0, rings=6):
    """Irregular patch with a noisy outline (the opaque base of a decal). dome > 0 heaps it up."""
    bm = bmesh.new()
    off = Vector((seed * 3.1, seed * 1.7, 0))
    centre = bm.verts.new((0, 0, z + dome))
    prev = [centre] * n
    for j in range(1, rings + 1):
        t = j / rings
        ring = []
        for k in range(n):
            a = 2 * PI * k / n
            r = radius * (1 + jitter * noise.noise(Vector((math.cos(a) * freq, math.sin(a) * freq, 0)) + off)
                          + 0.5 * jitter * noise.noise(Vector((math.cos(a) * freq * 4, math.sin(a) * freq * 4, 5)) + off))
            p = Vector((r * t * math.cos(a), r * t * math.sin(a), 0))
            bump = 0.03 * noise.noise(p * 3 + off)
            ring.append(bm.verts.new((p.x, p.y, z + dome * (1 - t) ** 1.5 + bump)))
        for k in range(n):
            k2 = (k + 1) % n
            if j == 1:
                bm.faces.new((centre, ring[k], ring[k2]))
            else:
                bm.faces.new((prev[k], ring[k], ring[k2], prev[k2]))
        prev = ring
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = sb._new_object(name, bm, material)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def scatter_debris(rg, radius, count, mats, size=(0.08, 0.42), height=0.0, centre_bias=1.0):
    out = []
    for k in range(count):
        r = radius * (rg.random() ** centre_bias)
        a = rg.uniform(0, 2 * PI)
        s = rg.uniform(*size)
        parts = kit.chunk(rg.randrange(1, 9999), flat=rg.random() < 0.3)
        for ob in parts:
            ob.data.materials.clear()
            ob.data.materials.append(rg.choice(mats) if ob.name.startswith('chunk') else flat('rebar', (0.3, 0.16, 0.1), 0.6))
            ob.scale = (s * rg.uniform(0.7, 1.4), s * rg.uniform(0.6, 1.2), s * rg.uniform(0.35, 0.8))
            ob.rotation_euler = (rg.uniform(-0.5, 0.5), rg.uniform(-0.5, 0.5), rg.uniform(0, 2 * PI))
            ob.location = (r * math.cos(a), r * math.sin(a), height + s * 0.22)
        out += parts
    return out


def bricks(rg, radius, count, material):
    out = []
    for _ in range(count):
        r, a = radius * math.sqrt(rg.random()), rg.uniform(0, 2 * PI)
        whole = rg.random() < 0.6
        out.append(sb.box('brick', (0.23 if whole else rg.uniform(0.08, 0.15), 0.11, 0.07),
                          (r * math.cos(a), r * math.sin(a), 0.045 + rg.uniform(0, 0.05)), material,
                          rot=(rg.uniform(-0.4, 0.4), rg.uniform(-0.4, 0.4), rg.uniform(0, PI))))
    return out


# ------------------------------------------------------------------------------------- scenes
def debris(seed):
    rg = random.Random(seed)
    o = [blob('dust', 1.65, scan('dust', 'concrete_dark', 0.7), seed, dome=0.06)]
    mats = [scan('c1', 'concrete', 0.8), scan('c2', 'rubble', 0.9), scan('c3', 'concrete_dark', 0.8), scan('c4', 'plaster', 0.6)]
    o += scatter_debris(rg, 1.45, rg.randint(34, 46), mats, centre_bias=0.75)
    o += bricks(rg, 1.3, rg.randint(22, 40), scan('brick', 'brick', 1.4))
    for _ in range(rg.randint(3, 6)):                              # splintered planks
        a, r = rg.uniform(0, 2 * PI), rg.uniform(0.2, 1.1)
        o.append(sb.box('plank', (rg.uniform(0.6, 1.5), 0.12, 0.03), (r * math.cos(a), r * math.sin(a), 0.1), scan('wood', 'wood', 1.0),
                        rot=(rg.uniform(-0.15, 0.15), rg.uniform(-0.15, 0.15), rg.uniform(0, PI))))
    for _ in range(rg.randint(3, 6)):                              # twisted rebar
        a, r = rg.uniform(0, 2 * PI), rg.uniform(0.1, 1.0)
        x, y = r * math.cos(a), r * math.sin(a)
        d = rg.uniform(0, 2 * PI)
        o.append(sb.tube('rebar', [(x, y, 0.06), (x + 0.4 * math.cos(d), y + 0.4 * math.sin(d), 0.16),
                                   (x + 0.75 * math.cos(d + 0.5), y + 0.75 * math.sin(d + 0.5), 0.07)], 0.012,
                         flat('rebar', (0.3, 0.16, 0.1), 0.6), verts=6))
    return o, 4.0


def crater(seed):
    rg = random.Random(seed)
    size, R = 6.0, 1.25
    bm = bmesh.new()
    n = 170
    off = Vector((seed * 2.3, seed * 0.7, 0))
    grid = {}
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = (i / n - 0.5) * size, (j / n - 0.5) * size
            a = math.atan2(y, x)
            r = math.hypot(x, y)
            edge = 2.55 * (1 + 0.16 * noise.noise(Vector((math.cos(a) * 2.0, math.sin(a) * 2.0, 0)) + off)
                           + 0.08 * noise.noise(Vector((math.cos(a) * 7.0, math.sin(a) * 7.0, 3)) + off))
            if r > edge:
                continue
            rr = r / R
            z = -0.55 * max(0.0, 1 - rr * rr) + 0.28 * math.exp(-((rr - 1.15) / 0.28) ** 2) + 0.05 * math.exp(-((rr - 1.6) / 0.4) ** 2)
            z += 0.05 * noise.noise(Vector((x * 2.5, y * 2.5, 0)) + off) + 0.02 * noise.noise(Vector((x * 9, y * 9, 1)) + off)
            grid[(i, j)] = bm.verts.new((x, y, z))
    for j in range(n):
        for i in range(n):
            q = [grid.get(k) for k in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
            if all(q):
                bm.faces.new(q)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ground = sb._new_object('crater', bm, None)
    for p in ground.data.polygons:
        p.use_smooth = True
    # scorched in the bowl, churned earth on the rim, dust beyond: mixed by distance from the centre
    m = bpy.data.materials.new(f'crater_{seed}')
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 1.0
    tc = nt.nodes.new('ShaderNodeTexCoord')
    grad = nt.nodes.new('ShaderNodeTexGradient')
    grad.gradient_type = 'SPHERICAL'
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (1 / 2.6, 1 / 2.6, 1 / 2.6)
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    nt.links.new(mp.outputs['Vector'], grad.inputs['Vector'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.25, 0.6
    nt.links.new(grad.outputs['Fac'], ramp.inputs['Fac'])

    def tex(base, scale):
        mp2 = nt.nodes.new('ShaderNodeMapping')
        mp2.inputs['Scale'].default_value = (scale, scale, scale)
        t = nt.nodes.new('ShaderNodeTexImage')
        t.image = bpy.data.images.load(os.path.join(TEX, base + '.jpg'), check_existing=True)
        t.projection, t.projection_blend = 'BOX', 0.2
        nt.links.new(tc.outputs['Object'], mp2.inputs['Vector'])
        nt.links.new(mp2.outputs['Vector'], t.inputs['Vector'])
        return t
    mix = nt.nodes.new('ShaderNodeMixRGB')
    nt.links.new(ramp.outputs['Color'], mix.inputs['Fac'])
    nt.links.new(tex('dirt', 0.5).outputs['Color'], mix.inputs['Color1'])         # outside: churned earth
    nt.links.new(tex('scorched', 0.6).outputs['Color'], mix.inputs['Color2'])     # inside: burnt
    dark = nt.nodes.new('ShaderNodeMixRGB')
    dark.blend_type = 'MULTIPLY'
    dark.inputs['Fac'].default_value = 1.0
    nt.links.new(mix.outputs['Color'], dark.inputs['Color1'])
    r2 = nt.nodes.new('ShaderNodeValToRGB')
    r2.color_ramp.elements[0].color, r2.color_ramp.elements[1].color = (1, 1, 1, 1), (0.25, 0.22, 0.2, 1)
    r2.color_ramp.elements[0].position, r2.color_ramp.elements[1].position = 0.45, 0.95
    nt.links.new(grad.outputs['Fac'], r2.inputs['Fac'])
    nt.links.new(r2.outputs['Color'], dark.inputs['Color2'])
    nt.links.new(dark.outputs['Color'], b.inputs['Base Color'])
    ground.data.materials.append(m)
    o = [ground]
    mats = [scan('c1', 'concrete', 0.8), scan('c2', 'rubble', 0.9), scan('asph', 'asphalt', 0.5), scan('c3', 'concrete_dark', 0.8)]
    for k in range(60):                                            # ejecta thrown outwards, thinning with distance
        a = rg.uniform(0, 2 * PI)
        r = R * rg.uniform(1.05, 1.95) ** 1.2
        s = rg.uniform(0.07, 0.34) * (1.5 - 0.5 * r / (2 * R))
        for ob in kit.chunk(rg.randrange(1, 9999), flat=rg.random() < 0.4):
            ob.data.materials.clear()
            ob.data.materials.append(rg.choice(mats))
            ob.scale = (s * 1.2, s, s * 0.6)
            ob.rotation_euler = (rg.uniform(-0.6, 0.6), rg.uniform(-0.6, 0.6), a)
            ob.location = (r * math.cos(a), r * math.sin(a), 0.12 + s * 0.2)
            o.append(ob)
    return o, size


def wallhole(seed):
    """Shell strike on a facade, modelled flat on the ground and rendered from above."""
    rg = random.Random(seed)
    o = [blob('brick_layer', 1.05, scan('brick', 'brick', 1.0), seed, z=0.0, jitter=0.36, freq=2.6, rings=5)]
    o.append(blob('void', 0.5, flat('void', (0.012, 0.01, 0.01), 1.0), seed + 7, z=0.02, jitter=0.4, freq=3.0, rings=3))
    o.append(blob('char', 0.66, flat('char', (0.05, 0.04, 0.035), 1.0), seed + 3, z=0.012, jitter=0.45, freq=3.4, rings=3))
    mats = [scan('pl', 'plaster', 0.6), scan('c1', 'concrete', 0.8)]
    for k in range(38):                                            # plaster and brick still clinging to the edge
        a = rg.uniform(0, 2 * PI)
        r = rg.uniform(0.62, 1.12)
        s = rg.uniform(0.07, 0.24)
        for ob in kit.chunk(rg.randrange(1, 9999), flat=True):
            if not ob.name.startswith('chunk'):
                bpy.data.objects.remove(ob, do_unlink=True)
                continue
            ob.data.materials.clear()
            ob.data.materials.append(rg.choice(mats))
            ob.scale = (s * 1.3, s, 0.035)
            ob.rotation_euler = (0, 0, rg.uniform(0, 2 * PI))
            ob.location = (r * math.cos(a), r * math.sin(a), 0.035)
            o.append(ob)
    for k in range(rg.randint(4, 7)):                              # bent reinforcement across the hole
        a = rg.uniform(0, PI)
        d = rg.uniform(-0.3, 0.3)
        o.append(sb.tube('rebar', [(-0.55 * math.cos(a) - d * math.sin(a), -0.55 * math.sin(a) + d * math.cos(a), 0.04),
                                   (rg.uniform(-0.1, 0.1), rg.uniform(-0.1, 0.1), 0.1),
                                   (0.5 * math.cos(a) - d * math.sin(a), 0.5 * math.sin(a) + d * math.cos(a), 0.04)], 0.012,
                         flat('rebar', (0.28, 0.15, 0.1), 0.6), verts=6))
    for k in range(rg.randint(6, 9)):                              # cracks running out into the wall
        a = rg.uniform(0, 2 * PI)
        pts, r, ang = [], 0.95, a
        while r < 1.45:
            pts.append((r * math.cos(ang), r * math.sin(ang), 0.006))
            r += rg.uniform(0.07, 0.14)
            ang += rg.uniform(-0.12, 0.12)
        if len(pts) > 2:
            o.append(sb.tube('crack', pts, rg.uniform(0.006, 0.014), flat('crack', (0.03, 0.03, 0.03), 1.0), verts=4))
    return o, 3.0


def render_top(path, size, samples, sun_el=42.0, sun_az=140.0, res=1024):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising = 'CPU', samples, True
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.image_settings.file_format, sc.render.image_settings.color_mode = 'PNG', 'RGBA'
    sc.view_settings.view_transform = 'Standard'
    if sc.world is None:
        sc.world = bpy.data.worlds.new('w')
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']
    bg.inputs[0].default_value, bg.inputs[1].default_value = (0.7, 0.68, 0.66, 1), 0.5
    ld = bpy.data.lights.new('sun', 'SUN')
    ld.energy, ld.angle = 2.1, math.radians(9)
    lo = bpy.data.objects.new('sun', ld)
    sc.collection.objects.link(lo)
    lo.rotation_euler = (math.radians(90 - sun_el), 0, math.radians(sun_az))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    sc.collection.objects.link(cam)
    cam.data.type, cam.data.ortho_scale = 'ORTHO', size
    cam.location, cam.rotation_euler = (0, 0, 12), (0, 0, 0)
    sc.camera = cam
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


# ------------------------------------------------------------------------------------- sky panorama
def sky(path, samples):
    """Hazy, low-sun sky over a ring of broken towers, rendered as a 360 x 90 degree panorama."""
    rg = random.Random(77)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising = 'CPU', samples, True
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new('sky')
    sc.world.use_nodes = True
    nt = sc.world.node_tree
    st = nt.nodes.new('ShaderNodeTexSky')
    st.sky_type = 'NISHITA'
    st.sun_elevation, st.sun_rotation = math.radians(9), math.radians(205)
    st.air_density, st.dust_density, st.ozone_density, st.sun_intensity = 2.2, 9.0, 1.5, 0.35
    bg = nt.nodes['Background']
    bg.inputs[1].default_value = 0.09
    nt.links.new(st.outputs['Color'], bg.inputs[0])
    dark = sb.mat('ruin', (0.07, 0.065, 0.06), rough=1.0)
    glow = sb.mat('fire_glow', (1.0, 0.35, 0.05), rough=1.0, emit=(1.0, 0.32, 0.04), emit_strength=6.0)
    o = [sb.box('ground', (4000, 4000, 1), (0, 0, -0.5), sb.mat('gnd', (0.06, 0.055, 0.05), rough=1.0))]
    for ring, (dist, n) in enumerate(((380, 46), (560, 60), (820, 70))):
        for k in range(n):
            a = 2 * PI * (k + rg.uniform(-0.3, 0.3)) / n
            d = dist * rg.uniform(0.9, 1.15)
            w, dep, h = rg.uniform(14, 34), rg.uniform(12, 26), rg.uniform(14, 62) * (1.0 + 0.25 * ring)
            cx, cy = d * math.cos(a), d * math.sin(a)
            cols = max(3, int(w / 4.5))
            bite = rg.randrange(cols)
            for c in range(cols):                                  # broken tops: each bay a different height
                hh = h * rg.uniform(0.55, 1.0) * (0.35 + 0.65 * min(1.0, abs(c - bite) / max(1.0, cols * 0.45)))
                ox = (c + 0.5) / cols * w - w / 2
                o.append(sb.box('ruin', (w / cols * 0.98, dep, hh), (cx - ox * math.sin(a), cy + ox * math.cos(a), hh / 2), dark,
                                rot=(0, 0, a + PI / 2)))
            if rg.random() < 0.16:
                o.append(sb.box('fire', (w * 0.3, dep * 0.4, h * 0.12), (cx, cy, h * 0.2), glow, rot=(0, 0, a + PI / 2)))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    sc.collection.objects.link(cam)
    cam.data.type = 'PANO'
    cam.data.panorama_type = 'EQUIRECTANGULAR'
    cam.data.latitude_min, cam.data.latitude_max = math.radians(-2), math.radians(88)
    cam.location, cam.rotation_euler = (0, 0, 9), (PI / 2, 0, 0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 4096, 1024
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'Filmic'
    sc.view_settings.exposure = 0.6
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


SCENES = {'debris_a': lambda: debris(11), 'debris_b': lambda: debris(12), 'debris_c': lambda: debris(13),
          'crater_a': lambda: crater(21), 'crater_b': lambda: crater(22),
          'wallhole_a': lambda: wallhole(31), 'wallhole_b': lambda: wallhole(32)}


def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    samples = int(args[args.index('--samples') + 1]) if '--samples' in args else 48
    for name, fn in SCENES.items():
        if only and name not in only:
            continue
        sb.reset()
        sb._MATS.clear()
        _objs, size = fn()
        render_top(os.path.join(TEX, f'decal_{name}.png'), size, samples, sun_el=34.0 if name.startswith('crater') else 46.0)
        print(f'[decal] {name} ({size} m)')
    if not only or 'sky' in only:
        sb.reset()
        sb._MATS.clear()
        sky(os.path.join(TEX, 'sky_war_render.png'), max(24, samples // 2))
        print('[decal] sky panorama')


if __name__ == '__main__':
    main()
