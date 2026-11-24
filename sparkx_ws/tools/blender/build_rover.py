"""SparkX rescue rover (Husky A200 class) in the Airoot livery.

  blender -b --python build_rover.py [-- --render DIR]

Writes sparkx_description/meshes/rover_base.glb (everything rigid on base_link) and
rover_wheel.glb (one wheel, spin axis +Y, outer face +Y). Geometry is modelled in base_link
coordinates (ground at z = 0) and stays inside the collision envelope declared in the URDF:
footprint 0.99 x 0.67 m, electronics bay up to z = 0.53, mast + LiDAR up to z = 0.82. Nothing on
the body rises into the LiDAR's field of view (a 22.5 degree cone below the sensor at z = 0.78).

Livery (from the Airoot TurtleBot S1): ink body, crimson Airoot mark, crimson light line,
off-white edge lines and the three diagonal slashes.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import sparkx_bpy as sb  # noqa: E402

OUT = os.path.join(sb.SRC, 'sparkx_description', 'meshes')
TEX = os.path.join(sb.MEDIA, 'textures')

# URDF geometry this model has to agree with
WHEEL_R, WHEEL_W = 0.1651, 0.1143
WHEELBASE, TRACK = 0.512, 0.5708
LIDAR_Z = 0.78
CAM_X, CAM_Z, CAM_PITCH = 0.40, 0.52, 0.12
DECK_Z = 0.389                       # top of the deck plate
BAY = dict(x=-0.085, lx=0.44, ly=0.34, h=0.135)   # electronics bay (collision box "payload" in the URDF)


def materials():
    m = sb.mat
    return dict(
        ink=m('ink', sb.INK, rough=0.46, metal=0.2),
        matte=m('ink_matte', (0.07, 0.07, 0.075), rough=0.85),
        crimson=m('crimson', sb.CRIMSON, rough=0.42, metal=0.1),
        glow=m('crimson_glow', sb.CRIMSON, rough=0.3, emit=sb.CRIMSON, emit_strength=2.2),
        white=m('offwhite', sb.OFFWHITE, rough=0.55),
        alu=m('aluminium', (0.74, 0.75, 0.77), rough=0.34, metal=1.0),
        steel=m('dark_steel', (0.2, 0.2, 0.22), rough=0.42, metal=0.9),
        rubber=m('rubber', (0.04, 0.04, 0.04), rough=0.93),
        lens=m('lens', (0.02, 0.02, 0.035), rough=0.06),
        lamp=m('lamp', (1.0, 0.97, 0.9), rough=0.2, emit=(1.0, 0.97, 0.9), emit_strength=3.5),
        estop_y=m('estop_yellow', (0.95, 0.78, 0.05), rough=0.5),
        estop_r=m('estop_red', (0.78, 0.03, 0.03), rough=0.4),
        deck=m('deck_graphic', (1, 1, 1), rough=0.6, tex=os.path.join(TEX, 'robot_deck.jpg')),
        sticker=m('stemlearn_sticker', (1, 1, 1), rough=0.6, tex=os.path.join(TEX, 'brand_stemlearn.jpg')),
    )


def pitched(local, origin, pitch):
    """Point given in a frame pitched about +Y (nose down for positive pitch) -> base_link."""
    x, y, z = local
    c, s = math.cos(pitch), math.sin(pitch)
    return (origin[0] + x * c + z * s, origin[1] + y, origin[2] - x * s + z * c)


def build_base(M):
    o = []
    add = o.append
    # ---------------------------------------------------------------- hull
    add(sb.box('hull', (0.78, 0.42, 0.20), (0, 0, 0.265), M['ink'], bev=0.02, seg=3))
    add(sb.box('belly', (0.62, 0.36, 0.02), (0, 0, 0.151), M['steel'], bev=0.004))
    for s in (-1, 1):
        add(sb.box('edge_line', (0.70, 0.004, 0.010), (0, s * 0.2112, 0.345), M['white']))       # S1 edge line
        add(sb.box('sill', (0.30, 0.004, 0.030), (0, s * 0.2112, 0.215), M['steel']))             # access hatch
        for sx in (-1, 1):                                                                         # axle housings
            add(sb.cyl('axle', 0.042, 0.03, (sx * WHEELBASE / 2, s * 0.219, WHEEL_R), M['steel'], axis='y', verts=20,
                       bev=0.003))
    # ---------------------------------------------------------------- bumpers
    for sx in (-1, 1):
        add(sb.box('bumper', (0.07, 0.60, 0.075), (sx * 0.455, 0, 0.22), M['matte'], bev=0.018, seg=3))
        for s in (-1, 1):
            add(sb.box('bumper_cap', (0.07, 0.022, 0.075), (sx * 0.455, s * 0.311, 0.22), M['crimson'], bev=0.008))
            add(sb.box('bumper_mount', (0.05, 0.05, 0.05), (sx * 0.405, s * 0.15, 0.22), M['steel']))
    # ---------------------------------------------------------------- deck
    add(sb.prism('deck_lip', sb.octagon(0.752, 0.512, 0.056), 0.371, 0.377, M['white']))
    add(sb.prism('deck', sb.octagon(0.74, 0.50, 0.05), 0.375, DECK_Z, M['matte'], bev=0.003))
    for s in (-1, 1):
        add(sb.box('rail', (0.60, 0.02, 0.012), (0, s * 0.222, DECK_Z + 0.006), M['alu'], bev=0.002))
    # ---------------------------------------------------------------- electronics bay
    bx, lx, ly, bh = BAY['x'], BAY['lx'], BAY['ly'], BAY['h']
    bz = DECK_Z + bh / 2
    add(sb.box('bay', (lx, ly, bh), (bx, 0, bz), M['ink'], bev=0.012, seg=3))
    top = sb.box('bay_graphic', (lx - 0.03, ly - 0.03, 0.002), (bx, 0, DECK_Z + bh + 0.0008), M['deck'])
    sb.uv_project(top, 'z')
    add(top)
    logo = sb.airoot_logo()
    scale = 0.29 / logo['width']
    tris = [[(u * scale, v * scale) for u, v in t] for t in logo['triangles']]
    lz = bz - 0.004
    lxc = bx - 0.045
    # right side (-Y): text reads along +X; left side (+Y): along -X
    add(sb.flat_tris('logo_r', tris, (lxc, -ly / 2 - 0.0012, lz), (1, 0, 0), (0, 0, 1), M['crimson']))
    add(sb.flat_tris('logo_l', tris, (lxc, ly / 2 + 0.0012, lz), (-1, 0, 0), (0, 0, 1), M['crimson']))
    quad = [[(0, 0), (0.008, 0), (0.038, 0.055)], [(0, 0), (0.038, 0.055), (0.030, 0.055)]]
    for k in range(3):                                            # three slashes ahead of the logo
        x0 = bx + lx / 2 - 0.100 + k * 0.022
        add(sb.flat_tris('slash_r', quad, (x0, -ly / 2 - 0.0012, bz - 0.03), (1, 0, 0), (0, 0, 1), M['white']))
        add(sb.flat_tris('slash_l', quad, (x0 + 0.038, ly / 2 + 0.0012, bz - 0.03), (-1, 0, 0), (0, 0, 1), M['white']))
    add(sb.box('light_line', (0.004, 0.26, 0.012), (bx + lx / 2 + 0.001, 0, bz + 0.03), M['glow']))   # S1 light line
    stk = sb.box('sticker', (0.002, 0.20, 0.10), (bx - lx / 2 - 0.0008, 0, bz), M['sticker'])
    sb.uv_project(stk, 'x')
    for l in stk.data.uv_layers.active.data:                       # seen from behind, +Y is on the left
        l.uv.x = 1.0 - l.uv.x
    add(stk)
    # ---------------------------------------------------------------- front face: dots, headlights
    for y in (-0.09, -0.03, 0.03, 0.09):
        add(sb.cyl('dot', 0.012, 0.004, (0.391, y, 0.300), M['glow'], axis='x', verts=20))
    for s in (-1, 1):
        add(sb.cyl('lamp_body', 0.036, 0.03, (0.398, s * 0.155, 0.318), M['steel'], axis='x', verts=24, bev=0.003))
        add(sb.cyl('lamp_lens', 0.029, 0.004, (0.4145, s * 0.155, 0.318), M['lamp'], axis='x', verts=24))
        add(sb.box('tail', (0.004, 0.05, 0.015), (-0.391, s * 0.15, 0.33), M['glow']))
    # ---------------------------------------------------------------- mast + LiDAR (OS1 class)
    mast_z0 = DECK_Z + bh
    add(sb.cyl('mast_flange', 0.042, 0.012, (0, 0, mast_z0 + 0.006), M['alu'], verts=24))
    add(sb.box('mast', (0.04, 0.04, LIDAR_Z - 0.037 - mast_z0), (0, 0, (mast_z0 + LIDAR_Z - 0.037) / 2), M['alu'],
               bev=0.004))
    add(sb.cyl('lidar_base', 0.0445, 0.022, (0, 0, LIDAR_Z - 0.026), M['steel'], verts=36, bev=0.002))
    add(sb.cyl('lidar_window', 0.0428, 0.034, (0, 0, LIDAR_Z + 0.002), M['lens'], verts=36))
    add(sb.cyl('lidar_cap', 0.0445, 0.018, (0, 0, LIDAR_Z + 0.028), M['steel'], verts=36, bev=0.003))
    for k in range(12):                                            # heat-sink fins on the cap
        a = math.pi * k / 12
        add(sb.box('fin', (0.07, 0.003, 0.006), (0, 0, LIDAR_Z + 0.040), M['alu'], rot=(0, 0, a)))
    add(sb.tube('lidar_cable', [(-0.03, 0.0, LIDAR_Z - 0.03), (-0.034, 0.004, LIDAR_Z - 0.09), (-0.03, 0.0, mast_z0 + 0.04),
                                (-0.05, 0.0, mast_z0 + 0.004)], 0.0045, M['rubber']))
    # ---------------------------------------------------------------- front sensor head (RGB-D + thermal)
    add(sb.box('head_post', (0.04, 0.10, 0.108), (0.352, 0, DECK_Z + 0.054), M['alu'], bev=0.004))
    add(sb.box('head_plate', (0.07, 0.16, 0.008), (0.372, 0, DECK_Z + 0.112), M['steel'], bev=0.002))
    # The optical centres (camera_link / thermal_link in the URDF) sit ON the front face of each
    # housing: every part of a housing is at or behind its sensor origin, so no camera can ever
    # look at the inside of its own body.
    cam = (CAM_X, 0.0, CAM_Z)
    rot = (0, CAM_PITCH, 0)
    add(sb.box('rgbd_body', (0.026, 0.124, 0.029), pitched((-0.016, 0, 0), cam, CAM_PITCH), M['alu'], rot=rot, bev=0.004,
               seg=3))
    add(sb.box('rgbd_face', (0.002, 0.112, 0.021), pitched((-0.003, 0, 0), cam, CAM_PITCH), M['lens'], rot=rot))
    for y in (-0.0475, -0.018, 0.018, 0.0475):
        add(sb.cyl('rgbd_lens', 0.0065, 0.003, pitched((-0.0015, y, 0), cam, CAM_PITCH), M['steel'],
                   rot=(0, math.pi / 2 + CAM_PITCH, 0), verts=16))
    th = (CAM_X, 0.0, CAM_Z + 0.04)
    add(sb.box('thermal_body', (0.032, 0.032, 0.032), pitched((-0.030, 0, 0), th, CAM_PITCH), M['matte'], rot=rot, bev=0.003))
    add(sb.cyl('thermal_barrel', 0.0125, 0.012, pitched((-0.008, 0, 0), th, CAM_PITCH), M['steel'],
               rot=(0, math.pi / 2 + CAM_PITCH, 0), verts=20))
    add(sb.cyl('thermal_lens', 0.0095, 0.002, pitched((-0.001, 0, 0), th, CAM_PITCH), M['lens'],
               rot=(0, math.pi / 2 + CAM_PITCH, 0), verts=20))
    add(sb.box('head_bracket', (0.012, 0.06, 0.075), (0.366, 0, DECK_Z + 0.150), M['steel'], bev=0.002))
    # ---------------------------------------------------------------- rear: GNSS, antennas, e-stop
    add(sb.cyl('gnss', 0.03, 0.016, (bx - 0.155, 0.10, DECK_Z + bh + 0.008), M['white'], verts=24, bev=0.004))
    for s in (-1, 1):
        add(sb.cyl('ant_base', 0.008, 0.012, (bx - 0.185, s * 0.13, DECK_Z + bh + 0.006), M['steel'], verts=12))
        add(sb.cyl('antenna', 0.0045, 0.085, (bx - 0.185, s * 0.13, DECK_Z + bh + 0.0425), M['rubber'], verts=10))
    add(sb.cyl('estop_base', 0.03, 0.035, (-0.325, -0.213, DECK_Z + 0.0175), M['estop_y'], verts=24, bev=0.003))
    add(sb.cyl('estop_button', 0.024, 0.018, (-0.325, -0.213, DECK_Z + 0.044), M['estop_r'], verts=24, bev=0.005, seg=3))
    add(sb.box('charge_port', (0.004, 0.05, 0.035), (-0.391, 0, 0.25), M['steel'], bev=0.002))
    return sb.finalize(o, 'rover_base')


def build_wheel(M):
    o = []
    add = o.append
    hw = WHEEL_W / 2 - 0.0006
    carcass = [(0.100, -0.050), (0.128, -hw), (0.150, -hw + 0.002), (0.158, -0.045), (0.1595, 0.0), (0.158, 0.045),
               (0.150, hw - 0.002), (0.128, hw), (0.100, 0.050)]
    add(sb.lathe('tyre', carcass, M['rubber'], segments=44))
    n = 22
    for k in range(n):                                            # staggered chevron lugs
        side = 1 if k % 2 == 0 else -1
        lug = sb.box('lug', (0.013, 0.060, 0.021), (0, 0, 0), M['rubber'], bev=0.003)
        m = (Matrix.Rotation(-2 * math.pi * k / n, 4, 'Y') @ Matrix.Translation((0.1586, side * 0.026, 0))
             @ Matrix.Rotation(side * 0.42, 4, 'X'))
        lug.matrix_world = m
        add(lug)
    add(sb.cyl('rim', 0.101, 0.088, (0, 0, 0), M['matte'], axis='y', verts=40))
    add(sb.lathe('stripe', [(0.129, hw - 0.0008), (0.136, hw - 0.0012), (0.136, hw + 0.0006), (0.129, hw + 0.0010)],
                 M['white'], segments=44))
    add(sb.cyl('dish', 0.097, 0.004, (0, 0.040, 0), M['steel'], axis='y', verts=40))
    for k in range(5):
        sp = sb.box('spoke', (0.070, 0.012, 0.022), (0, 0, 0), M['alu'], bev=0.003)
        sp.matrix_world = Matrix.Rotation(2 * math.pi * k / 5, 4, 'Y') @ Matrix.Translation((0.060, 0.044, 0))
        add(sp)
        nut = sb.cyl('nut', 0.0055, 0.008, (0, 0, 0), M['steel'], axis='y', verts=6)
        nut.matrix_world = (Matrix.Rotation(2 * math.pi * (k + 0.5) / 5, 4, 'Y') @ Matrix.Translation((0.024, 0.056, 0))
                            @ nut.matrix_world)
        add(nut)
    add(sb.cyl('hub', 0.034, 0.03, (0, 0.046, 0), M['alu'], axis='y', verts=28, bev=0.004))
    add(sb.cyl('cap', 0.018, 0.006, (0, 0.063, 0), M['crimson'], axis='y', verts=24, bev=0.002))
    add(sb.cyl('inner_hub', 0.05, 0.02, (0, -0.045, 0), M['steel'], axis='y', verts=24))
    return sb.finalize(o, 'rover_wheel')


def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    sb.reset()
    M = materials()
    base = build_base(M)
    wheel = build_wheel(M)
    print(f'[rover] base {sb.tri_count(base)} tris, wheel {sb.tri_count(wheel)} tris')
    sb.export_glb(base, os.path.join(OUT, 'rover_base.glb'))
    sb.export_glb(wheel, os.path.join(OUT, 'rover_wheel.glb'))
    if '--render' in args:
        out = args[args.index('--render') + 1]
        os.makedirs(out, exist_ok=True)
        for sx in (-1, 1):
            for sy in (-1, 1):
                w = wheel if (sx, sy) == (1, 1) else wheel.copy()
                if w is not wheel:
                    bpy.context.scene.collection.objects.link(w)
                w.location = (sx * WHEELBASE / 2, sy * TRACK / 2, WHEEL_R)
                w.rotation_euler = (0, 0, 0 if sy > 0 else math.pi)
        sb.render(os.path.join(out, 'rover_front.png'), target=(0, 0, 0.36), dist=2.3, az=-38, el=20)
        sb.render(os.path.join(out, 'rover_rear.png'), target=(0, 0, 0.36), dist=2.3, az=150, el=24)
        sb.render(os.path.join(out, 'rover_top.png'), target=(0, 0, 0.3), dist=2.2, az=-90, el=62)


if __name__ == '__main__':
    main()
