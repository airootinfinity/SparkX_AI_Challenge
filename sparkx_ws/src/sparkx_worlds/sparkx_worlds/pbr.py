"""PBR surface library for SparkX worlds.

World surfaces (asphalt, concrete, brick, plaster, rubble, metal ...) are built from photo-scanned
Poly Haven materials (https://polyhaven.com, CC0): albedo + tangent-space normal map (OpenGL
convention) + roughness map. Colour variants (containers, painted tanks, tents) are derived by
recolouring a scanned base, so every coloured landmark still has real surface detail.

`build_all(out_dir)` downloads the sources once into ~/.cache/sparkx/polyhaven and writes
`<material>.jpg`, `<material>_n.jpg`, `<material>_r.jpg` into the texture directory. The written
files are committed, so generating worlds never needs network access.

`SURFACES[name]['tile']` is the real-world size (metres) of one texture repeat; the mesh builder
uses it so bricks, pavers and planks always come out at their true scale.
"""
import json
import os
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFilter

ImageFile.MAXBLOCK = 1 << 24   # optimised 4:4:4 JPEGs of noisy normal maps overflow Pillow's default buffer

CACHE = os.path.expanduser('~/.cache/sparkx/polyhaven')
API = 'https://api.polyhaven.com/files/'
UA = {'User-Agent': 'asset-fetch/1.0'}

COLORS = {
    'red': (172, 36, 30), 'blue': (34, 78, 160), 'green': (44, 122, 62), 'yellow': (222, 180, 34),
    'orange': (226, 104, 24), 'white': (222, 222, 216), 'black': (34, 34, 36), 'gray': (122, 122, 122),
}

# material -> source scan, repeat size in metres, output resolution, optional adjustments
SURFACES = {
    'asphalt': dict(src='asphalt_02', tile=3.0, px=1024),
    'sidewalk': dict(src='concrete_pavement', tile=1.8, px=1024),
    'concrete': dict(src='dirty_concrete', tile=3.0, px=1024),
    'concrete_dark': dict(src='concrete_floor_worn_001', tile=3.0, px=1024),
    'brick': dict(src='red_brick_03', tile=1.0, px=512),
    'brick_grey': dict(src='factory_brick', tile=1.5, px=512),
    'plaster': dict(src='concrete_wall_003', tile=3.0, px=1024),
    'plaster_blue': dict(src='painted_brick', tile=1.8, px=1024),
    'plaster_yellow': dict(src='painted_plaster_wall', tile=2.0, px=1024, tint=(206, 176, 112)),
    'plaster_damaged': dict(src='damaged_plaster', tile=2.6, px=1024),
    'plaster_red': dict(src='peeling_painted_wall', tile=2.4, px=1024),
    'plaster_int': dict(src='painted_plaster_wall', tile=2.0, px=512, gain=0.92),
    'floor_tiles': dict(src='floor_tiles_06', tile=3.0, px=1024, gain=0.85),
    'dirt': dict(src='brown_mud_dry', tile=2.6, px=1024),
    'rubble': dict(src='rubble', tile=2.0, px=1024),
    'scorched': dict(src='burned_ground_01', tile=2.0, px=1024, gain=0.7),
    'wood': dict(src='weathered_planks', tile=2.0, px=512),
    'shutter': dict(src='painted_metal_shutter', tile=2.0, px=512),
    'metal_plate': dict(src='metal_plate', tile=0.5, px=512, metal=0.6),
}
# colour families derived from one scan each (shared normal / roughness map)
FAMILIES = {
    'container': dict(src='corrugated_iron', tile=3.4, px=512, metal=0.35),
    'paint': dict(src='rusty_metal_02', tile=2.0, px=512, metal=0.3),
    'fabric': dict(src=None, tile=1.2, px=512),
}
# every scan used above (for attribution and the fetch step)
SCANS = sorted({s['src'] for s in list(SURFACES.values()) + list(FAMILIES.values()) if s['src']})


# ------------------------------------------------------------------------------------- sources
def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def source(scan, kind, res='1k'):
    """Path of a cached Poly Haven map (downloads on first use). kind: Diffuse | nor_gl | Rough."""
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, f'{scan}_{kind}_{res}.jpg')
    if not os.path.exists(dst):
        meta = json.loads(_get(API + scan))
        with open(dst, 'wb') as f:
            f.write(_get(meta[kind][res]['jpg']['url']))
    return dst


def load(scan, kind, px):
    im = Image.open(source(scan, kind)).convert('L' if kind == 'Rough' else 'RGB')
    return im.resize((px, px), Image.LANCZOS) if im.size != (px, px) else im


# ------------------------------------------------------------------------------------- helpers
def fbm(size, octaves=5, seed=0, persistence=0.55):
    """Tileable fractal value noise in [0, 1]."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 4 * (2 ** o)
        grid = rng.random((cells, cells)).astype(np.float32)
        xs = np.linspace(0, cells, size, endpoint=False)
        x0 = np.floor(xs).astype(int)
        fx = xs - x0
        x1 = (x0 + 1) % cells
        a = grid[x0][:, x0] * (1 - fx)[None, :] + grid[x0][:, x1] * fx[None, :]
        b = grid[x1][:, x0] * (1 - fx)[None, :] + grid[x1][:, x1] * fx[None, :]
        out += amp * (a * (1 - fx)[:, None] + b * fx[:, None])
        total += amp
        amp *= persistence
    out /= total
    return (out - out.min()) / (out.max() - out.min() + 1e-6)


def normal_from_height(h, strength=2.0):
    """Tileable height field (float, any range) -> OpenGL tangent-space normal map image."""
    h = np.asarray(h, np.float32)
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * strength
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * strength   # image rows grow downwards (= -v)
    n = np.dstack([-dx, dy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8))


def luminance(rgb):
    a = np.asarray(rgb, np.float32)
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def recolor(img, color, keep=None):
    """Repaint a scan in `color`, keeping its shading; `keep` is a 0..1 mask of pixels to leave
    untouched (rust, chipped paint)."""
    a = np.asarray(img, np.float32)
    lum = luminance(a)
    shade = np.clip(lum / (np.median(lum) + 1e-6), 0.35, 1.6)[..., None]
    out = np.asarray(color, np.float32)[None, None, :] * shade
    if keep is not None:
        out = out * (1 - keep[..., None]) + a * keep[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def rust_mask(img, amount=1.0):
    """Soft mask of rusty (orange / brown, saturated) pixels in a metal scan."""
    hsv = np.asarray(img.convert('HSV'), np.float32) / 255.0
    h, s = hsv[..., 0], hsv[..., 1]
    m = ((h > 0.02) & (h < 0.14)).astype(np.float32) * np.clip((s - 0.3) * 3.0, 0, 1)
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    return np.clip(m * amount, 0, 1)


def soot(img, amount, seed=0):
    """Smoke staining that creeps down from the top of a wall texture."""
    a = np.asarray(img, np.float32)
    n = fbm(a.shape[0], 4, seed)
    ramp = np.linspace(1, 0, a.shape[0])[:, None] ** 1.6
    dark = np.clip(n * ramp * 1.7 - 0.25, 0, 1) * amount
    return Image.fromarray(np.clip(a * (1 - dark[..., None]), 0, 255).astype(np.uint8))


def save(img, path, quality=88):
    img.save(path, quality=quality, subsampling=0 if path.endswith('_n.jpg') else 2, optimize=True)


def tile_image(img, nx, ny):
    w, h = img.size
    out = Image.new(img.mode, (w * nx, h * ny))
    for i in range(nx):
        for j in range(ny):
            out.paste(img, (i * w, j * h))
    return out


# ------------------------------------------------------------------------------------- builders
def build_surface(out_dir, name, spec):
    px = spec['px']
    alb = load(spec['src'], 'Diffuse', px)
    if spec.get('tint'):
        alb = recolor(alb, spec['tint'])
    if spec.get('gain'):
        alb = Image.fromarray(np.clip(np.asarray(alb, np.float32) * spec['gain'], 0, 255).astype(np.uint8))
    if spec.get('soot'):
        alb = soot(alb, spec['soot'], seed=len(name))
    save(alb, os.path.join(out_dir, f'{name}.jpg'))
    save(load(spec['src'], 'nor_gl', px), os.path.join(out_dir, f'{name}_n.jpg'), 92)
    save(load(spec['src'], 'Rough', px), os.path.join(out_dir, f'{name}_r.jpg'))


def build_container(out_dir):
    spec = FAMILIES['container']
    px = spec['px']
    base = load(spec['src'], 'Diffuse', px)
    rust_src = load('rusty_metal_02', 'Diffuse', px)
    rust = rust_mask(rust_src, 0.9) * np.clip(fbm(px, 4, 91) * 2.4 - 1.0, 0, 1)
    for cname, col in COLORS.items():
        im = np.asarray(recolor(base, col), np.float32)
        im = im * (1 - rust[..., None]) + np.asarray(rust_src, np.float32) * 0.75 * rust[..., None]
        save(Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)), os.path.join(out_dir, f'container_{cname}.jpg'))
    save(load(spec['src'], 'nor_gl', px), os.path.join(out_dir, 'container_n.jpg'), 92)
    save(load(spec['src'], 'Rough', px), os.path.join(out_dir, 'container_r.jpg'))


def build_paint(out_dir):
    spec = FAMILIES['paint']
    px = spec['px']
    base = load(spec['src'], 'Diffuse', px)
    keep = np.clip(rust_mask(base) * 2.4 - 1.5, 0, 1) * np.clip(fbm(px, 3, 77) * 2.2 - 0.6, 0, 1)           # only the heavier rust survives repainting
    for cname, col in COLORS.items():
        save(recolor(base, col, keep), os.path.join(out_dir, f'paint_{cname}.jpg'))
    save(load(spec['src'], 'nor_gl', px), os.path.join(out_dir, 'paint_n.jpg'), 92)
    save(load(spec['src'], 'Rough', px), os.path.join(out_dir, 'paint_r.jpg'))
    # charred sheet metal (burnt-out cars, rebar): same scan, burnt to charcoal with rust blooming through
    lum = luminance(base) / 255.0
    char = np.dstack([18 + 62 * lum, 16 + 46 * lum, 15 + 36 * lum])
    r = rust_mask(base)[..., None]
    char = char * (1 - 0.6 * r) + np.asarray(base, np.float32) * 0.45 * 0.6 * r
    save(Image.fromarray(np.clip(char, 0, 255).astype(np.uint8)), os.path.join(out_dir, 'burnt_metal.jpg'))


def build_fabric(out_dir):
    """Heavy canvas / tarpaulin: plain weave, soft folds, light dust. Bright enough to read as cloth."""
    px = FAMILIES['fabric']['px']
    x = np.arange(px)
    warp = np.sin(x * 2 * np.pi * 96 / px)
    weave = warp[None, :] * warp[:, None]
    folds = fbm(px, 3, 71)
    grime = fbm(px, 5, 72)
    for cname, col in COLORS.items():
        base = np.asarray(col, np.float32)
        base = base + (255 - base) * 0.12                          # sun-bleached
        a = base[None, None, :] * (0.9 + 0.1 * folds[..., None]) * (0.955 + 0.045 * weave[..., None])
        a *= 1 - 0.12 * np.clip(grime * 2.0 - 1.2, 0, 1)[..., None]
        save(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), os.path.join(out_dir, f'fabric_{cname}.jpg'))
    save(normal_from_height(folds * 9 + weave * 0.9, 1.0), os.path.join(out_dir, 'fabric_n.jpg'), 92)


def build_lane(out_dir):
    """Street surface with worn lane paint. u runs ALONG the street (12 m per repeat), v spans the
    carriageway (v = 0.5 is the centre line). Built from 4 x 2 repeats of the asphalt scan."""
    cell = 512
    alb = tile_image(load('asphalt_02', 'Diffuse', cell), 4, 2)
    nor = tile_image(load('asphalt_02', 'nor_gl', cell), 4, 2)
    rgh = tile_image(load('asphalt_02', 'Rough', cell), 4, 2)
    w, h = alb.size
    paint = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(paint)
    yc = h // 2
    for x in range(0, w, w // 4):                      # dashed centre line: 1.7 m dash every 3 m
        d.rectangle([x + 30, yc - 9, x + 30 + int(w * 1.7 / 12), yc + 9], fill=255)
    edge = Image.new('L', (w, h), 0)
    de = ImageDraw.Draw(edge)
    for yy in (int(h * 0.035), int(h * 0.965)):        # solid edge lines
        de.rectangle([0, yy - 7, w, yy + 7], fill=255)
    wear = np.asarray(Image.fromarray((fbm(1024, 6, 5) * 255).astype(np.uint8)).resize((w, h)), np.float32) / 255
    wear = np.clip(wear * 2.6 - 0.75, 0, 1)            # paint flakes off in patches
    a = np.asarray(alb, np.float32)
    shade = (luminance(a) / (np.median(luminance(a)) + 1e-6))[..., None]
    for mask, col in ((paint, (206, 170, 52)), (edge, (198, 198, 190))):
        m = (np.asarray(mask.filter(ImageFilter.GaussianBlur(1.0)), np.float32) / 255 * wear)[..., None]
        a = a * (1 - m) + np.asarray(col, np.float32) * np.clip(shade, 0.6, 1.25) * m
    m_all = np.clip((np.asarray(paint, np.float32) + np.asarray(edge, np.float32)) / 255 * wear, 0, 1)
    r = np.asarray(rgh, np.float32) * (1 - 0.3 * m_all)
    save(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), os.path.join(out_dir, 'asphalt_lane.jpg'))
    save(nor, os.path.join(out_dir, 'asphalt_lane_n.jpg'), 92)
    save(Image.fromarray(np.clip(r, 0, 255).astype(np.uint8)), os.path.join(out_dir, 'asphalt_lane_r.jpg'))


def build_crosswalk(out_dir):
    """Zebra crossing strip (u along the street, 3 m per repeat; v across the carriageway)."""
    cell = 512
    alb = tile_image(load('asphalt_02', 'Diffuse', cell), 1, 2)
    w, h = alb.size
    m = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(m)
    n_bars = 9
    bar = h / (n_bars * 2 + 1)
    for k in range(n_bars):
        y0 = bar * (2 * k + 1)
        d.rectangle([int(w * 0.12), int(y0), int(w * 0.88), int(y0 + bar)], fill=255)
    wear = np.asarray(Image.fromarray((fbm(512, 6, 9) * 255).astype(np.uint8)).resize((w, h)), np.float32) / 255
    wear = np.clip(wear * 2.4 - 0.6, 0, 1)
    a = np.asarray(alb, np.float32)
    mm = (np.asarray(m.filter(ImageFilter.GaussianBlur(1.0)), np.float32) / 255 * wear)[..., None]
    shade = np.clip(luminance(a) / (np.median(luminance(a)) + 1e-6), 0.6, 1.25)[..., None]
    a = a * (1 - mm) + np.array([200, 200, 192], np.float32) * shade * mm
    save(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), os.path.join(out_dir, 'crosswalk.jpg'))
    save(tile_image(load('asphalt_02', 'nor_gl', cell), 1, 2), os.path.join(out_dir, 'crosswalk_n.jpg'), 92)
    r = np.asarray(tile_image(load('asphalt_02', 'Rough', cell), 1, 2), np.float32) * (1 - 0.3 * mm[..., 0])
    save(Image.fromarray(np.clip(r, 0, 255).astype(np.uint8)), os.path.join(out_dir, 'crosswalk_r.jpg'))


# storey height / bay width (metres) encoded in the facade textures: 3 storeys x 3 bays per repeat
FACADE_TILE = 10.5
FACADES = {'facade_a': 'plaster', 'facade_b': 'brick', 'facade_c': 'concrete', 'facade_d': 'plaster_red',
           'facade_e': 'plaster_yellow'}


def build_facades(out_dir):
    """Backdrop facades (skyline and arena boundary): a scanned wall finish with three storeys of
    windows - blown-out, boarded up or sooty - plus matching normal and roughness maps."""
    px = 1024
    for k, (name, base) in enumerate(FACADES.items()):
        spec = SURFACES[base]
        rep = max(1, int(round(FACADE_TILE / spec['tile'])))
        cell = px // rep
        alb = tile_image(load(spec['src'], 'Diffuse', cell), rep, rep).resize((px, px), Image.LANCZOS)
        nor = tile_image(load(spec['src'], 'nor_gl', cell), rep, rep).resize((px, px), Image.LANCZOS)
        rgh = tile_image(load(spec['src'], 'Rough', cell), rep, rep).resize((px, px), Image.LANCZOS)
        rng = np.random.default_rng(100 + k)
        a = np.asarray(alb, np.float32).copy()
        height = np.zeros((px, px), np.float32)
        rough = np.asarray(rgh, np.float32).copy()
        soot_m = np.zeros((px, px), np.float32)
        bay = px // 3
        ww, wh = int(bay * 0.42), int(bay * 0.5)
        for row in range(3):
            for col in range(3):
                x0 = col * bay + (bay - ww) // 2
                y0 = row * bay + int(bay * 0.2)
                state = rng.choice(['dark', 'dark', 'broken', 'boarded', 'burnt'])
                glass = np.array([22, 26, 32], np.float32) if state != 'burnt' else np.array([8, 7, 6], np.float32)
                a[y0:y0 + wh, x0:x0 + ww] = glass + rng.normal(0, 3, (wh, ww, 3))
                rough[y0:y0 + wh, x0:x0 + ww] = 40 if state in ('dark',) else 170
                height[y0:y0 + wh, x0:x0 + ww] = -6.0
                fr = max(3, px // 200)                      # frame + mullions
                frame_col = np.array([196, 190, 178], np.float32) * rng.uniform(0.55, 1.0)
                for (xa, ya, xb, yb) in ((x0, y0, x0 + ww, y0 + fr), (x0, y0 + wh - fr, x0 + ww, y0 + wh),
                                         (x0, y0, x0 + fr, y0 + wh), (x0 + ww - fr, y0, x0 + ww, y0 + wh),
                                         (x0 + ww // 2 - fr // 2, y0, x0 + ww // 2 + fr // 2 + 1, y0 + wh)):
                    a[ya:yb, xa:xb] = frame_col
                    height[ya:yb, xa:xb] = -2.0
                    rough[ya:yb, xa:xb] = 150
                a[y0 + wh:y0 + wh + fr * 2, x0 - fr * 2:x0 + ww + fr * 2] *= 0.8      # sill
                height[y0 + wh:y0 + wh + fr * 2, x0 - fr * 2:x0 + ww + fr * 2] = 3.0
                if state == 'boarded':
                    for b in range(4):
                        yb0 = y0 + int(wh * (0.08 + 0.23 * b))
                        a[yb0:yb0 + int(wh * 0.17), x0 + fr:x0 + ww - fr] = np.array([122, 92, 60]) * rng.uniform(0.7, 1.1)
                        height[yb0:yb0 + int(wh * 0.17), x0 + fr:x0 + ww - fr] = 1.0
                        rough[yb0:yb0 + int(wh * 0.17), x0 + fr:x0 + ww - fr] = 215
                if state in ('burnt', 'broken'):
                    yy, xx = np.mgrid[0:px, 0:px]
                    cx, cy = x0 + ww / 2, y0
                    plume = np.exp(-((xx - cx) / (ww * 0.7)) ** 2) * np.clip((cy - yy) / (bay * 0.9) + 1.0, 0, 1) * (yy < y0 + wh)
                    soot_m = np.maximum(soot_m, plume * (0.85 if state == 'burnt' else 0.3))
        soot_m *= 0.6 + 0.4 * fbm(px, 4, 40 + k)
        a *= (1 - 0.8 * soot_m[..., None])
        # floor bands between storeys
        for row in range(3):
            y = row * bay
            a[y:y + px // 128] *= 0.72
            height[y:y + px // 128] = 2.5
        base_n = np.asarray(nor, np.float32) / 255 * 2 - 1
        win_n = np.asarray(normal_from_height(height, 0.9), np.float32) / 255 * 2 - 1
        n = np.dstack([base_n[..., 0] + win_n[..., 0], base_n[..., 1] + win_n[..., 1], base_n[..., 2]])
        n /= np.linalg.norm(n, axis=2, keepdims=True)
        save(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), os.path.join(out_dir, f'{name}.jpg'))
        save(Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8)), os.path.join(out_dir, f'{name}_n.jpg'), 92)
        save(Image.fromarray(np.clip(rough, 0, 255).astype(np.uint8)), os.path.join(out_dir, f'{name}_r.jpg'))


def build_all(out_dir, verbose=True):
    os.makedirs(out_dir, exist_ok=True)
    for name, spec in SURFACES.items():
        build_surface(out_dir, name, spec)
    build_container(out_dir)
    build_paint(out_dir)
    build_fabric(out_dir)
    build_lane(out_dir)
    build_crosswalk(out_dir)
    build_facades(out_dir)
    if verbose:
        print(f'[pbr] {len(SURFACES)} scanned surfaces + colour families + facades -> {out_dir}')


def attribution():
    lines = ['', '## Surface scans (Poly Haven, CC0 1.0)', '',
             'Albedo / normal / roughness maps in `sparkx_media/textures` are derived from these',
             'https://polyhaven.com scans (resized, recoloured or composited by `sparkx_worlds/pbr.py`).', '',
             '| Scan | Used for |', '|---|---|']
    used = {}
    for name, spec in list(SURFACES.items()) + [(f'{k}_*', v) for k, v in FAMILIES.items()]:
        if spec['src']:
            used.setdefault(spec['src'], []).append(name)
    used.setdefault('asphalt_02', []).extend(['asphalt_lane', 'crosswalk'])
    used.setdefault('rusty_metal_02', []).append('burnt_metal')
    for scan in sorted(used):
        lines.append(f'| {scan} | {", ".join(used[scan])} |')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import sys
    build_all(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                                                 'models', 'sparkx_media', 'textures'))
