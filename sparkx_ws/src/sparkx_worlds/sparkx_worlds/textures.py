"""Procedural textures for SparkX disaster worlds (asphalt, concrete, brick, rubble, signs, fire/smoke sprites...).

All textures are generated deterministically with numpy + Pillow so the package ships no
third-party image assets. Run `ros2 run sparkx_worlds make_textures` (or this module) to regenerate.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 512

COLORS = {
    'red': (178, 34, 30), 'blue': (30, 80, 170), 'green': (40, 130, 60), 'yellow': (230, 190, 30),
    'orange': (235, 110, 20), 'white': (225, 225, 220), 'black': (30, 30, 30), 'gray': (120, 120, 120),
}

SIGN_LABELS = {
    # label: (background, foreground, icon)
    'PHARMACY': ((20, 130, 60), (255, 255, 255), 'cross'),
    'SCHOOL': ((230, 180, 20), (20, 20, 20), None),
    'HOTEL': ((30, 60, 140), (255, 255, 255), None),
    'BANK': ((120, 20, 30), (255, 230, 150), None),
    'POLICE': ((20, 40, 110), (255, 255, 255), 'star'),
    'CAFE': ((110, 60, 30), (255, 240, 220), None),
    'HOSPITAL': ((250, 250, 250), (200, 20, 20), 'cross'),
    'MARKET': ((200, 70, 20), (255, 255, 255), None),
}


def _rng(seed):
    return np.random.default_rng(seed)


def fractal_noise(size, octaves=5, seed=0, persistence=0.55):
    """Sum of bilinearly-upsampled random grids -> [0,1] float image (tileable)."""
    rng = _rng(seed)
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 4 * (2 ** o)
        grid = rng.random((cells, cells)).astype(np.float32)
        # tileable bilinear upsample using wrap
        xs = np.linspace(0, cells, size, endpoint=False)
        x0 = np.floor(xs).astype(int)
        fx = xs - x0
        x1 = (x0 + 1) % cells
        g = (grid[x0][:, x0] * (1 - fx)[None, :] + grid[x0][:, x1] * fx[None, :])
        g2 = (grid[x1][:, x0] * (1 - fx)[None, :] + grid[x1][:, x1] * fx[None, :])
        layer = g * (1 - fx)[:, None] + g2 * fx[:, None]
        out += amp * layer
        total += amp
        amp *= persistence
    out /= total
    return (out - out.min()) / (out.max() - out.min() + 1e-6)


def _to_img(rgb):
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def colorize(noise, c0, c1):
    c0 = np.array(c0, np.float32); c1 = np.array(c1, np.float32)
    return noise[..., None] * (c1 - c0) + c0


def cracks(draw, rng, n, size, color, width=(1, 3)):
    for _ in range(n):
        x, y = rng.random(2) * size
        ang = rng.random() * 2 * math.pi
        pts = [(x, y)]
        for _ in range(rng.integers(4, 12)):
            ang += rng.normal(0, 0.6)
            step = rng.uniform(8, 30)
            x += math.cos(ang) * step; y += math.sin(ang) * step
            pts.append((x, y))
        draw.line(pts, fill=color, width=int(rng.integers(width[0], width[1] + 1)))


def asphalt(seed=1, lane=False, dashed=True):
    rng = _rng(seed)
    n = fractal_noise(SIZE, 6, seed)
    speck = rng.random((SIZE, SIZE)) ** 8
    rgb = colorize(n, (45, 45, 48), (85, 85, 88)) + speck[..., None] * 60
    img = _to_img(rgb)
    d = ImageDraw.Draw(img)
    cracks(d, rng, 10, SIZE, (25, 25, 25))
    if lane:
        # texture u runs ALONG the street, v ACROSS it (v=0.5 is the centre line)
        y = SIZE // 2
        if dashed:
            for x in range(0, SIZE, 128):
                d.rectangle([x, y - 5, x + 70, y + 5], fill=(215, 190, 70))
        else:
            d.rectangle([0, y - 5, SIZE, y + 5], fill=(215, 190, 70))
        for yy in (int(SIZE * 0.03), int(SIZE * 0.97)):
            d.rectangle([0, yy - 3, SIZE, yy + 3], fill=(200, 200, 195))
        img = Image.blend(img, img.filter(ImageFilter.GaussianBlur(1)), 0.5)
    return img


def concrete(seed=2, base=(150, 148, 142), var=45, stains=True):
    rng = _rng(seed)
    n = fractal_noise(SIZE, 6, seed)
    rgb = colorize(n, np.array(base) - var, np.array(base) + var * 0.5)
    if stains:
        mask = Image.new('L', (SIZE, SIZE), 0)
        md = ImageDraw.Draw(mask)
        for _ in range(14):
            x, y = rng.random(2) * SIZE
            r = rng.uniform(10, 60)
            md.ellipse([x - r, y - r * 2, x + r, y + r * 2], fill=int(rng.uniform(60, 140)))
        m = np.asarray(mask.filter(ImageFilter.GaussianBlur(18)), np.float32) / 255.0
        rgb = rgb * (1 - 0.35 * m[..., None])
    img = _to_img(rgb)
    d = ImageDraw.Draw(img)
    cracks(d, rng, 6, SIZE, tuple(int(v * 0.45) for v in base))
    return img


def sidewalk(seed=3):
    img = concrete(seed, base=(165, 160, 150), var=30, stains=False)
    d = ImageDraw.Draw(img)
    step = SIZE // 4
    for i in range(5):
        d.line([(i * step, 0), (i * step, SIZE)], fill=(95, 92, 88), width=3)
        d.line([(0, i * step), (SIZE, i * step)], fill=(95, 92, 88), width=3)
    return img


def brick(seed=4, base=(150, 70, 50)):
    rng = _rng(seed)
    img = Image.new('RGB', (SIZE, SIZE), (170, 165, 155))
    d = ImageDraw.Draw(img)
    bh, bw = SIZE // 16, SIZE // 6
    for row in range(16):
        off = (bw // 2) * (row % 2)
        for col in range(-1, 7):
            x0 = col * bw + off + 2; y0 = row * bh + 2
            c = np.array(base) * rng.uniform(0.75, 1.15)
            d.rectangle([x0, y0, x0 + bw - 4, y0 + bh - 4], fill=tuple(int(v) for v in np.clip(c, 0, 255)))
    n = fractal_noise(SIZE, 5, seed)
    arr = np.asarray(img, np.float32) * (0.75 + 0.35 * n[..., None])
    img = _to_img(arr)
    cracks(ImageDraw.Draw(img), rng, 5, SIZE, (60, 40, 35))
    return img


def plaster(seed=5, base=(205, 195, 170)):
    rng = _rng(seed)
    img = concrete(seed, base=base, var=35)
    arr = np.asarray(img, np.float32)
    # soot / fire damage streaks from the top
    soot = fractal_noise(SIZE, 4, seed + 7)
    ramp = np.linspace(1, 0, SIZE)[:, None] ** 1.5
    dark = np.clip((soot * ramp) * 1.6 - 0.3, 0, 1)
    arr = arr * (1 - 0.65 * dark[..., None])
    img = _to_img(arr)
    cracks(ImageDraw.Draw(img), rng, 8, SIZE, (70, 65, 60))
    return img


def floor_tiles(seed=6):
    rng = _rng(seed)
    img = Image.new('RGB', (SIZE, SIZE), (80, 80, 80))
    d = ImageDraw.Draw(img)
    t = SIZE // 8
    for i in range(8):
        for j in range(8):
            c = int(rng.uniform(150, 185))
            d.rectangle([i * t + 1, j * t + 1, (i + 1) * t - 2, (j + 1) * t - 2], fill=(c, c - 5, c - 12))
    n = fractal_noise(SIZE, 5, seed)
    arr = np.asarray(img, np.float32) * (0.6 + 0.45 * n[..., None])  # dust
    return _to_img(arr)


def dirt(seed=7):
    rng = _rng(seed)
    n = fractal_noise(SIZE, 6, seed)
    rgb = colorize(n, (70, 60, 48), (125, 110, 90))
    grav = rng.random((SIZE, SIZE)) ** 12
    rgb += grav[..., None] * 80
    return _to_img(rgb)


def rubble(seed=8):
    rng = _rng(seed)
    img = concrete(seed, base=(135, 130, 122), var=50)
    d = ImageDraw.Draw(img)
    for _ in range(140):
        x, y = rng.random(2) * SIZE
        r = rng.uniform(3, 18)
        pts = [(x + r * math.cos(a) * rng.uniform(0.6, 1.2), y + r * math.sin(a) * rng.uniform(0.6, 1.2))
               for a in np.linspace(0, 2 * math.pi, 7)[:-1]]
        c = int(rng.uniform(70, 190))
        d.polygon(pts, fill=(c, c - 4, c - 10))
    # rebar
    for _ in range(6):
        x, y = rng.random(2) * SIZE
        a = rng.random() * math.pi
        d.line([(x, y), (x + 60 * math.cos(a), y + 60 * math.sin(a))], fill=(95, 50, 30), width=3)
    return img


def scorched(seed=9):
    n = fractal_noise(SIZE, 6, seed)
    rgb = colorize(n, (15, 12, 10), (70, 58, 48))
    return _to_img(rgb)


def scorch_decal(seed=10):
    """RGBA blotch (alpha-tested cutout) for burn marks on the ground."""
    rng = _rng(seed)
    n = fractal_noise(SIZE, 6, seed)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    r = np.hypot(xx - SIZE / 2, yy - SIZE / 2) / (SIZE / 2)
    alpha = ((1 - r) * 1.3 + (n - 0.5) * 0.9) > 0.35
    rgb = colorize(n, (10, 8, 6), (55, 45, 38))
    a = (alpha * 255).astype(np.uint8)
    img = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), a])
    return Image.fromarray(img, 'RGBA')


def corrugated(color, seed=11):
    base = np.array(COLORS[color], np.float32)
    n = fractal_noise(SIZE, 5, seed)
    x = np.arange(SIZE)
    ridges = 0.82 + 0.18 * np.sin(x / SIZE * 2 * math.pi * 24)[None, :]
    arr = base[None, None, :] * ridges[..., None] * (0.8 + 0.3 * n[..., None])
    rust = np.clip(fractal_noise(SIZE, 5, seed + 3) * 2.2 - 1.45, 0, 1)
    arr = arr * (1 - rust[..., None]) + np.array([120, 60, 30]) * rust[..., None]
    return _to_img(arr)


def painted_metal(color, seed=12):
    base = np.array(COLORS[color], np.float32)
    n = fractal_noise(SIZE, 5, seed)
    arr = base[None, None, :] * (0.85 + 0.25 * n[..., None])
    streak = np.clip(fractal_noise(SIZE, 3, seed + 5)[:, :1] * np.ones((1, SIZE)), 0, 1)
    rust = np.clip(np.abs(np.sin(np.arange(SIZE) / 13.0))[None, :] * streak - 0.75, 0, 1) * 2.5
    arr = arr * (1 - rust[..., None]) + np.array([110, 55, 25]) * rust[..., None]
    return _to_img(arr)


def burnt_metal(seed=13):
    n = fractal_noise(SIZE, 6, seed)
    rgb = colorize(n, (20, 18, 16), (95, 60, 40))
    return _to_img(rgb)


def fabric(color, seed=14):
    base = np.array(COLORS[color], np.float32)
    n = fractal_noise(SIZE, 4, seed)
    weave = 0.92 + 0.08 * np.sin(np.arange(SIZE) * 1.5)[None, :] * np.sin(np.arange(SIZE) * 1.5)[:, None]
    return _to_img(base[None, None] * weave[..., None] * (0.85 + 0.2 * n[..., None]))


def wood(seed=15):
    n = fractal_noise(SIZE, 5, seed)
    y = np.arange(SIZE)[:, None]
    grain = 0.5 + 0.5 * np.sin(y / 6.0 + n * 12)
    rgb = colorize(grain * 0.6 + n * 0.4, (90, 60, 35), (160, 115, 70))
    return _to_img(rgb)


def _font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def sign(label):
    bg, fg, icon = SIGN_LABELS[label]
    w, h = 1024, 256
    img = Image.new('RGB', (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([6, 6, w - 7, h - 7], outline=fg, width=10)
    x_text = 60
    if icon == 'cross':
        cx, cy, s = 130, h // 2, 70
        d.rectangle([cx - s // 3, cy - s, cx + s // 3, cy + s], fill=fg)
        d.rectangle([cx - s, cy - s // 3, cx + s, cy + s // 3], fill=fg)
        x_text = 240
    elif icon == 'star':
        cx, cy, r = 130, h // 2, 85
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=fg)
        x_text = 240
    f = _font(150)
    tb = d.textbbox((0, 0), label, font=f)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    avail = w - x_text - 40
    if tw > avail:
        f = _font(int(150 * avail / tw)); tb = d.textbbox((0, 0), label, font=f)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text((x_text + (avail - tw) / 2, (h - th) / 2 - tb[1]), label, fill=fg, font=f)
    # grime
    n = fractal_noise(256, 4, hash(label) % 1000)
    n = np.array(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h)), np.float32) / 255.0
    arr = np.asarray(img, np.float32) * (0.7 + 0.35 * n[..., None])
    return _to_img(arr)


def helipad():
    img = concrete(21, base=(120, 120, 118), var=25, stains=False)
    d = ImageDraw.Draw(img)
    c = SIZE // 2
    d.ellipse([30, 30, SIZE - 30, SIZE - 30], outline=(240, 240, 240), width=18)
    s = 150
    d.rectangle([c - s * 0.6, c - s, c - s * 0.3, c + s], fill=(240, 240, 240))
    d.rectangle([c + s * 0.3, c - s, c + s * 0.6, c + s], fill=(240, 240, 240))
    d.rectangle([c - s * 0.6, c - 18, c + s * 0.6, c + 18], fill=(240, 240, 240))
    return img


def sprite(kind, seed=30):
    """RGBA soft particle sprites. kind in {'flame', 'smoke', 'dust'}."""
    s = 256
    yy, xx = np.mgrid[0:s, 0:s]
    r = np.hypot(xx - s / 2, yy - s / 2) / (s / 2)
    n = fractal_noise(s, 5, seed)
    if kind == 'flame':
        a = np.clip((1 - r) * 1.6 * (0.6 + 0.6 * n), 0, 1) ** 1.2
        rgb = np.dstack([np.full_like(r, 255), 150 + 90 * (1 - r), 40 + 60 * (1 - r) ** 3])
    elif kind == 'smoke':
        a = np.clip((1 - r) * 1.3 * (0.4 + 0.8 * n), 0, 1) ** 1.4 * 0.9
        g = 60 + 50 * n
        rgb = np.dstack([g, g, g])
    else:  # dust
        a = np.clip((1 - r) * 1.2 * (0.4 + 0.8 * n), 0, 1) ** 1.5 * 0.7
        rgb = np.dstack([150 + 40 * n, 135 + 40 * n, 110 + 30 * n])
    img = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
    return Image.fromarray(img, 'RGBA')


def color_ramp(stops, w=256, h=4):
    """Horizontal colour ramp image used as particle <color_range_image>."""
    arr = np.zeros((h, w, 3), np.float32)
    xs = np.linspace(0, 1, w)
    pos = [p for p, _ in stops]
    for ch in range(3):
        arr[:, :, ch] = np.interp(xs, pos, [c[ch] for _, c in stops])[None, :]
    return _to_img(arr)


def _cutout(rgb, mask):
    """RGBA image whose alpha is a hard cut-out (the renderer alpha-tests, it does not blend)."""
    a = (np.asarray(mask) > 0.5).astype(np.uint8) * 255
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), a]), 'RGBA')


def soot_decal(seed):
    """Smoke staining above a burnt-out opening: dense at the bottom centre, breaking up into a
    dithered plume towards the top (1.6 m wide x 2.6 m tall)."""
    w, h = 384, 640
    rng = _rng(seed)
    n = np.asarray(Image.fromarray((fractal_noise(512, 6, seed) * 255).astype(np.uint8)).resize((w, h)), np.float32) / 255
    yy, xx = np.mgrid[0:h, 0:w]
    up = 1.0 - yy / h                                               # 0 at the bottom edge, 1 at the top
    spread = 0.22 + 0.5 * up
    core = np.exp(-(((xx / w) - 0.5) / spread) ** 2) * (1.0 - up) ** 0.7
    dens = core * (0.55 + 0.9 * n)
    dither = rng.random((h, w))
    mask = dens > (0.33 + 0.45 * dither * up)                       # solid low down, speckled higher up
    shade = 14 + 26 * n
    return _cutout(np.dstack([shade, shade * 0.93, shade * 0.88]), mask)


def cracks_decal(seed):
    """Branching structural cracks (2.5 x 2.5 m)."""
    s = 512
    rng = _rng(seed)
    m = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(m)

    def grow(x, y, ang, width, depth):
        for _ in range(int(rng.integers(10, 22))):
            ang += rng.normal(0, 0.35)
            step = rng.uniform(10, 26)
            x2, y2 = x + math.cos(ang) * step, y + math.sin(ang) * step
            d.line([(x, y), (x2, y2)], fill=255, width=max(1, int(width)))
            x, y = x2, y2
            if depth < 2 and rng.random() < 0.22:
                grow(x, y, ang + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1), width * 0.6, depth + 1)
            width *= 0.94
    for _ in range(3):
        grow(s / 2 + rng.normal(0, 40), s / 2 + rng.normal(0, 40), rng.uniform(0, 2 * math.pi), 5, 0)
    return _cutout(np.full((s, s, 3), 22.0), np.asarray(m) / 255.0)


def scorch_ground_decal(seed):
    """Blast scorch on the ground with a ragged, speckled edge (5 x 5 m)."""
    s = 512
    rng = _rng(seed)
    n = fractal_noise(s, 6, seed)
    yy, xx = np.mgrid[0:s, 0:s]
    r = np.hypot(xx - s / 2, yy - s / 2) / (s / 2)
    dens = (1 - r) * 1.5 + (n - 0.5) * 0.9
    mask = dens > (0.42 + 0.3 * rng.random((s, s)) * np.clip(r * 1.4, 0, 1))
    return _cutout(colorize(n, (12, 10, 9), (48, 40, 34)), mask)


def sky_panorama(render_png, out_jpg):
    """Finish the Blender-rendered sky (tools/blender/render_decals.py): columns of smoke rising
    from the ruined skyline, a pall of haze, and the glow of fires. Returns the sun's u position."""
    im = Image.open(render_png).convert('RGB')
    a = np.asarray(im, np.float32)
    h, w = a.shape[:2]
    lum = a[: h // 2].mean(axis=(0, 2))
    k = 64
    sm = np.convolve(np.concatenate([lum[-k:], lum, lum[:k]]), np.ones(2 * k + 1) / (2 * k + 1), 'same')[k:-k]
    sun_u = float(np.argmax(sm)) / w
    rng = _rng(5)
    yy = np.arange(h)[:, None] / h                                   # 0 = zenith, 1 = horizon line (bottom)
    smoke = np.zeros((h, w), np.float32)
    n1 = np.asarray(Image.fromarray((fractal_noise(1024, 6, 3) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
    n2 = np.asarray(Image.fromarray((fractal_noise(1024, 5, 4) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
    xs = np.arange(w)[None, :]
    for _ in range(15):                                              # each plume leans down-wind as it climbs
        x0 = rng.uniform(0, w)
        base, top = rng.uniform(0.86, 0.95), rng.uniform(0.05, 0.5)
        width0, lean = rng.uniform(18, 46), rng.uniform(120, 420)
        t = np.clip((base - yy) / max(base - top, 1e-3), 0, 1)       # 0 at the fire, 1 at the top
        cx = x0 + lean * t ** 1.6
        wd = width0 * (1 + 5.5 * t)
        dx = np.abs(((xs - cx + w / 2) % w) - w / 2)
        col = np.exp(-(dx / wd) ** 2) * (yy < base) * (1 - t) ** 0.35 * (t > 0)
        smoke = np.maximum(smoke, col * rng.uniform(0.7, 1.0))
    smoke = np.clip(smoke * (0.45 + 1.0 * n1), 0, 1) ** 0.9
    pall = np.clip((yy - 0.55) / 0.45, 0, 1) ** 1.5 * (0.35 + 0.4 * n2)   # dust and smoke hanging low
    dark = np.clip(smoke * 0.85 + pall * 0.55, 0, 0.93)[..., None]
    smoke_col = np.array([46, 42, 40], np.float32) * (0.75 + 0.5 * n2[..., None])
    out = a * (1 - dark) + smoke_col * dark
    glow = np.clip((yy - 0.78) / 0.22, 0, 1) ** 2 * (0.25 + 0.75 * n1) * 0.22        # fires under the smoke
    out += glow[..., None] * np.array([255, 120, 40], np.float32)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(out_jpg, quality=90)
    return sun_u


def generate_all(out_dir):
    """Write every texture the worlds use: scanned PBR surfaces (see pbr.py) plus the generated
    signs, pads, particle sprites and branding panels."""
    from . import branding, pbr
    os.makedirs(out_dir, exist_ok=True)
    pbr.build_all(out_dir)
    jobs = {
        'scorch_decal.png': lambda: scorch_decal(),
        'flame.png': lambda: sprite('flame', 31),
        'smoke.png': lambda: sprite('smoke', 32),
        'dust.png': lambda: sprite('dust', 33),
        'fire_colors.png': lambda: color_ramp([(0, (255, 240, 170)), (0.3, (255, 170, 40)), (0.65, (230, 70, 10)), (1, (60, 40, 30))]),
        'smoke_colors.png': lambda: color_ramp([(0, (70, 65, 60)), (0.5, (95, 92, 90)), (1, (140, 140, 140))]),
        'dust_colors.png': lambda: color_ramp([(0, (160, 145, 120)), (1, (190, 180, 160))]),
    }
    from .markers import atlas_image
    jobs['marker_tags.png'] = atlas_image
    for label in SIGN_LABELS:
        jobs[f'sign_{label.lower()}.png'] = (lambda label=label: sign(label))
    jobs.update({'decal_soot_a.png': lambda: soot_decal(41), 'decal_soot_b.png': lambda: soot_decal(42),
                 'decal_cracks_a.png': lambda: cracks_decal(43), 'decal_scorch_a.png': lambda: scorch_ground_decal(44)})
    for name, fn in jobs.items():
        fn().save(os.path.join(out_dir, name), optimize=True)
    render = os.path.join(out_dir, 'sky_war_render.png')        # produced by tools/blender/render_decals.py
    if os.path.exists(render):
        u = sky_panorama(render, os.path.join(out_dir, 'sky_war.jpg'))
        print(f'[textures] sky panorama finished; sun at u = {u:.3f} (sdfgen.SKY_SUN_U)')
    names = sorted(jobs) + branding.build_all(out_dir)
    # drop superseded files (older procedural PNGs that now exist as scanned JPGs)
    for f in os.listdir(out_dir):
        stem, ext = os.path.splitext(f)
        if ext == '.png' and os.path.exists(os.path.join(out_dir, stem + '.jpg')):
            os.remove(os.path.join(out_dir, f))
    return names


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'models', 'sparkx_media', 'textures')
    names = generate_all(out)
    print(f'generated {len(names)} textures in {os.path.abspath(out)}')
