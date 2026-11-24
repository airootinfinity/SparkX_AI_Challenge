"""Scene props: catalog vehicles/props, burnt cars, boulders, rubble piles, fires, survivors, decoys."""
import math

import numpy as np

from . import kit
from .scene import catalog_box
from .sdfgen import emitter, fmt, include, label_plugin, material_xml, mesh_model, point_light, thermal_plugin
from .vocab import LABEL_IDS

ROCK_MAT = ('<material><diffuse>1 1 1 1</diffuse><specular>0.1 0.1 0.1 1</specular><pbr><metal>'
            '<albedo_map>model://sparkx_rock/materials/textures/FallingRocks_Albedo.jpg</albedo_map>'
            '<normal_map>model://sparkx_rock/materials/textures/FallingRocks_Normal.jpg</normal_map>'
            '<roughness_map>model://sparkx_rock/materials/textures/FallingRocks_Roughness.jpg</roughness_map>'
            '</metal></pbr></material>')


def place_catalog(scene, cat, name, x, y, yaw, margin=0.3, landmark=True, ignore_reserved=False, force=False):
    e = cat[name]
    pose = (x, y, 0.0, 0.0, 0.0, yaw)
    row = catalog_box(e, pose)
    if not force and not scene.placer.box_free(row, margin, ignore_reserved):
        return None
    cls = e.get('cls')
    plugins = label_plugin(LABEL_IDS[cls]) if cls in LABEL_IDS else ''
    uid = scene.uid(name.replace('sparkx_', ''))
    scene.add_model(include(f'model://{name}', uid, pose, plugins), [row], tag=e['kind'])
    rec = dict(model=uid, row=row)
    if landmark and cls in ('bus', 'fire_truck', 'ambulance', 'car', 'dumpster'):
        rec['landmark'] = scene.add_landmark(cls, e['color'], x, y, 0.0, yaw, np.subtract(e['max'], e['min']),
                                             model=uid, footprint=row)
    return rec


def burnt_car(scene, cat, x, y, yaw, margin=0.3, hot=True):
    e = cat['sparkx_car_white']
    pose = (x, y, 0.0, 0.0, 0.0, yaw)
    row = catalog_box(e, pose)
    if not scene.placer.box_free(row, margin):
        return None
    uid = scene.uid('burnt_car')
    mn, mx = np.array(e['min']), np.array(e['max'])
    c = (mn + mx) / 2
    s = (mx - mn) * np.array([0.9, 0.9, 1.0])
    vis_pl = thermal_plugin(float(scene.rng.uniform(330, 360))) if hot else ''
    if scene.rng.random() < 0.3:                                   # thrown onto its roof by a blast
        pose = (x, y, float(mx[2] + mn[2]), math.pi, 0.0, yaw)
    # the hatchback mesh is modelled along y; catalog mesh_pose rotates it by +90 deg
    sdf = (f'<model name="{uid}"><static>true</static><pose>{fmt(pose)}</pose>'
           f'{label_plugin(LABEL_IDS["burnt_car"])}<link name="link">'
           f'<collision name="c"><pose>{fmt(c)} 0 0 0</pose><geometry><box><size>{fmt(s)}</size></box></geometry>'
           f'</collision><visual name="visual"><pose>0 0 -0.06 0.03 0.02 1.5707963</pose><geometry><mesh>'
           f'<uri>model://sparkx_car_white/meshes/hatchback.obj</uri><scale>0.0254 0.0254 0.0254</scale></mesh>'
           f'</geometry>{material_xml("burnt_metal")}{vis_pl}'
           f'</visual></link></model>')
    scene.add_model(sdf, [row], tag='vehicle')
    return dict(model=uid, row=row)


# Boulder collision as fractions of the mesh's bounding box (x, y): the mesh outline lies between 0.90
# and 1.06 of the half-size in every direction, these boxes reach at most 0.91.
ROCK_COLLISION = ((0.84, 0.36), (0.36, 0.84), (0.62, 0.62))


def rock(scene, cat, x, y, scale, yaw=None, margin=0.05, sink=0.25, check=True, ignore_reserved=False):
    e = cat['sparkx_rock']
    mn, mx = np.array(e['min']) * scale, np.array(e['max']) * scale
    yaw = float(scene.rng.uniform(-math.pi, math.pi)) if yaw is None else yaw
    z = -mn[2] - sink * (mx[2] - mn[2])
    size = (mx - mn) * np.array([0.8, 0.8, 1.0])
    row = [x, y, z + (mn[2] + mx[2]) / 2, size[0], size[1], size[2], 0, 0, yaw]
    if row[2] - size[2] / 2 < 0:
        row[5] = row[2] * 2 + size[2] / 2  # keep collision box above ground
        row[2] = row[5] / 2
    if check and not scene.placer.box_free(row, margin, ignore_reserved):
        return None
    uid = scene.uid('rock')
    pose = (x, y, z, float(scene.rng.uniform(-0.3, 0.3)), float(scene.rng.uniform(-0.3, 0.3)), yaw)
    sdf = mesh_model(uid, 'model://sparkx_rock/meshes/FallingRock01.dae', pose, scale, collision_box=None,
                     plugins=label_plugin(LABEL_IDS['rock']))
    sdf = sdf.replace('</geometry></visual>', f'</geometry>{ROCK_MAT}</visual>', 1)
    scene.models.append(sdf)
    # Collision in the world frame (independent of the random tilt of the visual), kept in one static
    # model. Three boxes that together make an octagon just inside the boulder's outline: one box
    # the size of `row` would stick its corners up to 0.4 m out of the rock, an obstacle no sensor
    # can see. `row` still reserves the ground the boulder stands on.
    full = (mx - mn)
    for fx, fy in ROCK_COLLISION:
        scene.group('debris_collisions').box(row[:3], (full[0] * fx, full[1] * fy, row[5]), None, rpy=row[6:9],
                                             tag='rubble')
    scene.placer.mark_box(row)
    return row


# Rubble that counts as a collision is never lower than this: the rover's LiDAR sits 0.78 m up and
# looks at most 22.5 degrees down, so it sees a 0.35 m block from 1 m to 5 m away, but a 0.2 m one
# only in a narrow band around 2 m.
RUBBLE_MIN_HEIGHT_M = 0.35

CHUNKS = ['chunk_a', 'chunk_b', 'chunk_c', 'chunk_d', 'chunk_e', 'chunk_f']
SLABS = ['slab_a', 'slab_b', 'slab_c']
BRICKS = ['bricks_a', 'bricks_b']


def rubble_chunk(group, rng, row, mat):
    """Dress one rubble collision box with a broken-concrete / slab / brick-heap kit part."""
    sx, sy, sz = row[3:6]
    if mat in ('brick', 'brick_grey') and rng.random() < 0.6:
        kit.fit(group, str(rng.choice(BRICKS)), row, roles={'body': mat})
        return
    flat = sz < 0.45 * min(sx, sy)
    name = str(rng.choice(SLABS if flat else CHUNKS))
    kit.fit(group, name, row, roles={'concrete': mat})


def rubble_pile(scene, group, cat, x, y, radius, height=1.0, density=1.0, rocks=2, solid_core=None,
                ignore_reserved=False):
    """Irregular pile of broken concrete, slabs, brick heaps and boulders. solid_core=(sx, sy, yaw)
    adds a gap-free 1 m high core so the pile is guaranteed impassable (used for blockages)."""
    rng = scene.rng
    n = int(density * 6 * radius * radius) + 3
    placed = []
    if solid_core is not None:
        n = min(n, 70)                                             # the core does the blocking; keep the dressing light
        sx, sy, yaw = solid_core
        row = [x, y, 0.5, sx, sy, 1.0, 0, 0, yaw]
        group.box(row[:3], row[3:6], None, rpy=row[6:9], tag='rubble')
        scene.placer.mark_box(row)
        placed.append(row)
        k = max(1, int(math.ceil(sx / 1.3)))                       # the core looks like a row of big blocks
        c, s = math.cos(yaw), math.sin(yaw)
        for i in range(k):
            off = -sx / 2 + sx * (i + 0.5) / k
            kit.fit(group, str(rng.choice(CHUNKS)), [x + off * c, y + off * s, 0.5 + float(rng.uniform(-0.04, 0.06)),
                                                     sx / k * 1.12, sy * float(rng.uniform(0.92, 1.05)), 1.06,
                                                     float(rng.uniform(-0.08, 0.08)), float(rng.uniform(-0.08, 0.08)),
                                                     yaw + float(rng.uniform(-0.12, 0.12))],
                    roles={'concrete': str(rng.choice(['rubble', 'concrete', 'concrete_dark']))})
    for _ in range(n):
        r = radius * math.sqrt(rng.random())
        a = rng.uniform(0, 2 * math.pi)
        if solid_core is not None:
            px = x + rng.uniform(-1, 1) * (solid_core[0] / 2 + 0.3)
            py = y + rng.uniform(-1, 1) * (solid_core[1] / 2 + 0.3)
            px, py = (x + (px - x) * math.cos(solid_core[2]) - (py - y) * math.sin(solid_core[2]),
                      y + (px - x) * math.sin(solid_core[2]) + (py - y) * math.cos(solid_core[2]))
        else:
            px, py = x + r * math.cos(a), y + r * math.sin(a)
        prof = height * max(0.15, 1 - math.hypot(px - x, py - y) / max(radius, 0.1))
        sz = (rng.uniform(0.3, 1.1), rng.uniform(0.3, 0.9), max(rng.uniform(0.2, 0.6), RUBBLE_MIN_HEIGHT_M))
        z = max(sz[2] / 2, prof - sz[2] / 2)
        rpy = (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-math.pi, math.pi))
        row = [px, py, z, *sz, *rpy]
        if solid_core is None and not scene.placer.box_free([px, py, z, sz[0], sz[1], sz[2], 0, 0, rpy[2]], 0.0,
                                                            ignore_reserved):
            continue
        mat = str(rng.choice(['rubble', 'rubble', 'concrete', 'brick', 'brick_grey', 'concrete_dark']))
        group.box(row[:3], row[3:6], None, rpy=row[6:9], tag='rubble')
        rubble_chunk(group, rng, row, mat)
        placed.append(row)
    for row in placed:
        scene.placer.mark_box([row[0], row[1], row[2], row[3], row[4], row[5], 0, 0, row[8]])
    for _ in range(rocks):
        a = rng.uniform(0, 2 * math.pi)
        r = radius * 0.6 * math.sqrt(rng.random())
        rock(scene, cat, x + r * math.cos(a), y + r * math.sin(a), float(rng.uniform(0.6, 1.5)),
             check=solid_core is None, ignore_reserved=ignore_reserved)
    # dusty ground patch
    group.mesh('rubble').add_blob((x, y), radius + 0.6, rng, z=0.02)
    return placed


def fire(scene, x, y, size=1.0, base='debris', smoke=True, light=True):
    """Burning debris pile: hot thermal core + flames + smoke + flickering light."""
    rng = scene.rng
    uid = scene.uid('fire')
    t_core = float(rng.uniform(750, 900))
    vis = [f'<visual name="embers"><pose>0 0 0.06 0 0 0</pose><geometry><cylinder><radius>{0.55 * size + 0.2:.2f}'
           f'</radius><length>0.12</length></cylinder></geometry><material><ambient>0.3 0.1 0.03 1</ambient>'
           f'<diffuse>0.3 0.1 0.03 1</diffuse><emissive>1.0 0.35 0.05 1</emissive></material>'
           f'{thermal_plugin(t_core)}</visual>']
    cols = []
    if base == 'debris':
        for k in range(3):
            a = rng.uniform(0, math.pi)
            L = 0.9 + 0.5 * size
            vis.append(f'<visual name="log{k}"><pose>{rng.uniform(-0.2, 0.2):.2f} {rng.uniform(-0.2, 0.2):.2f} '
                       f'{0.15 + 0.12 * k:.2f} 0 {rng.uniform(-0.3, 0.3):.2f} {a:.2f}</pose><geometry><box><size>{L:.2f}'
                       f' 0.25 0.22</size></box></geometry><material><ambient>0.12 0.08 0.05 1</ambient><diffuse>'
                       f'0.12 0.08 0.05 1</diffuse><emissive>0.35 0.08 0.0 1</emissive></material>'
                       f'{thermal_plugin(t_core - 150)}</visual>')
        s = 0.9 + 0.5 * size
        cols.append(f'<collision name="c"><pose>0 0 0.25 0 0 0</pose><geometry><box><size>{s:.2f} {s:.2f} 0.5'
                    f'</size></box></geometry></collision>')
        scene.placer.mark_box([x, y, 0.25, s, s, 0.5, 0, 0, 0])
        scene.extra_boxes.append(([x, y, 0.25, s, s, 0.5, 0, 0, 0], 'fire'))
        kit.place(scene.group('fire_debris'), 'fire_debris', (x, y, 0.0), float(rng.uniform(0, 6.28)), scale=(s, s, 0.7))
    sdf = (f'<model name="{uid}"><static>true</static><pose>{x:.3f} {y:.3f} 0 0 0 0</pose>'
           f'{label_plugin(LABEL_IDS["fire"])}<link name="link">{"".join(cols)}{"".join(vis)}</link></model>')
    scene.models.append(sdf)
    zf = 0.3 if base == 'debris' else 1.2
    scene.models.append(emitter(uid + '_flames', (x, y, zf), 'fire', size))
    if smoke:
        scene.models.append(emitter(uid + '_smoke', (x, y, zf + 1.4), 'smoke', size))
    if light:
        scene.lights.append(point_light(uid + '_light', (x, y, 1.5), rng=6 + 4 * size, intensity=1.5))
    rec = dict(id=uid, x=float(x), y=float(y), size=float(size), temperature=t_core,
               hazard_radius=float(1.4 + 0.8 * size), danger_radius=float(0.9 + 0.5 * size))
    scene.fires.append(rec)
    return rec


def survivor_pose(entry, posture, x, y, yaw):
    """Model pose and world body box for a survivor model. (x, y) = body centre on the ground."""
    mn, mx = np.array(entry['min']), np.array(entry['max'])
    if posture == 'lying':
        # roll -90 deg: body length (z) -> +y, depth (y) -> -z
        length = mx[2] - mn[2]
        ox, oy = -math.sin(yaw) * (-length / 2), math.cos(yaw) * (-length / 2)
        pose = (x + ox, y + oy, float(mx[1]) + 0.01, -math.pi / 2, 0.0, yaw)
        size = (mx[0] - mn[0], length, mx[1] - mn[1])
        row = [x, y, size[2] / 2, size[0] * 0.8, size[1], size[2], 0, 0, yaw]
    else:
        pose = (x, y, 0.0, 0.0, 0.0, yaw)
        size = mx - mn
        row = catalog_box(entry, pose, shrink=1.0)
        row[3] *= 0.8
    return pose, row


def survivor(scene, cat, sid, model_name, posture, x, y, yaw, decoy=False):
    e = cat[model_name]
    pose, row = survivor_pose(e, posture, x, y, yaw)
    if decoy:
        mesh = f'model://{model_name}/{e["mesh"]}'
        mp = e.get('mesh_pose', (0, 0, 0, 0, 0, 0))
        sdf = (f'<model name="{sid}"><static>true</static><pose>{fmt(pose)}</pose>'
               f'{label_plugin(LABEL_IDS["mannequin"])}<link name="link"><collision name="c"><pose>'
               f'{fmt(((np.array(e["min"]) + np.array(e["max"])) / 2))} 0 0 0</pose><geometry><box><size>'
               f'{fmt((np.array(e["max"]) - np.array(e["min"])) * np.array([0.8, 0.8, 1.0]))}</size></box>'
               f'</geometry></collision><visual name="visual"><pose>{fmt(mp)}</pose><geometry><mesh><uri>{mesh}</uri>'
               f'</mesh></geometry></visual></link></model>')
    else:
        sdf = include(f'model://{model_name}', sid, pose, label_plugin(LABEL_IDS['survivor']))
    scene.add_model(sdf, [row], tag='decoy' if decoy else 'survivor')
    torso_z = 0.2 if posture == 'lying' else (0.45 if posture == 'sitting' else 1.05)
    return dict(id=sid, model=model_name, posture=posture, x=float(x), y=float(y), z=torso_z, yaw=float(yaw),
                row=[float(v) for v in row], pose=[float(v) for v in pose])
