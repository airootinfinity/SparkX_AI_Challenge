"""SDF emission helpers for SparkX worlds.

Static geometry is batched per material into OBJ meshes (few draw calls) while collisions are
kept as simple boxes (fast, deterministic physics and exact ground-truth maps).
"""
import math
import os
from xml.sax.saxutils import escape

import numpy as np

from . import pbr
from .objmesh import ObjMesh

TEX = 'model://sparkx_media/textures/'


def _mat(tex, nrm=None, rgh=None, rough=0.9, metal=0.0, tint=None, emis=None, tile=None, emis_map=None, shadows=True):
    return dict(tex=tex, nrm=nrm, rgh=rgh, rough=rough, metal=metal, tint=tint, emis=emis, tile=tile, emis_map=emis_map,
                shadows=shadows)


# name -> albedo / normal / roughness maps, scalar fallbacks, tint, emissive and the real-world size
# of one texture repeat ("tile", metres; None = the caller decides the UV scale).
MATERIALS = {}
for _n, _s in pbr.SURFACES.items():
    MATERIALS[_n] = _mat(f'{_n}.jpg', f'{_n}_n.jpg', f'{_n}_r.jpg', metal=_s.get('metal', 0.0), tile=_s['tile'])
for _n in ('asphalt_lane', 'crosswalk'):
    MATERIALS[_n] = _mat(f'{_n}.jpg', f'{_n}_n.jpg', f'{_n}_r.jpg')
for _n in pbr.FACADES:
    MATERIALS[_n] = _mat(f'{_n}.jpg', f'{_n}_n.jpg', f'{_n}_r.jpg', tile=pbr.FACADE_TILE)
for _c in pbr.COLORS:
    MATERIALS[f'container_{_c}'] = _mat(f'container_{_c}.jpg', 'container_n.jpg', 'container_r.jpg', metal=0.35,
                                        tile=pbr.FAMILIES['container']['tile'])
    MATERIALS[f'paint_{_c}'] = _mat(f'paint_{_c}.jpg', 'paint_n.jpg', 'paint_r.jpg', metal=0.3,
                                    tile=pbr.FAMILIES['paint']['tile'])
    MATERIALS[f'fabric_{_c}'] = _mat(f'fabric_{_c}.jpg', 'fabric_n.jpg', None, rough=1.0,
                                     tile=pbr.FAMILIES['fabric']['tile'])
MATERIALS['burnt_metal'] = _mat('burnt_metal.jpg', 'paint_n.jpg', 'paint_r.jpg', metal=0.3, tile=2.0)
MATERIALS['embers'] = _mat('scorched.jpg', 'scorched_n.jpg', None, rough=1.0, tint=(0.35, 0.12, 0.05),
                           emis=(0.9, 0.25, 0.02), tile=2.0)
# flat-colour materials (no texture) used by kit parts
for _n, _c, _r, _m in (('glass', (0.05, 0.07, 0.09), 0.08, 0.0), ('rubber', (0.04, 0.04, 0.04), 0.95, 0.0),
                       ('lamp_glass', (0.82, 0.82, 0.76), 0.3, 0.0), ('cardboard', (0.56, 0.43, 0.28), 0.95, 0.0),
                       ('brand_crimson', (0.898, 0.008, 0.153), 0.5, 0.1), ('brand_ink', (0.098, 0.098, 0.098), 0.5, 0.2),
                       ('brand_offwhite', (0.941, 0.937, 0.949), 0.6, 0.0)):
    MATERIALS[_n] = _mat(None, rough=_r, metal=_m, tint=_c)
MATERIALS['charred'] = _mat('scorched.jpg', 'scorched_n.jpg', None, rough=1.0, tint=(0.35, 0.33, 0.32), tile=1.0)
# Blender-rendered cut-out decals (tools/blender/render_decals.py) and generated soot / crack decals.
# Their alpha channel is alpha-tested by the renderer; they never cast shadows.
DECALS = ['decal_debris_a', 'decal_debris_b', 'decal_debris_c', 'decal_crater_a', 'decal_crater_b', 'decal_wallhole_a',
          'decal_wallhole_b', 'decal_soot_a', 'decal_soot_b', 'decal_cracks_a', 'decal_scorch_a']
for _n in DECALS:
    MATERIALS[_n] = _mat(f'{_n}.png', rough=1.0, shadows=False)
# sky dome: unlit panorama (tinted per lighting preset through the emissive colour)
MATERIALS['sky_war'] = _mat(None, rough=1.0, tint=(0, 0, 0), emis=(1, 1, 1), emis_map='sky_war.jpg', shadows=False)
# numbered location markers: the white of the board glows faintly so tags stay readable at dusk and in smoke
MATERIALS['marker_tags'] = _mat('marker_tags.png', rough=0.8, emis=(0.3, 0.3, 0.3), emis_map='marker_tags.png')
MATERIALS['basepad'] = _mat('basepad.jpg', 'basepad_n.jpg', 'basepad_r.jpg')
for _n in ('brand_banner', 'brand_billboard', 'brand_airoot', 'brand_stemlearn', 'brand_gantry', 'brand_flag_airoot',
           'brand_flag_stemlearn'):
    MATERIALS[_n] = _mat(f'{_n}.jpg', rough=0.75, emis=(0.04, 0.04, 0.04))
for _l in ('pharmacy', 'school', 'hotel', 'bank', 'police', 'cafe', 'hospital', 'market'):
    MATERIALS[f'sign_{_l}'] = _mat(f'sign_{_l}.png', rough=0.6, emis=(0.08, 0.08, 0.08))


def fmt(v):
    return ' '.join(f'{float(x):.4f}'.rstrip('0').rstrip('.') if abs(float(x)) > 1e-9 else '0' for x in v)


def material_xml(name):
    m = MATERIALS[name]
    d = m['tint'] or (1, 1, 1)
    e = f'<emissive>{fmt(m["emis"])} 1</emissive>' if m['emis'] else ''
    maps = f'<albedo_map>{TEX}{m["tex"]}</albedo_map>' if m['tex'] else ''
    if m.get('emis_map'):
        maps += f'<emissive_map>{TEX}{m["emis_map"]}</emissive_map>'
    if m['nrm']:
        maps += f'<normal_map>{TEX}{m["nrm"]}</normal_map>'
    if m['rgh']:
        maps += f'<roughness_map>{TEX}{m["rgh"]}</roughness_map>'
    return (f'<material><ambient>{fmt(d)} 1</ambient><diffuse>{fmt(d)} 1</diffuse><specular>0.1 0.1 0.1 1</specular>{e}'
            f'<pbr><metal>{maps}<roughness>{m["rough"]}</roughness>'
            f'<metalness>{m["metal"]}</metalness></metal></pbr></material>')


def label_plugin(label_id):
    return f'<plugin filename="gz-sim-label-system" name="gz::sim::systems::Label"><label>{int(label_id)}</label></plugin>'


def thermal_plugin(temperature):
    return (f'<plugin filename="gz-sim-thermal-system" name="gz::sim::systems::Thermal">'
            f'<temperature>{temperature:.1f}</temperature></plugin>')


class StaticGroup:
    """A static model: batched visual meshes (one per material) + box collisions."""

    def __init__(self, name):
        self.name = name
        self.meshes = {}          # material -> ObjMesh
        self.collisions = []      # rows [cx cy cz sx sy sz r p y]
        self.col_tags = []        # tag per collision (for ground truth / occluders)
        self.extra_visuals = []   # raw SDF visual strings (thermal cores, labelled items)
        self.plugins = ''         # model-level plugins (e.g. semantic label)
        self.pose = None

    def mesh(self, material):
        if material not in self.meshes:
            self.meshes[material] = ObjMesh(tile=MATERIALS[material]['tile'])
        return self.meshes[material]

    def box(self, center, size, material=None, rpy=(0, 0, 0), collide=True, tile=2.0, tag='solid', faces='all'):
        if material:
            self.mesh(material).add_box(center, size, rpy, tile=tile, faces=faces)
        if collide:
            self.collisions.append([*center, *size, *rpy])
            self.col_tags.append(tag)

    def to_sdf(self, mesh_dir, uri_prefix, world_name):
        vis = []
        for mat, m in sorted(self.meshes.items()):
            if m.empty():
                continue
            fn = f'{world_name}_{self.name}_{mat}.obj'
            m.write(os.path.join(mesh_dir, fn))
            shadows = 'true' if MATERIALS[mat].get('shadows', True) else 'false'
            vis.append(f'<visual name="v_{mat}"><cast_shadows>{shadows}</cast_shadows><geometry><mesh>'
                       f'<uri>{uri_prefix}{fn}</uri></mesh></geometry>{material_xml(mat)}</visual>')
        cols = [f'<collision name="c{i}"><pose>{fmt(r[:3])} {fmt(r[6:9])}</pose><geometry><box><size>{fmt(r[3:6])}'
                f'</size></box></geometry></collision>' for i, r in enumerate(self.collisions)]
        body = '\n'.join(cols + vis + self.extra_visuals)
        return (f'<model name="{self.name}"><static>true</static>{self.plugins}<link name="link">\n{body}\n'
                f'</link></model>')


def include(uri, name, pose, plugins=''):
    return (f'<include><uri>{uri}</uri><name>{name}</name><pose>{fmt(pose)}</pose>{plugins}</include>')


def mesh_model(name, mesh_uri, pose, scale=1.0, material=None, collision_box=None, plugins='', visual_plugins=''):
    """Inline static model around an existing mesh (e.g. mannequins, burnt cars, boulders)."""
    col = ''
    if collision_box is not None:
        c, s = collision_box
        col = (f'<collision name="c"><pose>{fmt(c)} 0 0 0</pose><geometry><box><size>{fmt(s)}</size></box>'
               f'</geometry></collision>')
    mat = material_xml(material) if material else ''
    return (f'<model name="{name}"><static>true</static><pose>{fmt(pose)}</pose>{plugins}<link name="link">{col}'
            f'<visual name="visual"><geometry><mesh><uri>{mesh_uri}</uri><scale>{fmt([scale] * 3)}</scale></mesh>'
            f'</geometry>{mat}{visual_plugins}</visual></link></model>')


RAMP_PREFIX = 'meshes/'  # kept for API compatibility (colour ramps are no longer used)
COLOR_GRADIENT = {  # (start rgba, end rgba) - colour_range_image only accepts absolute paths in gz-sim 8
    'fire': ((1.0, 0.85, 0.45, 1.0), (0.85, 0.22, 0.04, 1.0)),
    'smoke': ((0.28, 0.27, 0.26, 1.0), (0.55, 0.55, 0.55, 1.0)),
    'dust': ((0.62, 0.57, 0.47, 1.0), (0.76, 0.72, 0.64, 1.0)),
}


def emitter(name, pose, kind, size=1.0, scatter=None, ramp_prefix=None):
    """Particle emitter. kind: fire | smoke | dust. Emits along world +Z."""
    del ramp_prefix
    x, y, z = pose
    if kind == 'fire':
        p = dict(size=f'0.2 {size} {size}', psize=f'{0.55 * size + 0.15:.2f}', life=1.1, vmin=0.7, vmax=1.3,
                 scale=0.25, rate=int(30 + 25 * size), tex='flame.png', ramp='fire_colors.png', scat=0.02)
    elif kind == 'smoke':
        p = dict(size=f'0.3 {size} {size}', psize=f'{1.2 * size + 0.4:.2f}', life=9.0, vmin=0.35, vmax=0.7,
                 scale=0.7, rate=int(6 + 5 * size), tex='smoke.png', ramp='smoke_colors.png', scat=0.25)
    else:
        p = dict(size=f'0.3 {size} {size}', psize=f'{1.0 * size:.2f}', life=7.0, vmin=0.1, vmax=0.3,
                 scale=0.4, rate=int(3 + 3 * size), tex='dust.png', ramp='dust_colors.png', scat=0.1)
    if scatter is not None:
        p['scat'] = scatter
    ps = p['psize']
    c0, c1 = COLOR_GRADIENT[kind]
    return (f'<model name="{name}"><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} 0 0 0</pose><link name="link">'
            f'<particle_emitter name="emitter" type="box"><pose>0 0 0 0 -1.5707963 0</pose>'
            f'<emitting>true</emitting><size>{p["size"]}</size><particle_size>{ps} {ps} {ps}</particle_size>'
            f'<lifetime>{p["life"]}</lifetime><min_velocity>{p["vmin"]}</min_velocity>'
            f'<max_velocity>{p["vmax"]}</max_velocity><scale_rate>{p["scale"]}</scale_rate><rate>{p["rate"]}</rate>'
            f'<particle_scatter_ratio>{p["scat"]}</particle_scatter_ratio>'
            f'<color_start>{fmt(c0)}</color_start><color_end>{fmt(c1)}</color_end>'
            f'<material><diffuse>1 1 1</diffuse><specular>0 0 0</specular><pbr><metal>'
            f'<albedo_map>{TEX}{p["tex"]}</albedo_map></metal></pbr></material>'
            f'</particle_emitter></link></model>')


def point_light(name, pos, color=(1.0, 0.55, 0.2), rng=10.0, intensity=1.0):
    return (f'<light type="point" name="{name}"><pose>{fmt(pos)} 0 0 0</pose><diffuse>{fmt(color)} 1</diffuse>'
            f'<specular>0.1 0.1 0.1 1</specular><attenuation><range>{rng}</range><constant>0.4</constant>'
            f'<linear>0.08</linear><quadratic>0.02</quadratic></attenuation><cast_shadows>false</cast_shadows>'
            f'<intensity>{intensity}</intensity></light>')


LIGHTING = {
    # ambient, background (haze colour), sun diffuse, sun direction, sun shadows, sky-dome tint
    # A city under bombardment: the air is full of smoke and dust, the sun is low and yellowed.
    'day': ((0.52, 0.50, 0.47), (0.56, 0.52, 0.47), (1.0, 0.90, 0.74), (-0.5, 0.35, -0.72), True, (1.0, 0.97, 0.92)),
    'afternoon': ((0.44, 0.40, 0.35), (0.60, 0.50, 0.40), (1.0, 0.76, 0.50), (-0.75, -0.35, -0.45), True, (1.0, 0.86, 0.70)),
    'smoky': ((0.40, 0.39, 0.38), (0.40, 0.38, 0.36), (0.60, 0.55, 0.48), (-0.3, 0.2, -0.9), True, (0.62, 0.60, 0.58)),
    'dusk': ((0.15, 0.14, 0.16), (0.22, 0.17, 0.17), (0.50, 0.30, 0.20), (-0.85, 0.2, -0.25), False, (0.42, 0.30, 0.28)),
}


def sky_dome(center, radius, lighting):
    """Visual-only dome carrying the Blender-rendered war sky (smoke, haze, a ruined skyline). It is
    far beyond LiDAR range and unlit, so it never affects sensing other than the colour camera."""
    amb, bg, sun, sdir, shadows, tint = LIGHTING[lighting]
    m = ObjMesh()
    seg, rings = 64, 10
    lat0, lat1 = math.radians(-2.0), math.radians(88.0)
    sun_az = math.atan2(-sdir[1], -sdir[0])                      # where the light comes from
    yaw0 = sun_az - 2 * math.pi * SKY_SUN_U                       # put the panorama's sun there
    grid = []
    for j in range(rings + 1):
        lat = lat0 + (lat1 - lat0) * j / rings
        row = []
        for i in range(seg + 1):
            a = yaw0 + 2 * math.pi * i / seg
            row.append(((center[0] + radius * math.cos(lat) * math.cos(a), center[1] + radius * math.cos(lat) * math.sin(a),
                         radius * math.sin(lat)), (i / seg, j / rings)))
        grid.append(row)
    for j in range(rings):
        for i in range(seg):
            q = [grid[j][i + 1], grid[j][i], grid[j + 1][i], grid[j + 1][i + 1]]      # wound to face inwards
            m.add_poly([p for p, _ in q], [uv for _, uv in q])
    return m, tint


SKY_SUN_U = 0.07   # horizontal position (0..1) of the sun in sky_war.jpg; measured by textures.sky_panorama()


def world_header(name, lighting='day', step=0.004):
    amb, bg, sun, sdir, shadows, _tint = LIGHTING[lighting]
    sky = ''   # the stock blue sky is replaced by the war-sky dome (see sky_dome)
    return f'''<?xml version="1.0"?>
<!-- SparkX Disaster Response world "{escape(name)}" (generated, see sparkx_worlds/generate_world) -->
<sdf version="1.9">
<world name="{name}">
  <physics name="default_physics" type="dart">
    <max_step_size>{step}</max_step_size>
    <real_time_factor>1.0</real_time_factor>
    <real_time_update_rate>{int(round(1.0 / step))}</real_time_update_rate>
  </physics>
  <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
  <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
  <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
  <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>
  <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
  <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
  <plugin filename="gz-sim-particle-emitter-system" name="gz::sim::systems::ParticleEmitter"/>
  <gravity>0 0 -9.81</gravity>
  <scene>
    <ambient>{fmt(amb)} 1</ambient>
    <background>{fmt(bg)} 1</background>
    <shadows>{str(shadows).lower()}</shadows>
    <grid>false</grid>
    {sky}
  </scene>
  <atmosphere type="adiabatic">
    <temperature>298.0</temperature>
    <temperature_gradient>0.0065</temperature_gradient>
  </atmosphere>
  <light type="directional" name="sun">
    <cast_shadows>{str(shadows).lower()}</cast_shadows>
    <pose>0 0 80 0 0 0</pose>
    <diffuse>{fmt(sun)} 1</diffuse>
    <specular>0.2 0.2 0.2 1</specular>
    <direction>{fmt(np.asarray(sdir) / np.linalg.norm(sdir))}</direction>
  </light>
  <model name="ground_plane">
    <static>true</static>
    <link name="link">
      <collision name="collision">
        <geometry><plane><normal>0 0 1</normal><size>1000 1000</size></plane></geometry>
        <surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface>
      </collision>
    </link>
  </model>
'''


def world_footer():
    return '</world>\n</sdf>\n'
