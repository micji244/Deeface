# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Deeface — Thai face-search desktop app (v1.4, ONNX).

Two layouts from the same spec:

    pyinstaller Deeface.spec                 -> dist/Deeface.exe   (portable, one file)
    set DEEFACE_ONEDIR=1 & pyinstaller ...    -> dist/Deeface/      (folder, for the installer)

The one-file exe unpacks itself to %TEMP% on every start; the folder build
starts instantly, which is why the installer uses it. See build.ps1.

v1.4 runs the face models on ONNX Runtime, so TensorFlow / Keras (≈1.1 GB
of DLLs in 1.3) are excluded entirely. Model weights are NOT inside the exe:
they live in ``models\\.deepface\\weights\\*.onnx`` next to Deeface.exe and the
app points DEEPFACE_HOME there (configure_model_home() in face_search_core.py).
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ONEDIR = os.environ.get("DEEFACE_ONEDIR", "") == "1"

# deepface picks model classes by dotted name at runtime (importlib), so the
# submodules must be listed explicitly — but only the ONNX / OpenCV ones;
# collecting the TensorFlow / PyTorch variants would drag TF back in.
def _deepface_ok(name: str) -> bool:
    parts = name.split(".")
    return not ({"tf", "pytorch", "api", "dlib", "external"} & set(parts))

hiddenimports = collect_submodules("deepface", filter=_deepface_ok)
hiddenimports += ["onnxruntime", "onnxruntime.capi._pybind_state"]
datas = []
# gdown / onnxruntime read their own version from package metadata at import
for pkg in ("gdown", "onnxruntime", "deepface"):
    datas += copy_metadata(pkg)
binaries = []
for pkg in ("customtkinter",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# v1.5 uses the Windows UI fonts (Leelawadee UI / Segoe UI), so the old
# bundled serif fonts in assets/fonts are no longer shipped.

EXCLUDES = [
    # the old TensorFlow stack
    "tensorflow", "tensorflow_intel", "tf_keras", "keras", "tensorboard",
    "tensorflow_estimator", "jax", "jaxlib", "h5py", "grpc", "ml_dtypes",
    "torch", "torchvision",
    # heavy libraries deepface can import but this app never uses
    "scipy", "pandas", "matplotlib", "skimage", "sklearn", "sympy", "onnx",
    "insightface", "retinaface", "mtcnn", "mediapipe", "ultralytics",
    "flask", "flask_cors", "gunicorn", "fire",
    "cryptography", "pydantic", "pydantic_core",
    # dev tools
    "pytest", "IPython", "notebook", "sphinx", "PyInstaller",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)

# OpenCV's FFmpeg plug-in (31 MB) is only for video files — we read JPEG/PNG.
a.binaries = [b for b in a.binaries if "opencv_videoio_ffmpeg" not in b[0]]

pyz = PYZ(a.pure)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Deeface",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon=["deeface.ico"],
        version="version_info.txt",
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="Deeface",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Deeface",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon=["deeface.ico"],
        version="version_info.txt",
    )
