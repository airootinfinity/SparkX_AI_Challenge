"""Procedural landmarks from the published vocabulary. Each landmark is a separate static model
carrying a semantic Label (for the dataset bounding-box camera) and is registered in the scene."""
import math

import numpy as np

from . import kit
from .sdfgen import label_plugin
from .vocab import LABEL_IDS


def _new_group(scene, cls):
    g = scene.group(scene.uid(f'lm_{cls}'))
    g.plugins = label_plugin(LABEL_IDS[cls])
    return g


def _rot(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return x * c - y * s, x * s + y * c


def water_tank(scene, x, y, color, yaw=0.0):
    """Elevated cylindrical tank (d=2.6 m) on four braced legs; top at ~5.2 m."""
    g = _new_group(scene, 'water_tank')
    leg_h, r, th = 2.6, 1.3, 2.2
    for sx in (-1, 1):
        for sy in (-1, 1):
            lx, ly = _rot(sx * 0.95, sy * 0.95, yaw)
            g.box((x + lx, y + ly, leg_h / 2), (0.16, 0.16, leg_h), None, rpy=(0, 0, yaw), tag='landmark')
    g.box((x, y, (leg_h + 0.1) / 2), (0.16, 0.16, leg_h + 0.1), None, rpy=(0, 0, yaw), tag='landmark')   # outlet pipe
    g.box((x, y, leg_h + 0.1 + th / 2), (2 * r * 0.9, 2 * r * 0.9, th), None, rpy=(0, 0, yaw), tag='landmark')
    kit.place(g, 'water_tank', (x, y, 0.0), yaw, roles={'body': f'paint_{color}'})
    return scene.add_landmark('water_tank', color, x, y, 0.0, yaw, (2 * r, 2 * r, leg_h + th + 0.6),
                              model=g.name, footprint=[x, y, 1.3, 2.1, 2.1, 2.6, 0, 0, yaw])


def container(scene, x, y, color, yaw=0.0, damaged=False):
    """ISO 20 ft shipping container (6.06 x 2.44 x 2.59 m); `damaged` = blown over onto its side."""
    g = _new_group(scene, 'container')
    L, W, H = 6.06, 2.44, 2.59
    roles = {'body': f'paint_{color}'}
    if damaged:
        g.box((x, y, W / 2), (L, H, W), None, rpy=(0, 0, yaw), tag='landmark')
        ox, oy = _rot(0.0, H / 2, yaw)
        kit.place(g, 'container', (x + ox, y + oy, W / 2), roles=roles, rpy=(math.pi / 2, 0.0, yaw))
        return scene.add_landmark('container', color, x, y, 0.0, yaw, (L, H, W), model=g.name,
                                  footprint=[x, y, W / 2, L, H, W, 0, 0, yaw], tipped=True)
    g.box((x, y, H / 2), (L, W, H), None, rpy=(0, 0, yaw), tag='landmark')
    kit.place(g, 'container', (x, y, 0.0), yaw, roles=roles)
    return scene.add_landmark('container', color, x, y, 0.0, yaw, (L, W, H), model=g.name,
                              footprint=[x, y, H / 2, L, W, H, 0, 0, yaw], tipped=False)


def tent(scene, x, y, color, yaw=0.0, size=3.6):
    """Relief tent: canvas walls, sagging pyramid roof with a scalloped valance, corner poles."""
    g = _new_group(scene, 'tent')
    h_wall, h_peak = 1.8, 2.9
    g.box((x, y, h_wall / 2), (size, size, h_wall), None, rpy=(0, 0, yaw), tag='landmark')
    s = size / 3.6
    kit.place(g, 'tent', (x, y, 0.0), yaw, scale=(s, s, 1.0), roles={'canvas': f'fabric_{color}'})
    return scene.add_landmark('tent', color, x, y, 0.0, yaw, (size, size, h_peak), model=g.name,
                              footprint=[x, y, h_wall / 2, size, size, h_wall, 0, 0, yaw])


def fountain(scene, x, y):
    """Dry stone fountain: round basin, column and upper bowl."""
    g = _new_group(scene, 'fountain')
    s = 2 * 2.3 * 0.9
    g.box((x, y, 0.3), (s, s, 0.6), None, tag='landmark')
    g.box((x, y, 0.3), (s, s, 0.6), None, rpy=(0, 0, math.pi / 4), tag='landmark')
    g.box((x, y, 0.95), (0.9, 0.9, 1.9), None, tag='landmark')
    kit.place(g, 'fountain', (x, y, 0.0), 0.0)
    return scene.add_landmark('fountain', '', x, y, 0.0, 0.0, (4.6, 4.6, 1.9), model=g.name,
                              footprint=[x, y, 0.3, s, s, 0.6, 0, 0, 0])


def sign(scene, mesh_dir, uri_prefix, rec, building_id):
    """Shop sign plate on a facade. rec: dict(label, x, y, z, yaw(outward), w, h)."""
    from .objmesh import ObjMesh
    from .sdfgen import material_xml
    label = rec['label']
    g = _new_group(scene, 'sign')
    yaw, w, h = rec['yaw'], rec['w'], rec['h']
    x, y, z = rec['x'], rec['y'], rec['z']
    # backing plate (visual only, sits against the wall)
    g.box((x + 0.02 * math.cos(yaw), y + 0.02 * math.sin(yaw), z), (0.04, w + 0.12, h + 0.12), 'paint_black',
          rpy=(0, 0, yaw), collide=False)
    # front plate: one quad showing the sign texture, readable from the street
    nx, ny = math.cos(yaw), math.sin(yaw)
    q = ObjMesh()
    q.add_panel((x + 0.065 * nx, y + 0.065 * ny, z), w, h, yaw)
    fn = f'{scene.name}_{g.name}.obj'
    q.write(f'{mesh_dir}/{fn}')
    g.extra_visuals.append(f'<visual name="plate"><geometry><mesh><uri>{uri_prefix}{fn}</uri></mesh></geometry>'
                           f'{material_xml("sign_" + label.lower())}</visual>')
    return scene.add_landmark('sign', '', x, y, z, yaw, (0.1, w, h), label=label, model=g.name,
                              building=building_id, footprint=None)
