"""Half-resolution copy of the model library for machines that are short of graphics memory.

On integrated graphics, textures live in system RAM. The full library needs about 1 GB of it; this
copy needs about a quarter. Geometry, colours, tags and signs are unchanged, only surface detail
is softer. Use it for development and practice (`textures:=lite` on the launch files); scored runs
should use the full set.
"""
import hashlib
import os
import shutil

IMAGES = ('.png', '.jpg', '.jpeg')


def ensure(models_dir, scale=0.5, cache_root=None):
    """Return a directory holding the lite copy of `models_dir`, building it on first use (and
    again whenever a file in the library changes)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    files = []
    for root, _, names in os.walk(models_dir):
        for n in sorted(names):
            p = os.path.join(root, n)
            st = os.stat(p)
            files.append((os.path.relpath(p, models_dir), st.st_size, int(st.st_mtime)))
    key = hashlib.sha1(repr((sorted(files), scale)).encode()).hexdigest()[:12]
    cache_root = cache_root or os.path.join(os.path.expanduser('~'), '.cache', 'sparkx')
    out = os.path.join(cache_root, f'models_lite_{key}')
    done = os.path.join(out, '.complete')
    if os.path.exists(done):
        return out
    tmp = out + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    for rel, _, _ in files:
        src, dst = os.path.join(models_dir, rel), os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if rel.lower().endswith(IMAGES):
            try:
                im = Image.open(src)
                w, h = im.size
                if max(w, h) > 128:
                    im = im.resize((max(32, int(w * scale)), max(4, int(h * scale))), Image.LANCZOS)
                    if rel.lower().endswith('.png'):
                        im.save(dst, optimize=True)
                    else:
                        im.convert('RGB').save(dst, quality=88)
                    continue
            except Exception:  # noqa: BLE001  (not an image after all: copy it as it is)
                pass
        shutil.copy2(src, dst)
    shutil.rmtree(out, ignore_errors=True)
    os.rename(tmp, out)
    open(done, 'w').close()
    # older copies are of no use any more
    for d in os.listdir(cache_root):
        if d.startswith('models_lite_') and d != os.path.basename(out) and not d.endswith('.tmp'):
            shutil.rmtree(os.path.join(cache_root, d), ignore_errors=True)
    return out
