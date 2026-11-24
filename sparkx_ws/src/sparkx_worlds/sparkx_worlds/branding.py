"""SparkX arena branding: posters, flags, start gate and start pad.

Partners, in the order of the official header (left to right = priority 1..4):
    1 IIIT Allahabad   2 STEMLearn.AI   3 Airoot   4 Presented at IIT Bombay Techfest
Wherever several logos stand side by side they appear in that order, using the header strip itself
(`models/sparkx_media/brand/header_strip_on_dark.png`). The single-partner posters around the start
pad are shared out by priority: IIIT Allahabad 3 (two flags + the container board), STEMLearn.AI 2
(two flags), Airoot 1 (the tent board); Techfest is credited on every strip ("Presented at").

The texture file names are the slots the worlds already use, so new artwork needs no world
regeneration (only `make_textures` and a rebuild):
    brand_gantry.jpg          start gate over the spawn pad      SPARKX + header strip
    basepad.jpg               spawn pad (ground paint)           RESCUE BASE + header strip
    brand_banner.jpg          perimeter banners                  header strip
    brand_billboard.jpg       perimeter billboards               SPARKX event + header strip
    brand_flag_airoot.jpg     flags 1 and 3 at the pad           IIIT Allahabad
    brand_flag_stemlearn.jpg  flags 2 and 4 at the pad           STEMLearn.AI
    brand_stemlearn.jpg       container board at the pad         IIIT Allahabad
    brand_airoot.jpg          relief-tent board at the pad       Airoot
    robot_deck.jpg            the rover's deck (unchanged)       Airoot / STEMLearn.AI livery
Artwork comes from `models/sparkx_media/brand/` (see its README).
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import pbr

INK = (25, 25, 25)
CRIMSON = (229, 2, 39)
OFFWHITE = (240, 239, 242)
NAVY = (36, 40, 96)

BRAND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'sparkx_media', 'brand')
EVENT = 'SPARKX'
EVENT_SUB = 'DISASTER RESPONSE CHALLENGE'


def _brand_dir():
    if os.path.isdir(BRAND_DIR):
        return BRAND_DIR
    from ament_index_python.packages import get_package_share_directory
    return os.path.join(get_package_share_directory('sparkx_worlds'), 'models', 'sparkx_media', 'brand')


def font(size, weight='black'):
    cands = {'black': ['/usr/share/fonts/truetype/lato/Lato-Black.ttf'],
             'bold': ['/usr/share/fonts/truetype/lato/Lato-Bold.ttf'],
             'regular': ['/usr/share/fonts/truetype/lato/Lato-Regular.ttf']}[weight]
    for p in cands + ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                      '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf']:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def airoot(height, color=CRIMSON, part='logo'):
    """Airoot artwork as an RGBA image of the given pixel height. part: logo | mark | wordmark."""
    m = Image.open(os.path.join(_brand_dir(), f'airoot_{part}_mask.png')).convert('L')
    m = m.resize((max(1, int(m.width * height / m.height)), height), Image.LANCZOS)
    out = Image.new('RGBA', m.size, color + (0,))
    out.putalpha(m)
    return out


def stemlearn(height, on_dark=False, part='logo'):
    """STEMLearn.AI artwork as RGBA. On dark backgrounds the navy letters are flipped to off-white
    (the teal / amber / coral accents keep their colours)."""
    im = Image.open(os.path.join(_brand_dir(), f'stemlearn_{part}.png')).convert('RGBA')
    a = np.asarray(im).copy()
    ys, xs = np.nonzero(a[..., 3] > 8)
    im = Image.fromarray(a).crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    if on_dark:
        a = np.asarray(im, np.float32).copy()
        d = np.linalg.norm(a[..., :3] - np.asarray(NAVY, np.float32), axis=2)
        k = np.clip(1.0 - d / 70.0, 0, 1)[..., None]
        a[..., :3] = a[..., :3] * (1 - k) + np.asarray(OFFWHITE, np.float32) * k
        im = Image.fromarray(a.astype(np.uint8), 'RGBA')
    return im.resize((max(1, int(im.width * height / im.height)), height), Image.LANCZOS)


def _panel(w, h, color=INK, seed=0):
    """Printed panel base with a little surface variation so it does not look like a flat fill."""
    n = pbr.fbm(256, 4, seed)
    n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
    a = np.asarray(color, np.float32)[None, None, :] * (0.9 + 0.2 * n[..., None])
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert('RGBA')


def _edge_line(img, inset, width, chamfer, color=OFFWHITE):
    """Off-white outline with chamfered corners (the S1 top-plate edge line)."""
    w, h = img.size
    d = ImageDraw.Draw(img)
    i, c = inset, chamfer
    pts = [(i + c, i), (w - i - c, i), (w - i, i + c), (w - i, h - i - c), (w - i - c, h - i), (i + c, h - i),
           (i, h - i - c), (i, i + c), (i + c, i)]
    d.line(pts, fill=color, width=width, joint='curve')


def _slashes(img, x, y0, y1, color=OFFWHITE, n=3, width=None, gap=None):
    """The three diagonal slashes from the S1 side panel."""
    d = ImageDraw.Draw(img)
    hgt = y1 - y0
    width = width or max(4, hgt // 9)
    gap = gap or int(hgt * 0.36)
    lean = int(hgt * 0.55)
    for k in range(n):
        xa = x + k * gap
        d.line([(xa, y1), (xa + lean, y0)], fill=color, width=width)
    return x + (n - 1) * gap + lean


def _grime(img, amount=0.22, seed=3):
    """Dust and soot settling on a panel that has been through a blast."""
    w, h = img.size
    n = pbr.fbm(512, 5, seed)
    n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
    streak = np.linspace(0.4, 1.0, h)[:, None]
    k = np.clip(n * 1.9 - 0.8, 0, 1) * streak * amount
    a = np.asarray(img.convert('RGB'), np.float32)
    dust = np.array([120, 110, 96], np.float32)
    return Image.fromarray(np.clip(a * (1 - k[..., None]) + dust * k[..., None], 0, 255).astype(np.uint8))


def _paste_c(img, art, cx, cy):
    img.alpha_composite(art, (int(cx - art.width / 2), int(cy - art.height / 2)))


def _fit_text(d, text, max_w, size, weight='black'):
    f = font(size, weight)
    tb = d.textbbox((0, 0), text, font=f)
    if tb[2] - tb[0] > max_w:
        f = font(int(size * max_w / (tb[2] - tb[0])), weight)
        tb = d.textbbox((0, 0), text, font=f)
    return f, tb



PARTNERS = ('1_iiita', '2_stemlearn', '3_airoot', '4_techfest')     # header order = priority


def _trim(im):
    a = np.asarray(im)[..., 3]
    ys, xs = np.nonzero(a > 8)
    return im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def _fit(im, max_w, max_h):
    k = min(max_w / im.width, max_h / im.height)
    return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)


def partner(key, max_w, max_h):
    """One partner logo from the header (artwork for dark backgrounds), fitted inside max_w x max_h."""
    return _fit(_trim(Image.open(os.path.join(_brand_dir(), f'header_logo_{key}.png')).convert('RGBA')), max_w, max_h)


def header_strip(max_w, max_h=10 ** 6):
    """The official partner header (all four logos with their dividers, left to right), for dark backgrounds."""
    return _fit(_trim(Image.open(os.path.join(_brand_dir(), 'header_strip_on_dark.png')).convert('RGBA')), max_w, max_h)


def _event_title(img, x, y, size, sub=True, max_w=None):
    """SPARKX + the three slashes (+ the subtitle in crimson underneath). Returns the bottom y."""
    d = ImageDraw.Draw(img)
    f, tb = _fit_text(d, EVENT, max_w or img.width, size)
    d.text((x, y - tb[1]), EVENT, fill=OFFWHITE, font=f)
    _slashes(img, x + (tb[2] - tb[0]) + int(size * 0.3), y + int(size * 0.07), y + (tb[3] - tb[1]),
             width=max(5, size // 12), gap=int(size * 0.3))
    y2 = y + (tb[3] - tb[1])
    if sub:
        f2, tb2 = _fit_text(d, EVENT_SUB, (max_w or img.width) - x, int(size * 0.36), 'bold')
        y2 += int(size * 0.22)
        d.text((x, y2 - tb2[1]), EVENT_SUB, fill=CRIMSON, font=f2)
        y2 += tb2[3] - tb2[1]
    return y2


def banner():
    """8 m x 2 m perimeter banner: the partner header, left to right, under the event name."""
    w, h = 2048, 512
    img = _panel(w, h, INK, 1)
    _edge_line(img, 26, 7, 46)
    d = ImageDraw.Draw(img)
    f, tb = _fit_text(d, f'{EVENT}  ·  {EVENT_SUB}', w - 200, 64, 'bold')
    d.text(((w - (tb[2] - tb[0])) / 2, 70 - tb[1]), f'{EVENT}  ·  {EVENT_SUB}', fill=OFFWHITE, font=f)
    s = header_strip(w - 140, h - 200)
    img.alpha_composite(s, ((w - s.width) // 2, 70 + (tb[3] - tb[1]) + (h - 70 - (tb[3] - tb[1]) - 40 - s.height) // 2))
    return _grime(img, 0.25, 11)


def billboard():
    """6 m x 3 m event billboard: SPARKX, the challenge, and the partner header across the bottom."""
    w, h = 2048, 1024
    img = _panel(w, h, INK, 2)
    _edge_line(img, 34, 9, 60)
    tx = 150
    y = _event_title(img, tx, 120, 280, max_w=int(w * 0.62))
    d = ImageDraw.Draw(img)
    d.line([(tx, y + 50), (w - tx, y + 50)], fill=OFFWHITE, width=5)
    f3 = font(46, 'bold')
    d.text((tx, y + 80), 'ROBOTICS & AI CHALLENGE', fill=(170, 170, 174), font=f3)
    s = header_strip(w - 2 * 90, h - y - 200)
    img.alpha_composite(s, ((w - s.width) // 2, h - 80 - s.height))
    return _grime(img, 0.2, 12)


def _single(key, seed, slashes=True):
    """1024 x 512 board with one partner logo (the boards on the tent and the container)."""
    w, h = 1024, 512
    img = _panel(w, h, INK, seed)
    _edge_line(img, 22, 6, 40)
    room = w - (300 if slashes else 120)
    a = partner(key, room, h - 170)
    _paste_c(img, a, (w / 2 - 70) if slashes else w / 2, h / 2)
    if slashes:
        _slashes(img, w - 190, int(h * 0.36), int(h * 0.64), width=9, gap=38)
    return _grime(img, 0.2, seed + 10)


def panel_airoot():
    """Relief-tent board (slot brand_airoot): Airoot, priority 3."""
    return _single('3_airoot', 3)


def panel_iiita():
    """Container board (slot brand_stemlearn): IIIT Allahabad, priority 1."""
    return _single('1_iiita', 4, slashes=False)


def basepad():
    """8 m x 8 m rescue-base start pad (the robot spawns on it) painted on scanned concrete:
    RESCUE BASE, SPARKX and the partner header, left to right."""
    px = 1024
    conc = pbr.load('dirty_concrete', 'Diffuse', 512)
    base = pbr.tile_image(conc, 2, 2).convert('RGBA')
    paint = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(paint)
    c = px // 2
    d.ellipse([70, 70, px - 70, px - 70], outline=OFFWHITE + (255,), width=26)
    d.ellipse([112, 112, px - 112, px - 112], outline=CRIMSON + (255,), width=8)
    for k in range(4):                                       # corner chevrons pointing at the pad
        sx, sy = (1 if k in (0, 3) else -1), (1 if k in (0, 1) else -1)
        x, y = (30 if sx > 0 else px - 30), (30 if sy > 0 else px - 30)
        d.line([(x + sx * 110, y), (x, y), (x, y + sy * 110)], fill=OFFWHITE + (255,), width=18, joint='curve')
    f = font(58)
    tb = d.textbbox((0, 0), 'RESCUE BASE', font=f)
    d.text((c - (tb[2] - tb[0]) / 2, 215 - tb[1]), 'RESCUE BASE', fill=OFFWHITE + (255,), font=f)
    f2 = font(150)
    tb = d.textbbox((0, 0), EVENT, font=f2)
    d.text((c - (tb[2] - tb[0]) / 2, c - 150 - tb[1]), EVENT, fill=OFFWHITE + (255,), font=f2)
    s = header_strip(int(px * 0.70))                         # the header is artwork for a dark ground:
    bw, bh = s.width + 56, s.height + 44                      # paint an ink band under it
    d.rounded_rectangle([c - bw / 2, c + 120 - bh / 2, c + bw / 2, c + 120 + bh / 2], radius=18,
                        fill=INK + (255,), outline=OFFWHITE + (255,), width=5)
    _paste_c(paint, s, c, c + 120)
    # worn paint: flake the alpha, then let the concrete shading show through
    wear = pbr.fbm(px, 6, 21)
    alpha = np.asarray(paint, np.float32)[..., 3] * np.clip(0.5 + wear * 1.1, 0, 1)
    paint.putalpha(Image.fromarray(alpha.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)))
    shade = pbr.luminance(base.convert('RGB'))
    shade = np.clip(shade / (np.median(shade) + 1e-6), 0.65, 1.2)[..., None]
    p = np.asarray(paint, np.float32)
    p[..., :3] *= shade
    base.alpha_composite(Image.fromarray(np.clip(p, 0, 255).astype(np.uint8), 'RGBA'))
    return base.convert('RGB')


def robot_deck():
    """Graphic for the top of the rover's electronics bay (0.42 m x 0.32 m, +X of the robot to the
    right of the image). The sensor mast stands at 70 % of the width, so that area stays clear."""
    w, h = 1024, 780
    img = _panel(w, h, INK, 6)
    _edge_line(img, 22, 7, 60)
    _paste_c(img, airoot(230, part='mark'), w * 0.30, h * 0.40)
    _paste_c(img, airoot(72, part='wordmark'), w * 0.30, h * 0.70)
    s = stemlearn(50, on_dark=True)
    img.alpha_composite(s, (w - 70 - s.width, h - 62 - s.height))
    _slashes(img, w - 250, 70, 170, width=11, gap=42)
    return img.convert('RGB')



def gantry():
    """7 m x 1 m start-gate header over the spawn pad: SPARKX, then the partner header left to right."""
    w, h = 2048, 292
    img = _panel(w, h, INK, 7)
    _edge_line(img, 14, 5, 30)
    d = ImageDraw.Draw(img)
    f = font(104)
    tb = d.textbbox((0, 0), EVENT, font=f)
    d.text((60, h / 2 - (tb[3] - tb[1]) / 2 - tb[1]), EVENT, fill=OFFWHITE, font=f)
    x = _slashes(img, 60 + (tb[2] - tb[0]) + 30, int(h * 0.32), int(h * 0.68), width=10, gap=36) + 40
    s = header_strip(w - x - 50, h - 70)
    img.alpha_composite(s, (x + (w - x - 50 - s.width) // 2, (h - s.height) // 2))
    return _grime(img, 0.15, 17)


def flag(key):
    """0.8 m x 3.0 m feather-flag sail (portrait): one partner, upright at the top, along the sail below."""
    w, h = 512, 1920
    img = _panel(w, h, INK, 8 if key == '1_iiita' else 9)
    if key == '1_iiita':
        # the IIIT Allahabad card is a wide badge: run it along the sail
        _paste_c(img, partner(key, 1500, w - 90).rotate(90, expand=True), w / 2, h * 0.5)
    else:
        _paste_c(img, partner(key, w - 110, 420), w / 2, h * 0.16)
        _paste_c(img, partner(key, 1150, w - 130).rotate(90, expand=True), w / 2, h * 0.62)
    d = ImageDraw.Draw(img)
    for k in range(3):
        d.line([(150 + k * 70, h - 70), (230 + k * 70, h - 190)], fill=OFFWHITE, width=22)
    return _grime(img, 0.15, 18)


def build_all(out_dir):
    jobs = {'brand_banner.jpg': banner, 'brand_billboard.jpg': billboard, 'brand_airoot.jpg': panel_airoot,
            'brand_stemlearn.jpg': panel_iiita, 'basepad.jpg': basepad, 'robot_deck.jpg': robot_deck,
            'brand_gantry.jpg': gantry, 'brand_flag_airoot.jpg': lambda: flag('1_iiita'),
            'brand_flag_stemlearn.jpg': lambda: flag('2_stemlearn')}
    for name, fn in jobs.items():
        fn().convert('RGB').save(os.path.join(out_dir, name), quality=90, optimize=True)
    # normal / roughness of the pad follow the concrete it is painted on
    pbr.save(pbr.tile_image(pbr.load('dirty_concrete', 'nor_gl', 512), 2, 2), os.path.join(out_dir, 'basepad_n.jpg'), 92)
    pbr.save(pbr.tile_image(pbr.load('dirty_concrete', 'Rough', 512), 2, 2), os.path.join(out_dir, 'basepad_r.jpg'))
    for old in ('helipad.png',):
        if os.path.exists(os.path.join(out_dir, old)):
            os.remove(os.path.join(out_dir, old))
    return sorted(jobs)
