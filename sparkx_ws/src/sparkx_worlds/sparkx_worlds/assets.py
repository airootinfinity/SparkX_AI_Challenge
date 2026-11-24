"""Asset catalog and Fuel importer for SparkX worlds.

`import_assets()` downloads the required Gazebo Fuel models (CC0 / CC-BY, see ATTRIBUTION.md),
copies meshes + textures into self-contained local models under `models/`, downscales large
textures, adds thermal signatures to survivors, replaces mesh collisions by boxes, and creates
colour variants of cars. The resulting catalogue (`models/catalog.yaml`) stores extents that the
world generator uses for placement and ground-truth maps.
"""
import colorsys
import glob
import os
import shutil
import subprocess

import numpy as np
import yaml
from PIL import Image

from . import meshio

FUEL = 'https://fuel.gazebosim.org/1.0/OpenRobotics/models/'
CACHE = os.path.expanduser('~/.gz/fuel/fuel.gazebosim.org/openrobotics/models')

# kind: survivor | vehicle | prop | ruin | rock
ASSETS = {
    # ---------------- survivors (thermal ~305-310 K) ----------------
    'sparkx_survivor_randy': dict(
        fuel='Rescue Randy', kind='survivor', mesh='meshes/rescue_randy.dae',
        desc='adult manikin, hi-vis jacket', postures=['standing', 'lying'],
        material=dict(albedo='materials/textures/rescue_randy_albedo.png',
                      normal='materials/textures/rescue_randy_normal.png',
                      roughness='materials/textures/rescue_randy_roughness.png',
                      metalness='materials/textures/rescue_randy_metalness.png'),
        thermal=dict(heat_signature='materials/textures/RescueRandy_Thermal.png', max_temp=310.0)),
    'sparkx_survivor_randy_sitting': dict(
        fuel='Rescue Randy Sitting', kind='survivor', mesh='meshes/rescue_randy.dae',
        mesh_pose=(0, 0, -0.624, 0, 0, 0), desc='adult sitting, hi-vis jacket', postures=['sitting'],
        material=dict(albedo='materials/textures/RescueRandy_Diffuse.jpg'),
        thermal=dict(heat_signature='materials/textures/RescueRandy_Thermal.png', max_temp=308.0)),
    'sparkx_survivor_male': dict(
        fuel='Standing person', kind='survivor', mesh='meshes/standing.dae', mesh_pose=(0, 0, 0.02, 0.04, 0, 0),
        desc='adult male, white t-shirt, jeans', postures=['standing', 'lying'], thermal=dict(temperature=308.5)),
    'sparkx_survivor_female': dict(
        fuel='Casual female', kind='survivor', mesh='meshes/casual_female.dae', mesh_pose=(0, 0, 0.02, 0.04, 0, 0),
        desc='adult female, casual clothes', postures=['standing', 'lying'], thermal=dict(temperature=307.5)),
    'sparkx_survivor_medic': dict(
        fuel='Scrubs', kind='survivor', mesh='meshes/scrubs.obj',
        desc='adult female, medical scrubs', postures=['standing', 'lying'], thermal=dict(temperature=307.0)),
    # ---------------- vehicles ----------------
    'sparkx_bus': dict(fuel='Bus', kind='vehicle', mesh='meshes/bus.obj', scale=0.01,
                      mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='bus', color='gray'),
    'sparkx_fire_truck': dict(fuel='Fire truck', kind='vehicle', mesh='meshes/fire_truck.obj', scale=0.1,
                              mesh_pose=(0, 0, 0, 0, 0, 1.5707963),
                              cls='fire_truck', color='red'),
    'sparkx_ambulance': dict(fuel='Ambulance', kind='vehicle', mesh='meshes/ambulance.obj', scale=0.0254,
                             mesh_pose=(0, 0, 0, 0, 0, 1.5707963),
                             cls='ambulance', color='white'),
    'sparkx_car_red': dict(fuel='Hatchback red', kind='vehicle', mesh='meshes/hatchback.obj', scale=0.0254,
                           mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='car', color='red'),
    'sparkx_car_white': dict(fuel='Hatchback', kind='vehicle', mesh='meshes/hatchback.obj', scale=0.0254,
                             mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='car', color='white'),
    'sparkx_car_blue': dict(fuel='Hatchback red', kind='vehicle', mesh='meshes/hatchback.obj', scale=0.0254,
                            mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='car', color='blue', hue_shift=0.62),
    'sparkx_car_yellow': dict(fuel='Hatchback red', kind='vehicle', mesh='meshes/hatchback.obj', scale=0.0254,
                              mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='car', color='yellow', hue_shift=0.14),
    'sparkx_car_green': dict(fuel='Hatchback red', kind='vehicle', mesh='meshes/hatchback.obj', scale=0.0254,
                             mesh_pose=(0, 0, 0, 0, 0, 1.5707963), cls='car', color='green', hue_shift=0.33),
    'sparkx_suv': dict(fuel='SUV', kind='vehicle', mesh='meshes/suv.obj', scale=0.06,
                       mesh_pose=(0, 0, 0, 0, 0, -1.5707963), cls='car', color='gray'),
    'sparkx_pickup': dict(fuel='Pickup', kind='vehicle', mesh='meshes/pickup.dae',
                          mesh_pose=(0, 0, 0, 0, 0, -1.5707963), cls='car', color='gray'),
    # ---------------- props ----------------
    'sparkx_dumpster': dict(fuel='Dumpster', kind='prop', mesh='meshes/dumpster.dae', scale=1.5,
                            material=dict(albedo='materials/textures/Dumpster_Diffuse.png'),
                            cls='dumpster', color='green'),
    'sparkx_hydrant': dict(fuel='Fire hydrant', kind='prop', mesh='meshes/fire_hydrant.dae',
                           cls='fire_hydrant', color='red'),
    'sparkx_jersey_barrier': dict(fuel='Jersey Barrier', kind='prop', mesh='meshes/jersey_barrier.dae',
                                  cls='barrier', color='gray'),
    'sparkx_traffic_barrel': dict(fuel='Construction Barrel', kind='prop', mesh='meshes/construction_barrel.dae',
                                  scale=0.7, cls='traffic_barrel', color='orange'),
    # ---------------- ruins (visual only; collision generated per world) ----------------
    'sparkx_ruin_house': dict(fuel='Collapsed House', kind='ruin', mesh='meshes/collapsed_house.dae', scale=1.5),
    'sparkx_ruin_industrial': dict(fuel='Collapsed industrial building', kind='ruin',
                                   mesh='meshes/collapsed_industrial.dae'),
    'sparkx_ruin_police': dict(fuel='Collapsed police station', kind='ruin', mesh='meshes/collapsed_police_station.dae'),
    'sparkx_ruin_firestation': dict(fuel='Collapsed Fire Station', kind='ruin', mesh='meshes/collapsed_fire_station.dae'),
    # ---------------- rocks ----------------
    'sparkx_rock': dict(fuel='Falling Rock 1', kind='rock', mesh='meshes/FallingRock01.dae',
                        collider='meshes/FallingRock01_Collider.dae',
                        material=dict(albedo='materials/textures/FallingRocks_Albedo.jpg',
                                      normal='materials/textures/FallingRocks_Normal.jpg',
                                      roughness='materials/textures/FallingRocks_Roughness.jpg')),
}

ATTRIBUTION = """# Third-party assets

The models below are re-packaged from Gazebo Fuel (https://app.gazebosim.org, owner OpenRobotics).
Meshes/textures are unchanged except for texture down-scaling, car colour hue-shifts, simplified
collisions and added thermal/label plugins.

| Local model | Fuel model | License |
|---|---|---|
"""


def fuel_dir(name):
    d = sorted(glob.glob(os.path.join(CACHE, name.lower(), '*/')), key=lambda p: int(os.path.basename(p.rstrip('/'))))
    return d[-1] if d else None


def download(name):
    if fuel_dir(name):
        return fuel_dir(name)
    subprocess.run(['gz', 'fuel', 'download', '-u', FUEL + name], check=False, timeout=600,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return fuel_dir(name)


def _downscale(path, max_px=1024):
    try:
        im = Image.open(path)
        if max(im.size) > max_px:
            f = max_px / max(im.size)
            im = im.resize((int(im.size[0] * f), int(im.size[1] * f)), Image.LANCZOS)
            im.save(path)
    except Exception:
        pass


def _hue_shift(path, target_hue):
    """Recolour saturated red body paint to target hue (0..1)."""
    im = Image.open(path).convert('RGB')
    a = np.asarray(im, np.float32) / 255.0
    hsv = np.array(Image.fromarray((a * 255).astype(np.uint8)).convert('HSV'), np.float32) / 255.0
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = ((h < 0.06) | (h > 0.94)) & (s > 0.35) & (v > 0.12)
    h = np.where(red, target_hue, h)
    if target_hue in (0.14,):  # yellow looks better brighter
        v = np.where(red, np.clip(v * 1.5, 0, 1), v)
    hsv2 = np.stack([h, s, v], -1)
    out = Image.fromarray((hsv2 * 255).astype(np.uint8), 'HSV').convert('RGB')
    out.save(path)


def _pose_str(p):
    return ' '.join(f'{v:.6g}' for v in p)


def _material_xml(mat):
    if not mat:
        return ''
    keys = [('albedo', 'albedo_map'), ('normal', 'normal_map'), ('roughness', 'roughness_map'),
            ('metalness', 'metalness_map')]
    maps = ''.join(f'<{tag}>{mat[k]}</{tag}>' for k, tag in keys if k in mat)
    return f'<material><diffuse>1 1 1 1</diffuse><specular>0.2 0.2 0.2 1</specular><pbr><metal>{maps}</metal></pbr></material>'


def _thermal_xml(th):
    if not th:
        return ''
    if 'heat_signature' in th:
        return ('<plugin filename="gz-sim-thermal-system" name="gz::sim::systems::Thermal">'
                f'<heat_signature>{th["heat_signature"]}</heat_signature><max_temp>{th["max_temp"]}</max_temp></plugin>')
    return ('<plugin filename="gz-sim-thermal-system" name="gz::sim::systems::Thermal">'
            f'<temperature>{th["temperature"]}</temperature></plugin>')


def build_model_sdf(name, a, ext_min, ext_max):
    scale = a.get('scale', 1.0)
    mesh_pose = a.get('mesh_pose', (0, 0, 0, 0, 0, 0))
    size = np.maximum(ext_max - ext_min, 0.05)
    center = (ext_max + ext_min) / 2
    kind = a['kind']
    vis = (f'<visual name="visual"><pose>{_pose_str(mesh_pose)}</pose><geometry><mesh><uri>{a["mesh"]}</uri>'
           f'<scale>{scale} {scale} {scale}</scale></mesh></geometry>{_material_xml(a.get("material"))}'
           f'{_thermal_xml(a.get("thermal"))}</visual>')
    col = ''
    if kind in ('survivor', 'vehicle', 'prop'):
        shrink = 0.9 if kind == 'vehicle' else 0.8
        cs = size * np.array([shrink, shrink, 1.0])
        col = (f'<collision name="collision"><pose>{center[0]:.4f} {center[1]:.4f} {center[2]:.4f} 0 0 0</pose>'
               f'<geometry><box><size>{cs[0]:.4f} {cs[1]:.4f} {cs[2]:.4f}</size></box></geometry></collision>')
    elif kind == 'rock':
        col = (f'<collision name="collision"><geometry><mesh><uri>{a["collider"]}</uri>'
               f'<scale>{scale} {scale} {scale}</scale></mesh></geometry></collision>')
    return (f'<?xml version="1.0"?>\n<sdf version="1.9">\n  <model name="{name}">\n    <static>true</static>\n'
            f'    <link name="link">\n      {col}\n      {vis}\n    </link>\n  </model>\n</sdf>\n')


def import_assets(models_dir, max_tex=1024, verbose=True):
    catalog = {}
    attribution = ATTRIBUTION
    for name, a in ASSETS.items():
        src = download(a['fuel'])
        if not src:
            print(f'[assets] FAILED to download {a["fuel"]}')
            continue
        dst = os.path.join(models_dir, name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)
        for sub in ('meshes', 'materials'):
            if os.path.isdir(os.path.join(src, sub)):
                shutil.copytree(os.path.join(src, sub), os.path.join(dst, sub),
                                ignore=shutil.ignore_patterns('*-unmodified*', '*.material', 'scripts'))
        for f in glob.glob(os.path.join(dst, '**', '*.*'), recursive=True):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tga')):
                _downscale(f, max_tex)
        # OBJ materials: resolve every map_* to a model-local, uniquely named texture.
        # (ogre2 caches textures by file name, so colour variants must not share names)
        tex_dir = os.path.join(dst, 'materials', 'textures')
        os.makedirs(tex_dir, exist_ok=True)
        renamed = {}
        for mtl in glob.glob(os.path.join(dst, 'meshes', '*.mtl')):
            out = []
            for ln in open(mtl).read().splitlines():
                s = ln.strip()
                if s.startswith(('map_Kd', 'map_Ka')):
                    key, ref = s.split()[0], s.split()[-1]
                    base = os.path.basename(ref)
                    if base not in renamed:
                        found = None
                        for cand in (os.path.join(dst, 'meshes', base), os.path.join(tex_dir, base)):
                            if os.path.exists(cand):
                                found = cand
                                break
                        if found is None:
                            hits = glob.glob(os.path.join(CACHE, '*', '*', '**', base), recursive=True)
                            found = hits[0] if hits else None
                        if found is None:
                            out.append(ln)
                            continue
                        stem, ext = os.path.splitext(base)
                        new = f'{name}_{stem}{ext}'
                        shutil.copyfile(found, os.path.join(tex_dir, new))
                        _downscale(os.path.join(tex_dir, new), max_tex)
                        renamed[base] = new
                    ln = f'\t{key} ../materials/textures/{renamed[base]}'
                out.append(ln)
            open(mtl, 'w').write('\n'.join(out) + '\n')
        if 'hue_shift' in a:
            for tex in glob.glob(os.path.join(tex_dir, f'{name}_hatchback*.png')):
                _hue_shift(tex, a['hue_shift'])
        # COLLADA: rewrite <init_from> image references to unique model-local files
        import re
        for dae in glob.glob(os.path.join(dst, 'meshes', '*.dae')):
            txt = open(dae, encoding='utf-8', errors='ignore').read()

            def fix(m):
                ref = m.group(1)
                base = os.path.basename(ref)
                if not base.lower().endswith(('.png', '.jpg', '.jpeg', '.tga')):
                    return m.group(0)
                if base not in renamed:
                    found = None
                    for cand in (os.path.join(dst, 'meshes', ref), os.path.join(dst, 'meshes', base),
                                 os.path.join(tex_dir, base)):
                        if os.path.exists(cand):
                            found = cand
                            break
                    if found is None:
                        return m.group(0)
                    new = f'{name}_{base}'
                    if not os.path.exists(os.path.join(tex_dir, new)):
                        shutil.copyfile(found, os.path.join(tex_dir, new))
                        _downscale(os.path.join(tex_dir, new), max_tex)
                    renamed[base] = new
                return f'<init_from>../materials/textures/{renamed[base]}</init_from>'

            txt2 = re.sub(r'<init_from>([^<]+)</init_from>', fix, txt)
            if txt2 != txt:
                open(dae, 'w', encoding='utf-8').write(txt2)
        # material maps referenced from model.sdf must follow the renaming too
        if a.get('material'):
            a = dict(a)
            a['material'] = {k: (f'materials/textures/{renamed[os.path.basename(v)]}'
                                 if os.path.basename(v) in renamed else v) for k, v in a['material'].items()}
        tris = meshio.load_mesh(os.path.join(dst, a['mesh']))
        tris = meshio.transform(tris, [a.get('scale', 1.0)] * 3, a.get('mesh_pose', (0, 0, 0, 0, 0, 0)))
        mn, mx = meshio.extents(tris)
        with open(os.path.join(dst, 'model.sdf'), 'w') as f:
            f.write(build_model_sdf(name, a, mn, mx))
        with open(os.path.join(dst, 'model.config'), 'w') as f:
            f.write(f'<?xml version="1.0"?>\n<model><name>{name}</name><version>1.0</version>'
                    f'<sdf version="1.9">model.sdf</sdf><author><name>OpenRobotics (Gazebo Fuel)</name></author>'
                    f'<description>Re-packaged from Fuel model "{a["fuel"]}" for SparkX.</description></model>\n')
        entry = {k: v for k, v in a.items() if k not in ('material', 'thermal')}
        entry['min'] = [round(float(v), 4) for v in mn]
        entry['max'] = [round(float(v), 4) for v in mx]
        entry['thermal'] = a.get('thermal')
        catalog[name] = entry
        lic = 'CC-BY 4.0' if a['fuel'] in ('Rescue Randy', 'Falling Rock 1', 'Scrubs') else 'CC0 1.0'
        attribution += f'| {name} | {a["fuel"]} | {lic} |\n'
        if verbose:
            print(f'[assets] {name:32s} size={np.round(mx - mn, 2)}')
    with open(os.path.join(models_dir, 'catalog.yaml'), 'w') as f:
        yaml.safe_dump(catalog, f, sort_keys=True)
    from . import pbr
    with open(os.path.join(models_dir, 'ATTRIBUTION.md'), 'w') as f:
        f.write(attribution + pbr.attribution())
    return catalog


def load_catalog(models_dir):
    with open(os.path.join(models_dir, 'catalog.yaml')) as f:
        return yaml.safe_load(f)


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'models')
    import_assets(os.path.abspath(out))
