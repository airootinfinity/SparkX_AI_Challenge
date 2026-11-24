# Trained model weights (data only)

Put the model you trained here. This folder is installed with the package and its path is passed to
`perception.py` as the `model_dir` parameter. The evaluation machine can open three kinds of model
(RULES.md section 6, the official ML kit):

1. plain numbers: `.json`, `.csv`, `.npy`, `.npz` (recommended: a small classifier, used with numpy);
2. an OpenCV `cv2.ml` model saved as `.xml` / `.yml`;
3. an `.onnx` file, run with `onnxruntime` 1.32.0 on the CPU.

No pickles (`.pkl`, `.joblib`, `.pt`), no Python, no scripts, no executables, no sub-folders.
Check before you hand in: `python3 sparkx_ws/tools/model_selftest.py`.
