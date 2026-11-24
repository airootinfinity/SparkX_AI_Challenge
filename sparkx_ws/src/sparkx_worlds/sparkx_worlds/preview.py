"""Annotated top-down preview of a generated world (organizer only)."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _font(size):
    try:
        return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size)
    except OSError:
        return ImageFont.load_default()


def render_preview(path, gt, sc, scale=1):
    occ, reach = gt.occ, gt.reach
    img = np.full(occ.shape + (3,), 215, np.uint8)
    img[reach] = (245, 245, 240)
    img[occ > 0] = (45, 45, 50)
    im = Image.fromarray(img[::-1].copy())
    d = ImageDraw.Draw(im)
    f, fs = _font(14), _font(11)
    H = occ.shape[0]

    def P(x, y):
        return ((x - gt.origin[0]) / gt.res, H - (y - gt.origin[1]) / gt.res)

    for fr in sc['fires']:
        x, y = P(fr['x'], fr['y'])
        for r, col in ((fr['hazard_radius'], (255, 150, 60)), (fr['danger_radius'], (230, 40, 0))):
            rr = r / gt.res
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=col, width=3)
    for a in sc['aftershocks']['candidates']:
        x, y = P(a['x'], a['y'])
        d.rectangle([x - 12, y - 12, x + 12, y + 12], outline=(160, 90, 20), width=2)
        d.text((x + 14, y - 8), a['id'], fill=(160, 90, 20), font=fs)
    for b in sc['blockages']:
        x, y = P(b['x'], b['y'])
        d.text((x + 14, y - 8), 'BLOCKED', fill=(160, 60, 0), font=fs)
    for lm in sc['landmarks']:
        x, y = P(lm['x'], lm['y'])
        name = lm['label'] if lm['cls'] == 'sign' else f"{lm['color']} {lm['cls']}".strip()
        d.text((x - 20, y - 6), name, fill=(20, 60, 200) if lm['unique'] else (120, 120, 170), font=fs)
    for mk in sc.get('markers', []):
        x, y = P(mk['x'], mk['y'])
        d.rectangle([x - 5, y - 5, x + 5, y + 5], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
        d.text((x + 7, y + 2), f"#{mk['id']}", fill=(0, 0, 0), font=fs)
    by_id = {s['id']: s for s in sc['survivors']}
    for h in sc['hints']:
        a, b = by_id[h['source']], by_id[h['target']]
        xa, ya = P(a['x'], a['y'])
        xb, yb = P(b['x'], b['y'])
        d.line([xa, ya, xb, yb], fill=(0, 150, 60), width=2)
        ang = math.atan2(yb - ya, xb - xa)
        for s in (-0.4, 0.4):
            d.line([xb, yb, xb - 14 * math.cos(ang + s), yb - 14 * math.sin(ang + s)], fill=(0, 150, 60), width=3)
    for s in sc['survivors']:
        x, y = P(s['x'], s['y'])
        col = (220, 0, 0) if s['street_visibility'] > 0 else (150, 0, 150)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=col)
        d.text((x + 9, y - 7), f"{s['id']} {s['posture'][0]}", fill=col, font=f)
    for dc in sc['decoys']:
        x, y = P(dc['x'], dc['y'])
        d.rectangle([x - 6, y - 6, x + 6, y + 6], outline=(90, 90, 90), width=3)
        d.text((x + 8, y - 7), dc['id'], fill=(90, 90, 90), font=fs)
    st = sc['start']
    x, y = P(st['x'], st['y'])
    rr = sc['rescue']['base_zone_radius_m'] / gt.res
    d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(230, 0, 230), width=3)
    d.line([x, y, x + 25 * math.cos(st['yaw']), y - 25 * math.sin(st['yaw'])], fill=(230, 0, 230), width=3)
    lines = [f"{sc['world']}  {sc['size']}/{sc['difficulty']}/{sc['lighting']}  seed {sc['seed']}  "
             f"time {sc['time_limit_s']:.0f}s"]
    lines += [f"{h['id']}: {h['source']}->{h['target']}  {h['text']}" for h in sc['hints']]
    lines.append('red=visible survivor  purple=hidden  grey square=decoy  arrows=hint chain  brown=aftershock slot')
    pad = 18 * len(lines) + 10
    out = Image.new('RGB', (im.width, im.height + pad), (255, 255, 255))
    out.paste(im, (0, 0))
    d2 = ImageDraw.Draw(out)
    for k, ln in enumerate(lines):
        d2.text((8, im.height + 5 + 18 * k), ln, fill=(0, 0, 0), font=f)
    if scale != 1:
        out = out.resize((int(out.width * scale), int(out.height * scale)))
    out.save(path)
