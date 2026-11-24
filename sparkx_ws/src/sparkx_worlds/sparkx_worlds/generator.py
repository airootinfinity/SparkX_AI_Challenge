"""SparkX world generator: builds a procedural bomb-blast city block and writes

  <out>/<name>/world.sdf                 simulation world (organizer)
  <out>/<name>/meshes/*.obj              batched static geometry
  <out>/<name>/public.yaml               information that may be shared with teams
  <out>/<name>/private/scenario.yaml     survivors, hints, fires, landmarks, blockages (SECRET)
  <out>/<name>/private/gt_map.{pgm,yaml} ground-truth occupancy (SECRET)
  <out>/<name>/private/occluders.npz     boxes used by the referee for line-of-sight checks
  <out>/<name>/private/aftershocks/*.sdf rubble barriers the referee can spawn mid-mission
  <out>/<name>/private/preview.png       annotated top-down view
"""
import argparse
import math
import os
import shutil
import time

import numpy as np
import yaml

from . import city, heat as HEAT, hints as H, markers as MK, survivors as SV, warzone
from .assets import load_catalog
from .blocks import Ctx
from .gt import GroundTruth, street_points
from .scene import Scene
from .sdfgen import emitter, world_footer, world_header
from .vocab import RULES_VERSION, SIGN_LABELS

TIME_LIMITS = {'small': 900.0, 'medium': 1200.0, 'large': 1500.0}
AFTERSHOCKS = {'easy': 0, 'normal': 1, 'hard': 2}


def default_models_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, '..', 'models'),):
        if os.path.exists(os.path.join(cand, 'catalog.yaml')):
            return os.path.abspath(cand)
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('sparkx_worlds'), 'models')
    except Exception:  # pragma: no cover
        raise RuntimeError('sparkx_worlds models directory not found')


def _r(v, n=3):
    return [round(float(x), n) for x in v]


MIN_HINTS = {'small': 1, 'medium': 2, 'large': 3}


def salted_seed(seed, salt=None):
    """The number the random generators are built from. Without a salt it is the seed itself (practice worlds,
    reproducible by everyone). With the organisers' secret salt (a file kept outside the stack, never shipped) it is
    a 256-bit hash of salt and seed, which keeps competition worlds private."""
    if not salt:
        return int(seed)
    import hashlib
    return int.from_bytes(hashlib.sha256(b'sparkx-world\0' + salt + b'\0' + str(int(seed)).encode()).digest(), 'big')


def generate(name, seed=0, size='medium', difficulty='normal', lighting='day', out_dir='.', models_dir=None,
             time_limit=None, preview=True, verbose=True, max_attempts=12, salt=None):
    """Generate a world that passes the quality gate: enough survivors, enough clues (at least one
    clue chain per world, more on bigger maps). A seed that gives a weak layout is re-rolled
    deterministically (variant 1, 2, ...), so the same seed always yields the same world."""
    want_s = SV.COUNTS[size] + {'easy': -1, 'normal': 0, 'hard': 1}[difficulty] - 1
    last = None
    for variant in range(max_attempts):
        wdir, sc = _generate(name, seed, variant, size, difficulty, lighting, out_dir, models_dir, time_limit, preview,
                             verbose=False, key=salted_seed(seed, salt))
        last = (wdir, sc)
        ok = len(sc['hints']) >= MIN_HINTS[size] and len(sc['survivors']) >= want_s
        if ok:
            break
        if verbose:
            print(f'[sparkx] seed {seed} variant {variant}: {len(sc["survivors"])} survivors, {len(sc["hints"])} clues '
                  f'- below the quality gate, re-rolling')
    wdir, sc = last
    if verbose:
        print(f'[sparkx] world "{name}" ({size}/{difficulty}/{lighting}, seed {seed}, variant {sc["seed_variant"]}) -> {wdir}  '
              f'arena {sc["arena"]["xmax"]:.0f}x{sc["arena"]["ymax"]:.0f} m, {len(sc["survivors"])} survivors, '
              f'{len(sc["decoys"])} decoys, {len(sc["hints"])} clues, {len(sc["fires"])} fires, '
              f'{len(sc["landmarks"])} landmarks, {len(sc["aftershocks"]["candidates"])} aftershock candidates')
    return wdir, sc


def _generate(name, seed, variant, size, difficulty, lighting, out_dir, models_dir, time_limit, preview, verbose=False,
              key=None):
    key = int(seed) if key is None else key            # what the generators are built from (salted_seed)
    t0 = time.time()
    models_dir = models_dir or default_models_dir()
    cat = load_catalog(models_dir)
    rng = np.random.default_rng(key if variant == 0 else [key, variant])
    lay = city.Layout(*city.SIZES[size], block=float(rng.uniform(23, 26)), street=float(rng.uniform(9.5, 11)))
    wdir = os.path.join(out_dir, name)
    if os.path.exists(wdir):
        shutil.rmtree(wdir)
    mesh_dir = os.path.join(wdir, 'meshes')
    priv = os.path.join(wdir, 'private')
    os.makedirs(mesh_dir)
    os.makedirs(os.path.join(priv, 'aftershocks'))

    scene = Scene(name, 0.0, 0.0, lay.W, lay.H, rng)
    ctx = Ctx(cat, models_dir, mesh_dir, 'meshes/', rng, [str(s) for s in rng.permutation(SIGN_LABELS)])
    diff = city.DIFFICULTY[difficulty]
    city.build_ground(scene, lay)
    city.build_perimeter(scene, lay, rng)
    start = city.build_blocks(scene, ctx, lay, rng)
    city.street_clutter(scene, ctx, lay, diff, rng)
    city.ensure_landmarks(scene, ctx, rng)
    city.static_blockages(scene, ctx, lay, diff, rng)
    city.extra_fires(scene, ctx, diff['fires'], rng)
    city.street_furniture(scene, ctx, lay, rng)
    warzone.dress_streets(scene, lay, rng)

    rows, tags = scene.all_boxes()
    gt = GroundTruth(rows, tags, scene.bounds, start[:2], fires=[(f['x'], f['y']) for f in scene.fires])
    spts = street_points(scene, gt)
    survivors = SV.select_survivors(scene, ctx, gt, spts, size, difficulty, rng)
    decoys = SV.select_decoys(scene, ctx, gt, spts, survivors, difficulty, rng)
    rows, tags = scene.all_boxes()
    gt = GroundTruth(rows, tags, scene.bounds, start[:2], fires=[(f['x'], f['y']) for f in scene.fires])
    spts = street_points(scene, gt)
    # numbered location markers: their own random stream, so they change nothing else in the world
    usable = H.usable_landmarks(scene, gt, spts)
    marker_list = MK.place_markers(scene, lay, gt, spts, usable, survivors + decoys,
                                   np.random.default_rng([key, int(variant), 7741]))
    # heat sources (things at body temperature that are not people): only where the fires are thick,
    # i.e. smoky lighting; their own random stream as well
    heat_list = HEAT.place_heat_sources(scene, gt, spts, survivors + decoys, size,
                                        np.random.default_rng([key, int(variant), 9151])) if lighting == 'smoky' else []
    rows, tags = scene.all_boxes()
    gt = GroundTruth(rows, tags, scene.bounds, start[:2], fires=[(f['x'], f['y']) for f in scene.fires])
    spts = street_points(scene, gt)
    survivors = SV.finalize_survivors(scene, gt, spts, survivors)
    hint_list, usable = H.build_hints(scene, gt, spts, survivors, rng, marker_list, usable)
    shocks = H.aftershock_candidates(scene, gt, survivors, lay) if AFTERSHOCKS[difficulty] else []

    # ---------------- aftershock rubble barriers (spawned by the referee) ----------------
    for k, a in enumerate(shocks):
        sub = Scene(name, 0.0, 0.0, lay.W, lay.H, rng)
        seg = next(s for s in scene.street_segments if s['id'] == a['segment'])
        g = sub.group(f'aftershock_{k}')
        rec = city.street_blockage(sub, ctx, lay, seg, g)
        a.update(x=rec['x'], y=rec['y'], yaw=rec['yaw'])
        a['core'] = [rec['x'], rec['y'], 0.5, rec['width'], rec['depth'], 1.0, 0, 0, rec['yaw']]
        a['rows'] = [_r(r, 4) for r in g.collisions]
        sdf = g.to_sdf(mesh_dir, '{WORLD_DIR}/meshes/', name)
        dust = emitter('dust', (0, 0, 0), 'dust', 5.0, ramp_prefix='{WORLD_DIR}/meshes/')
        dust_link = dust.split('<link name="link">', 1)[1].rsplit('</link>', 1)[0]
        sdf = sdf.replace('</link></model>', f'</link><link name="dust"><pose>{rec["x"]:.2f} {rec["y"]:.2f} 1.0 0 0 0'
                                             f'</pose>{dust_link}</link></model>')
        a['sdf'] = f'aftershocks/aftershock_{k}.sdf'
        with open(os.path.join(priv, a['sdf']), 'w') as f:
            f.write(f'<?xml version="1.0"?>\n<sdf version="1.9">\n{sdf}\n</sdf>\n')
        a['id'] = f'A{k + 1:02d}'

    # ---------------- world.sdf ----------------
    parts = [world_header(name, lighting)]
    for g in scene.groups.values():
        if g.collisions or g.meshes or g.extra_visuals:
            parts.append(g.to_sdf(mesh_dir, 'meshes/', name))
    parts += scene.models + scene.lights
    parts.append(warzone.sky_model(scene, lay, lighting, mesh_dir, 'meshes/'))
    parts.append(world_footer())
    with open(os.path.join(wdir, 'world.sdf'), 'w') as f:
        f.write('\n'.join(parts))

    # ---------------- ground truth + scenario ----------------
    res = gt.res
    np.savez_compressed(os.path.join(priv, 'occluders.npz'), rows=gt.rows, tags=np.array(gt.tags),
                        occ=gt.occ.astype(np.uint8), reach=gt.reach.astype(np.uint8), safe=gt.safe.astype(np.uint8),
                        origin=np.array(gt.origin), res=np.array(res))
    img = np.full(gt.occ.shape, 205, np.uint8)
    img[gt.reach] = 254
    img[gt.occ > 0] = 0
    from PIL import Image
    Image.fromarray(img[::-1]).save(os.path.join(priv, 'gt_map.pgm'))
    with open(os.path.join(priv, 'gt_map.yaml'), 'w') as f:
        yaml.safe_dump(dict(image='gt_map.pgm', resolution=res, origin=[gt.origin[0], gt.origin[1], 0.0], negate=0,
                            occupied_thresh=0.65, free_thresh=0.25, mode='trinary'), f)
    tl = time_limit or TIME_LIMITS[size] + (300.0 if difficulty == 'hard' else 0.0)
    scenario = dict(
        rules_version=RULES_VERSION, world=name, seed=int(seed), salted=key != int(seed), seed_variant=int(variant), size=size, difficulty=difficulty, lighting=lighting,
        arena=dict(xmin=0.0, ymin=0.0, xmax=round(lay.W, 2), ymax=round(lay.H, 2), block=round(lay.B, 2),
                   street=round(lay.S, 2), grid=[lay.nx, lay.ny]),
        start=dict(x=float(start[0]), y=float(start[1]), z=0.05, yaw=float(start[2])),
        time_limit_s=tl,
        rescue=dict(radius_m=2.0, stop_dwell_s=2.0, max_stop_speed_mps=0.05, report_tolerance_m=1.0,
                    base_zone_radius_m=3.0),
        survivors=[dict(id=s['id'], model=s['model'], posture=s['posture'], x=round(s['x'], 3), y=round(s['y'], 3),
                        z=s['z'], yaw=round(s['yaw'], 3), body=_r(s['row'], 4), entity=f'survivor_{s["id"].lower()}',
                        area=s['slot']['area'], kind=s['slot']['kind'], building=s['slot'].get('building'),
                        room=s['slot'].get('room'), indoor_path_m=round(float(s['slot'].get('indoor_path_m', 0.0)), 1),
                        street_visibility=int(s['street_visibility']),
                        path_from_start_m=s['path_from_start_m'], approach_points=s['approach_points'],
                        releases=s.get('releases', [])) for s in survivors],
        decoys=[dict(id=d['id'], model=d['model'], posture=d['posture'], x=round(d['x'], 3), y=round(d['y'], 3),
                     body=_r(d['row'], 4)) for d in decoys],
        hints=hint_list,
        landmarks=[dict(id=lm['id'], cls=lm['cls'], color=lm.get('color', ''), label=lm.get('label', ''),
                        x=round(lm['x'], 3), y=round(lm['y'], 3), z=round(lm['z'], 3), yaw=round(lm['yaw'], 3),
                        size=_r(lm['size']), unique=lm in usable,
                        street_visibility=int(lm.get('street_visibility', -1))) for lm in scene.landmarks],
        markers=marker_list,
        marker_dictionary=MK.DICTIONARY,
        fires=[dict(id=f['id'], x=round(f['x'], 3), y=round(f['y'], 3), temperature=round(f['temperature'], 1),
                    hazard_radius=round(f['hazard_radius'], 2), danger_radius=round(f['danger_radius'], 2))
               for f in scene.fires],
        heat_sources=heat_list,
        buildings=[dict(id=b.id, rect=_r(b.rect), rooms=[dict(id=r['id'], rect=_r(r['rect']), collapsed=r['collapsed'])
                                                         for r in b.rooms]) for b in scene.buildings],
        blockages=scene.blockages,
        aftershocks=dict(count=AFTERSHOCKS[difficulty], trigger_after_rescues=2, trigger_time_fraction=0.45,
                         min_robot_distance_m=15.0, candidates=[{k: v for k, v in a.items()} for a in shocks]),
        epicenter=_r(scene.epicenter),
        gt_map='gt_map.yaml', occluders='occluders.npz',
    )
    with open(os.path.join(priv, 'scenario.yaml'), 'w') as f:
        yaml.safe_dump(scenario, f, sort_keys=False, default_flow_style=None, width=140)
    public = dict(rules_version=RULES_VERSION, world=name, size=size, difficulty=difficulty, lighting=lighting,
                  time_limit_s=tl, arena_size_m=[round(lay.W), round(lay.H)], survivors_total=len(survivors),
                  markers_total=len(marker_list), marker_dictionary=MK.DICTIONARY, heat_sources_total=len(heat_list),
                  note='Organizer-generated SparkX world. private/ must never be given to teams.')
    with open(os.path.join(wdir, 'public.yaml'), 'w') as f:
        yaml.safe_dump(public, f, sort_keys=False)
    if preview:
        from .preview import render_preview
        render_preview(os.path.join(priv, 'preview.png'), gt, scenario)
    if verbose:
        print(f'[sparkx] world "{name}" ({size}/{difficulty}/{lighting}, seed {seed}) -> {wdir}  '
              f'[{time.time() - t0:.1f}s] arena {lay.W:.0f}x{lay.H:.0f} m, {len(survivors)} survivors, '
              f'{len(decoys)} decoys, {len(hint_list)} hints, {len(marker_list)} markers, {len(scene.fires)} fires, '
              f'{len(scene.landmarks)} landmarks, {len(shocks)} aftershock candidates, {len(gt.rows)} boxes')
    return wdir, scenario


def main(argv=None):
    p = argparse.ArgumentParser(description='Generate a SparkX disaster-response world')
    p.add_argument('--name', required=True)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--size', choices=list(city.SIZES), default='medium')
    p.add_argument('--difficulty', choices=list(city.DIFFICULTY), default='normal')
    p.add_argument('--lighting', choices=['day', 'afternoon', 'smoky', 'dusk'], default='day')
    p.add_argument('--out', default='.')
    p.add_argument('--models-dir', default=None)
    p.add_argument('--time-limit', type=float, default=None)
    p.add_argument('--no-preview', action='store_true')
    p.add_argument('--salt-file', default=None, help='organisers only: a secret file mixed into the seed, so that the '
                   'world private (keep it outside the stack; never ship it)')
    a = p.parse_args(argv)
    salt = None
    if a.salt_file:
        with open(os.path.expanduser(a.salt_file), 'rb') as f:
            salt = f.read().strip()
        if len(salt) < 16:
            p.error(f'{a.salt_file}: the salt must be at least 16 bytes of random data')
    generate(a.name, a.seed, a.size, a.difficulty, a.lighting, a.out, a.models_dir, a.time_limit, not a.no_preview,
             salt=salt)


if __name__ == '__main__':
    main()
