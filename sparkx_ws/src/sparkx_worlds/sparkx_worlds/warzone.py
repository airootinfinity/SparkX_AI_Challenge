"""Bombardment dressing: everything that turns a tidy generated city into one that has been shelled.

None of this changes where the robot can drive. Ground decals are paper-thin, loose street debris
is under 9 cm (the rover's chassis clears 12 cm and its laser scan ignores anything below 15 cm),
wall decals are flat on walls that stay solid, and ruined shells stand outside the arena or above
head height.
"""
import math

import numpy as np

from . import kit
from .sdfgen import LIGHTING, TEX, fmt, sky_dome

SIDES = ('-x', '+x', '-y', '+y')
DEBRIS_DECALS = ['decal_debris_a', 'decal_debris_b', 'decal_debris_c']
CRATER_DECALS = ['decal_crater_a', 'decal_crater_b']
CHUNKS = ['chunk_a', 'chunk_b', 'chunk_c', 'chunk_d', 'chunk_e', 'chunk_f', 'slab_a', 'slab_b']


def damage_at(scene, x, y, lay):
    ex, ey, _ = scene.epicenter
    return float(np.clip(1.15 - math.hypot(x - ex, y - ey) / (0.7 * math.hypot(lay.W, lay.H)), 0.12, 1.0))


# ------------------------------------------------------------------------------------- ruined shells
def ruined_shell(g, rng, cx, cy, w, d, height, facade, yaw=0.0, damage=0.6, cell=3.5, min_h=2.0, heap=True):
    """A bombed-out building drawn as a grid of bays, each standing to a different height: a deep
    bite where it was hit, ragged storeys around it, slabs and rubble where the rest came down.
    Visual only."""
    nx, ny = max(1, int(round(w / cell))), max(1, int(round(d / cell)))
    bx, by = float(rng.uniform(0, nx)), float(rng.uniform(0, ny))          # where the shell struck
    if rng.random() < 0.6:                                                 # usually a corner or an edge
        bx, by = float(rng.choice([0, nx])), float(rng.choice([0, ny])) if rng.random() < 0.6 else by
    reach = max(nx, ny) * float(rng.uniform(0.55, 1.1))
    c, s = math.cos(yaw), math.sin(yaw)
    cw, cd = w / nx, d / ny
    lowest = None
    for i in range(nx):
        for j in range(ny):
            dist = math.hypot(i + 0.5 - bx, j + 0.5 - by) / max(reach, 1e-3)
            keep = np.clip(1.0 - damage * (1.25 - dist) + float(rng.normal(0, 0.12)), 0.0, 1.0)
            h = max(min_h, round(height * keep / 1.75) * 1.75 + float(rng.uniform(-0.5, 0.4)))
            h = min(h, height)
            lx, ly = (i + 0.5) * cw - w / 2, (j + 0.5) * cd - d / 2
            px, py = cx + lx * c - ly * s, cy + lx * s + ly * c
            g.box((px, py, h / 2), (cw, cd, h), facade, rpy=(0, 0, yaw), collide=False, faces=SIDES)
            g.box((px, py, h / 2), (cw, cd, h), 'concrete_dark', rpy=(0, 0, yaw), collide=False, faces=('top',))
            if h < height - 1.0 and rng.random() < 0.5:                    # broken masonry and bars on the stump
                kit.fit(g, str(rng.choice(CHUNKS)), [px, py, h + 0.25, cw * float(rng.uniform(0.5, 0.95)),
                                                     cd * float(rng.uniform(0.5, 0.95)), float(rng.uniform(0.4, 1.1)),
                                                     float(rng.uniform(-0.3, 0.3)), float(rng.uniform(-0.3, 0.3)),
                                                     float(rng.uniform(0, 3.1))],
                        roles={'concrete': str(rng.choice(['rubble', 'concrete', 'brick']))})
            if lowest is None or h < lowest[0]:
                lowest = (h, px, py)
    if heap and lowest is not None:                                        # the collapsed part, as a talus of slabs
        _, hx, hy = lowest
        for _ in range(int(rng.integers(6, 12))):
            r, a = float(rng.uniform(0, 0.55 * max(cw, cd) * 2)), float(rng.uniform(0, 2 * math.pi))
            sz = (float(rng.uniform(1.2, 3.6)), float(rng.uniform(1.0, 2.6)), float(rng.uniform(0.4, 1.3)))
            kit.fit(g, str(rng.choice(CHUNKS)), [hx + r * math.cos(a), hy + r * math.sin(a), sz[2] * 0.45 + float(rng.uniform(0, 1.0)),
                                                 *sz, float(rng.uniform(-0.6, 0.6)), float(rng.uniform(-0.6, 0.6)),
                                                 float(rng.uniform(0, 3.1))],
                    roles={'concrete': str(rng.choice(['rubble', 'concrete', 'concrete_dark']))})


def jagged_wall(g, rng, start, direction, length, thickness, base_h, facade, normal_yaw, cell=3.5, extra=(0.0, 7.0),
                inner_face=0.0):
    """A boundary terrace with a broken skyline: every bay rises to its own height above base_h."""
    n = max(1, int(round(length / cell)))
    cw = length / n
    for k in range(n):
        h = base_h + (float(rng.choice([0.0, 0.0, 1.75, 3.5, 3.5, 7.0])) if rng.random() < 0.8 else float(rng.uniform(*extra)))
        h += float(rng.uniform(-0.4, 0.4))
        px = start[0] + direction[0] * (k + 0.5) * cw
        py = start[1] + direction[1] * (k + 0.5) * cw
        size = (cw if direction[0] else thickness, cw if direction[1] else thickness, h)
        g.box((px, py, h / 2), size, facade if k % 3 or rng.random() < 0.5 else str(rng.choice(['facade_a', 'facade_b', 'facade_c', 'facade_d', 'facade_e'])),
              collide=False, faces=SIDES)
        g.box((px, py, h / 2), size, 'concrete_dark', collide=False, faces=('top',))
        if rng.random() < 0.35:
            kit.fit(g, str(rng.choice(CHUNKS)), [px, py, h + 0.3, size[0] * 0.8, size[1] * 0.9, float(rng.uniform(0.5, 1.2)),
                                                 float(rng.uniform(-0.3, 0.3)), float(rng.uniform(-0.3, 0.3)), 0.0],
                    roles={'concrete': 'rubble'})


# ------------------------------------------------------------------------------------- wall decals
def wall_decal(g, name, x, y, z, yaw, w, h, off=0.03):
    g.mesh(name).add_panel((x + off * math.cos(yaw), y + off * math.sin(yaw), z), w, h, yaw)


def scar_wall(g, rng, x, y, yaw, z_lo, z_hi, damage, length=6.0):
    """Shell strikes, soot and cracks on a stretch of wall centred at (x, y) facing `yaw`."""
    tx, ty = -math.sin(yaw), math.cos(yaw)
    for _ in range(int(rng.poisson(0.5 + 1.6 * damage))):
        s = float(rng.uniform(-length / 2, length / 2))
        z = float(rng.uniform(z_lo, z_hi))
        kind = rng.random()
        if kind < 0.45:
            sz = float(rng.uniform(1.6, 3.2))
            wall_decal(g, str(rng.choice(['decal_wallhole_a', 'decal_wallhole_b'])), x + s * tx, y + s * ty, z, yaw, sz, sz)
        elif kind < 0.75:
            wall_decal(g, 'decal_cracks_a', x + s * tx, y + s * ty, z, yaw, float(rng.uniform(2.0, 3.6)), float(rng.uniform(2.0, 3.6)),
                       off=0.02)
        else:
            wall_decal(g, str(rng.choice(['decal_soot_a', 'decal_soot_b'])), x + s * tx, y + s * ty, z + 0.6, yaw,
                       float(rng.uniform(1.4, 2.4)), float(rng.uniform(2.2, 3.6)), off=0.025)


# ------------------------------------------------------------------------------------- streets and yards
def ground_decal(g, name, x, y, size, yaw, z=0.028):
    g.mesh(name).add_quad_centered((x, y), size, size, yaw, z)


def loose_debris(g, rng, x, y, spread, n):
    """Fist- to brick-sized rubble lying on the ground: under 9 cm, driven over without contact."""
    for _ in range(n):
        r, a = spread * math.sqrt(float(rng.random())), float(rng.uniform(0, 2 * math.pi))
        sz = (float(rng.uniform(0.1, 0.34)), float(rng.uniform(0.08, 0.26)), float(rng.uniform(0.035, 0.085)))
        kit.fit(g, str(rng.choice(CHUNKS[:6])), [x + r * math.cos(a), y + r * math.sin(a), sz[2] / 2, *sz, 0.0, 0.0,
                                                 float(rng.uniform(0, 3.1))],
                roles={'concrete': str(rng.choice(['rubble', 'concrete', 'brick', 'concrete_dark'])), 'rebar': None})


def dress_streets(scene, lay, rng):
    """Shell craters, debris fields, scorch marks and loose rubble on every street and block."""
    g = scene.group('war_ground')
    st = scene.placer
    sx, sy = None, None
    for blk in scene.blocks:
        if blk['type'] == 'base':
            x0, y0, x1, y1 = blk['rect']
            sx, sy = x0 + 8.0, y0 + 8.0

    def clear_of_base(x, y, r):
        return sx is None or math.hypot(x - sx, y - sy) > 6.5 + r

    for seg in scene.street_segments:
        x0, y0, x1, y1 = seg['rect']
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dmg = damage_at(scene, cx, cy, lay)
        for _ in range(int(rng.poisson(0.5 + 1.8 * dmg))):                 # shell craters in the carriageway
            x, y = float(rng.uniform(x0 + 1.5, x1 - 1.5)), float(rng.uniform(y0 + 1.5, y1 - 1.5))
            size = float(rng.uniform(3.4, 6.2))
            if clear_of_base(x, y, size / 2):
                if rng.random() < 0.5:
                    ground_decal(g, 'decal_scorch_a', x, y, size * 1.5, float(rng.uniform(0, 6.28)), z=0.022)
                ground_decal(g, str(rng.choice(CRATER_DECALS)), x, y, size, float(rng.uniform(0, 6.28)))
                loose_debris(g, rng, x, y, size * 0.7, int(rng.integers(6, 14)))
        for _ in range(int(rng.poisson(2.0 + 5.0 * dmg))):                 # debris fields, thickest by the buildings
            along = seg['axis'] == 'x'
            edge = float(rng.choice([-1, 1])) * float(rng.uniform(0.15, 0.5)) * lay.S if rng.random() < 0.7 else float(rng.uniform(-0.3, 0.3)) * lay.S
            t = float(rng.uniform(0.03, 0.97))
            x, y = (x0 + t * (x1 - x0), cy + edge) if along else (cx + edge, y0 + t * (y1 - y0))
            size = float(rng.uniform(2.6, 5.0))
            if clear_of_base(x, y, size / 2):
                ground_decal(g, str(rng.choice(DEBRIS_DECALS)), x, y, size, float(rng.uniform(0, 6.28)), z=0.026)
                loose_debris(g, rng, x, y, size * 0.5, int(rng.integers(3, 9)))
    for k, l, (x0, y0, x1, y1) in lay.intersections():
        dmg = damage_at(scene, (x0 + x1) / 2, (y0 + y1) / 2, lay)
        if rng.random() < 0.3 + 0.5 * dmg:
            x, y = float(rng.uniform(x0 + 2, x1 - 2)), float(rng.uniform(y0 + 2, y1 - 2))
            if clear_of_base(x, y, 3.0):
                ground_decal(g, str(rng.choice(CRATER_DECALS)), x, y, float(rng.uniform(4.0, 6.5)), float(rng.uniform(0, 6.28)))
    for blk in scene.blocks:                                               # yards, plazas and the crater block
        x0, y0, x1, y1 = blk['rect']
        dmg = blk['damage']
        n = 2 if blk['type'] == 'base' else int(rng.poisson(3.0 + 6.0 * dmg))
        for _ in range(n):
            x, y = float(rng.uniform(x0 + 1.5, x1 - 1.5)), float(rng.uniform(y0 + 1.5, y1 - 1.5))
            size = float(rng.uniform(2.4, 4.6))
            if not clear_of_base(x, y, size / 2) or any(b.contains(x, y, -1.0) for b in scene.buildings):
                continue
            ground_decal(g, str(rng.choice(DEBRIS_DECALS + CRATER_DECALS[:1])), x, y, size, float(rng.uniform(0, 6.28)), z=0.026)
            loose_debris(g, rng, x, y, size * 0.5, int(rng.integers(2, 7)))
    del st


# ------------------------------------------------------------------------------------- sky and smoke
def sky_model(scene, lay, lighting, mesh_dir, uri_prefix):
    """The war-sky dome as its own static model (unlit, tinted for the lighting preset)."""
    radius = 0.5 * math.hypot(lay.W, lay.H) + 230.0
    mesh, tint = sky_dome((lay.W / 2, lay.H / 2), radius, lighting)
    fn = f'{scene.name}_sky_dome.obj'
    mesh.write(f'{mesh_dir}/{fn}')
    return (f'<model name="sky_dome"><static>true</static><link name="link"><visual name="sky"><cast_shadows>false</cast_shadows>'
            f'<geometry><mesh><uri>{uri_prefix}{fn}</uri></mesh></geometry><material><ambient>0 0 0 1</ambient>'
            f'<diffuse>0 0 0 1</diffuse><specular>0 0 0 1</specular><emissive>{fmt(tint)} 1</emissive><pbr><metal>'
            f'<emissive_map>{TEX}sky_war.jpg</emissive_map><roughness>1</roughness><metalness>0</metalness></metal></pbr>'
            f'</material></visual></link></model>')
