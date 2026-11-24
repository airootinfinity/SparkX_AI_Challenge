#!/usr/bin/env python3
"""Will my models load in the evaluation?  (RULES.md section 6, the official ML kit)

    python3 sparkx_ws/tools/model_selftest.py [models folder]

Opens every file in src/sparkx_team/models/ (or the folder given) exactly as the evaluator does before a
scored run (the evaluator runs this very file, inside the sandbox):

    level 1  .json .csv .npy .npz    parsed / loaded with numpy, without pickle
    level 2  .xml .yml .yaml         an OpenCV cv2.ml model: loaded and asked for one prediction
    level 3  .onnx                   loaded with onnxruntime on the CPU and run once on a zero input

It prints one line per file, OK or the reason it will not load, and checks that your machine has the kit's
versions. Exit code 0 when every model is OK. It proves that a file opens, not that your code uses it right.

Run it with the same Python the robot uses (`python3`, not a virtual environment). `-s` is added on purpose:
the evaluator's sandbox cannot see ~/.local, so a library installed only there does not count.
"""
import csv
import json
import os
import sys

MAX_ARRAY_BYTES = 1_000_000_000                                       # unpacked .npz arrays, all together
KIT = {'numpy': '1.26.4', 'cv2': '4.6.0', 'onnxruntime': '1.32.0'}
PICKLE = ('pkl', 'pickle', 'joblib', 'pt', 'pth', 'ckpt', 'sav', 'dill')
NOT_KIT = ('h5', 'hdf5', 'keras', 'pb', 'tflite', 'lite', 'safetensors', 'engine', 'trt', 'plan', 'param',
           'bin', 'mlmodel', 'gguf', 'ggml', 'caffemodel', 'prototxt', 'weights', 'cfg', 'pdmodel', 'pdparams')
CV_ML = {'ann_mlp': 'ANN_MLP_load', 'boost': 'Boost_load', 'dtree': 'DTrees_load', 'em': 'EM_load',
         'knn': 'KNearest_load', 'lr': 'LogisticRegression_load', 'nbayes': 'NormalBayesClassifier_load',
         'rtrees': 'RTrees_load', 'svm': 'SVM_load', 'svmsgd': 'SVMSGD_load'}


def check_file(path, np, cv2, ort):
    """dict(file, status='ok'|'fail'|'data', level, info|error) for one file in models/."""
    rel = os.path.basename(path)
    ext = rel.rsplit('.', 1)[-1].lower() if '.' in rel else ''
    r = dict(file=rel, status='ok', level=None)
    try:
        if ext in PICKLE:
            return dict(r, status='fail', error='pickle-based file: forbidden (opening it can run code) and the kit '
                        'cannot read it. Save the numbers as .npy/.json, a cv2.ml .yml, or export to .onnx')
        if ext in NOT_KIT:
            return dict(r, status='fail', error=f'.{ext} is a format the official kit cannot read. Save the numbers '
                        'as .npy/.json (level 1), a cv2.ml .yml (level 2), or export to .onnx (level 3)')
        if ext == 'json':
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            return dict(r, level=1, info=f'JSON {type(d).__name__} with {len(d) if hasattr(d, "__len__") else 1} entries')
        if ext == 'csv':
            with open(path, encoding='utf-8', newline='') as f:
                rows = sum(1 for _ in csv.reader(f))
            return dict(r, level=1, info=f'CSV, {rows} rows')
        if ext == 'npy':
            try:
                a = np.load(path, allow_pickle=False, mmap_mode='r')
            except ValueError as e:
                if 'object' in str(e).lower():
                    return dict(r, status='fail', level=1, error='array of Python objects: it needs pickle, which is '
                                'forbidden. Save plain numbers (numpy.save of a float/int array)')
                raise
            return dict(r, level=1, info=f'array {a.dtype} {list(a.shape)}')
        if ext == 'npz':
            import zipfile
            total = 0       # sizes from the array headers, before anything is unpacked (a 2 MB .npz can hold 2 GB of zeros)
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    with zf.open(name) as f:
                        v = np.lib.format.read_magic(f)
                        shape, _, dtype = (np.lib.format.read_array_header_1_0 if v == (1, 0)
                                           else np.lib.format.read_array_header_2_0)(f)
                        total += int(np.prod(shape, dtype=np.int64)) * np.dtype(dtype).itemsize
            if total > MAX_ARRAY_BYTES:
                return dict(r, status='fail', level=1, error=f'the arrays unpack to {total / 1e9:.1f} GB, more than '
                            f'{MAX_ARRAY_BYTES / 1e9:.1f} GB: a model must fit in the team\'s memory')
            with np.load(path, allow_pickle=False) as z:
                info = ', '.join(f'{k} {z[k].dtype} {list(z[k].shape)}' for k in z.files)
            return dict(r, level=1, info=info[:300])
        if ext in ('xml', 'yml', 'yaml'):
            kind = None
            try:
                fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
                if fs.isOpened():
                    kind = next((k[len('opencv_ml_'):] for k in fs.root().keys() if k.startswith('opencv_ml_')), None)
                fs.release()
            except Exception:  # noqa: BLE001 - a plain YAML / XML file makes OpenCV's reader throw
                pass
            if kind is None:
                return dict(r, status='data', info='not a cv2.ml model; read as a plain data file (not checked)')
            if kind not in CV_ML:
                return dict(r, status='fail', level=2, error=f'cv2.ml model type "{kind}" is unknown to OpenCV {cv2.__version__}')
            m = getattr(cv2.ml, CV_ML[kind])(path)
            if m is None or m.empty() or not m.isTrained():
                return dict(r, status='fail', level=2, error=f'cv2.ml {kind} model loads empty / untrained')
            n = m.getVarCount() - (1 if kind == 'lr' else 0)            # cv2.ml LR counts its bias term
            out = m.predict(np.zeros((1, n), np.float32))
            return dict(r, level=2, info=f'cv2.ml {kind}, {n} inputs, predicts {np.asarray(out[1]).ravel()[:4].round(3).tolist()}')
        if ext == 'onnx':
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            s = ort.InferenceSession(path, so, providers=['CPUExecutionProvider'])
            feeds, shapes, notes = {}, [], []
            for i in s.get_inputs():
                shape = [d if isinstance(d, int) and d > 0 else (1 if k == 0 else 640) for k, d in enumerate(i.shape)]
                if not all(isinstance(d, int) and d > 0 for d in i.shape):
                    notes.append(f'input {i.name} has a variable size {list(i.shape)}; a fixed size is recommended')
                dt = {'tensor(float)': np.float32, 'tensor(double)': np.float64, 'tensor(int64)': np.int64,
                      'tensor(int32)': np.int32, 'tensor(uint8)': np.uint8, 'tensor(float16)': np.float16}[i.type]
                feeds[i.name] = np.zeros(shape, dt)
                shapes.append(f'{i.name}{shape}')
            outs = s.run(None, feeds)
            return dict(r, level=3, notes=notes,
                        info=f'input {", ".join(shapes)} -> output {[list(o.shape) for o in outs]}')
        return dict(r, status='data', info='data file, not a model (not checked)')
    except Exception as e:  # noqa: BLE001 - every failure is reported, none stops the check
        return dict(r, status='fail', error=f'{type(e).__name__}: {str(e)[:300]}')


def main():
    if not sys.flags.no_user_site:
        os.execv(sys.executable, [sys.executable, '-s'] + sys.argv)      # ignore ~/.local, like the sandbox
    args = sys.argv[1:]
    as_json = '--json' in args                                           # used by the evaluator (hosting/sparkx_host.py)
    args = [a for a in args if a != '--json']
    here = os.path.dirname(os.path.abspath(globals().get('__file__') or '.'))   # no __file__ under `python3 -c`
    folder = os.path.abspath(args[0] if args else os.path.join(here, '..', 'src', 'sparkx_team', 'models'))
    try:
        import numpy as np
        import cv2
        import onnxruntime as ort
    except ImportError as e:
        if as_json:
            print(json.dumps(dict(error=f'{type(e).__name__}: {e}')))
            return 3
        print(f'FAIL  the official ML kit is not installed ({e}). Install it as in sparkx_ws/docs/TEAM_GUIDE.md.')
        return 2
    kit = {'numpy': np.__version__, 'cv2': cv2.__version__, 'onnxruntime': ort.__version__}
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs
                   if f not in ('README.md', '.gitkeep'))
    results = [check_file(f, np, cv2, ort) for f in files]
    if as_json:
        print(json.dumps(dict(kit=kit, models=[dict(m, ok=m['status'] != 'fail') for m in results])))
        return 0
    for name, want in KIT.items():
        if kit[name] != want:
            print(f'WARN  {name} {kit[name]} here, the evaluation uses {want}: test with {want} before you hand in')
    if not results:
        print(f'no model files in {folder}')
    for m in results:
        if m['status'] == 'ok':
            print(f'OK    {m["file"]}: level {m["level"]}, {m["info"]}')
            for n in m.get('notes', []):
                print(f'NOTE  {m["file"]}: {n}')
        elif m['status'] == 'data':
            print(f'--    {m["file"]}: {m["info"]}')
        else:
            print(f'FAIL  {m["file"]}: {m["error"]}')
    return 1 if any(m['status'] == 'fail' for m in results) else 0


if __name__ == '__main__':
    sys.exit(main())
