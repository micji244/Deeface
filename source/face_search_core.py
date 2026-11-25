# -*- coding: utf-8 -*-
"""Deeface — core face-search logic (no GUI, headless-testable).

Pipeline:
  1. Build/refresh an embedding cache for every image in the DB folder.
  2. Embed the target image's face.
  3. Cosine-distance comparison against the whole cache -> top-N matches.
     File names ARE the employee IDs (e.g. 10234.jpg -> 10234).

Cache (v1.2.0) — content-addressed SQLite
-----------------------------------------
The cache identifies a picture by *what is in the file* (BLAKE2b-128 of the
bytes), never by where the file lives:

    <db>/deepface_cache/faces_<model>.<detector>.sqlite3
      files    (relkey PRIMARY KEY, size, mtime, hash)  -- stat-only fast path
      contents (hash PRIMARY KEY, size, n_faces, dim, vec) -- embedding once
                                                             per unique content

Consequences:
  * move the DB folder / drive          -> relkey unchanged      -> instant
  * rename files, re-organise folders   -> same hash             -> no re-embed
  * copy to another machine (mtimes
    change)                             -> crc-free hash check   -> no re-embed
  * the hash is verified once, then the new mtime is persisted, so the NEXT
    run is a stat-only pass again (this was the old 1.1.x "recomputes every
    time after a move" bug).
  * a picture with no detectable face is remembered too (n_faces = 0), so it
    is not re-detected on every run.
  * embeddings are appended incrementally (no full-matrix rewrite every 25
    rows), so the first long build is much faster and "หยุด" is instant.

A shared content store in %LOCALAPPDATA%\\Deeface\\cache lets a *new* DB folder
reuse embeddings that were already computed for the same picture bytes
anywhere else. Disable with the environment variable DEEFACE_SHARED_CACHE=0.

Upgrading from 1.1.x: the old ``rep_<model>.<detector>.npz`` is imported and
re-hashed automatically once (one read pass, no model), then ignored.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# v1.4: run every model on ONNX Runtime instead of TensorFlow. deepface
# 0.0.104 ships ONNX clients for VGG-Face / Facenet512 / ArcFace whose
# embeddings are bit-identical to the Keras ones (verified against the 1.3
# SQLite caches: cosine = 1.000000), so existing caches stay valid while the
# program loses ~1.1 GB of TensorFlow and starts in a fraction of the time.
# Must be set before deepface is imported.
os.environ.setdefault("DEEPFACE_BACKEND_ENGINE", "onnx")

import cv2
import numpy as np

logger = logging.getLogger("deeface")

# UI language for the progress/phase text emitted to the GUI.
UI_LANG = "th"


def set_ui_lang(lang: str) -> None:
    global UI_LANG
    UI_LANG = "en" if str(lang).lower().startswith("en") else "th"


def _p(th: str, en: str) -> str:
    """Pick the UI string for the language selected in the GUI."""
    return en if UI_LANG == "en" else th

# Lazy TensorFlow: `from deepface import DeepFace` pulls in TensorFlow (~5 s
# import). We defer it until the first model call so the GUI window can come
# up before TensorFlow has even started loading.
DeepFace = None
_MODEL_LOCK = threading.Lock()


def _deepface():
    """Return the DeepFace module, importing it on first use."""
    global DeepFace
    if DeepFace is None:
        configure_model_home()
        logger.info("importing deepface/ONNX Runtime (model home: %s)", model_home())
        from deepface import DeepFace as _DF
        DeepFace = _DF
        logger.info("deepface/ONNX Runtime ready")
    return DeepFace


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
MODELS = ["ArcFace", "Buffalo_L", "Facenet512", "VGG-Face"]
# Only detectors that run fully offline without TensorFlow (1.3 offered
# "tiny face" — not a deepface backend — and TF-only ones that never worked).
#   opencv : Haar cascade, the 1.x default; misses tilted/side faces
#   yunet  : small CNN (0.2 MB, ONNX) — finds far more faces, gives eye
#            landmarks for alignment; needs its own cache (one re-analysis)
DETECTORS = ["opencv", "yunet"]

# v1.6 benchmark (300 degraded queries vs 3,000 people from the real DB):
#   ArcFace  + opencv  top-1 86.7 %   74 ms/photo
#   ArcFace  + yunet   top-1 88.3 %   51 ms/photo
#   Buffalo_L + yunet  top-1 97.3 %   86 ms/photo   <- default
#   Buffalo_L + opencv top-1 97.3 %  110 ms/photo
DEFAULT_MODEL = "Buffalo_L"
DEFAULT_DETECTOR = "yunet"

CACHE_DIRNAME = "deepface_cache"
CACHE_SCHEMA = 3
HASH_CHUNK = 1 << 20
HASH_BYTES = 16  # BLAKE2b-128: no practical collision risk for ~1e5 pictures

# A model call that raises is treated as transient (bad environment, broken
# TensorFlow, out of memory, locked file...). We never persist such a failure.
# If this many pictures fail in a row while nothing has succeeded yet, the
# problem is the environment, not the pictures — stop and report it.
FAIL_LIMIT = 5

# --------------------------------------------------------------- model files
# DeepFace stores its weights in ``$DEEPFACE_HOME/.deepface/weights``. Pointing
# DEEPFACE_HOME at a folder beside the program lets us ship the weights with
# the app, so a PC that never had Python/internet can still run offline.
# When that folder is absent (running from source on the build machine) the
# library default (the user profile) is used instead.
MODELS_DIRNAME = "models"

# filename, approximate download size in MB (ONNX graphs, deepface_models v1.0)
MODEL_WEIGHTS = {
    "VGG-Face": ("vgg_face_weights.onnx", 513),
    "Facenet512": ("facenet512_weights.onnx", 90),
    "ArcFace": ("arcface_weights.onnx", 131),
    # InsightFace buffalo_l recognition net (ResNet-50, WebFace600K)
    "Buffalo_L": ("buffalo_l/webface_r50.onnx", 167),
}
DETECTOR_WEIGHTS = {
    "opencv": ("haarcascade_frontalface_default.xml", "haarcascade_eye.xml"),
    "yunet": ("face_detection_yunet_2023mar.onnx",),
}
MIN_ASSET_BYTES = 100 * 1024  # anything smaller is a partial/failed download


def app_dir() -> str:
    """Folder holding the exe (frozen) or the source files (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


def configure_model_home() -> Optional[str]:
    """Make DeepFace use the weights shipped next to the program.

    Idempotent and safe to call at any time. Respects an explicit
    DEEPFACE_HOME set by the user. Returns the chosen home, or None when the
    library default (``~``) is used.
    """
    if os.environ.get("DEEPFACE_HOME"):
        return os.environ["DEEPFACE_HOME"]

    home = os.path.join(app_dir(), MODELS_DIRNAME)
    if not os.path.isdir(home):
        if not getattr(sys, "frozen", False):
            return None  # dev/source run: use the existing ~/.deepface
        try:
            os.makedirs(os.path.join(home, ".deepface", "weights"), exist_ok=True)
        except OSError:
            return None  # read-only install dir -> fall back to the profile

    os.environ["DEEPFACE_HOME"] = home
    return home


def model_home() -> str:
    return str(os.environ.get("DEEPFACE_HOME") or os.path.expanduser("~"))


def weights_dir() -> str:
    return os.path.join(model_home(), ".deepface", "weights")


def model_assets(model_name: str, detector: str) -> dict:
    """Which weight files this model+detector needs, and which are missing.

    Used by the GUI to warn *before* a several-hundred-MB download starts (or
    before the app looks like it hung on a machine with no internet).
    """
    required: List[str] = []
    mb = 0
    entry = MODEL_WEIGHTS.get(model_name)
    if entry:
        required.append(entry[0])
        mb += entry[1]
    required.extend(DETECTOR_WEIGHTS.get(detector, ()))
    folder = weights_dir()
    missing = []
    for name in required:
        try:
            ok = os.path.getsize(os.path.join(folder, name)) >= MIN_ASSET_BYTES
        except OSError:
            ok = False
        if not ok:
            missing.append(name)
    return {
        "dir": folder,
        "required": required,
        "missing": missing,
        "download_mb": mb if missing else 0,
        "ready": not missing,
    }


configure_model_home()


def read_image(path: str) -> Optional[np.ndarray]:
    """Decode a picture into a BGR array, or None when it cannot be read.

    deepface's own loader refuses any path with non-ASCII characters
    ("Input image must not have non-english characters") — so a photo in a
    Thai-named folder, or a Windows user profile with a Thai name, made the
    whole search fail. Reading the bytes ourselves and decoding with
    cv2.imdecode works for every path and gives the same pixels as
    cv2.imread (EXIF orientation included).
    """
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None or img.ndim != 3 or img.shape[0] == 0 or img.shape[1] == 0:
        return None
    return img


class UnreadableImage(Exception):
    """The file exists but is not a decodable picture."""


class NoFaceInTarget(RuntimeError):
    """The search photo contains no detectable face."""


_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    relkey TEXT PRIMARY KEY,
    size   INTEGER NOT NULL,
    mtime  INTEGER NOT NULL,
    hash   TEXT
);
CREATE INDEX IF NOT EXISTS ix_files_hash ON files(hash);
CREATE TABLE IF NOT EXISTS contents (
    hash    TEXT PRIMARY KEY,
    size    INTEGER NOT NULL,
    n_faces INTEGER NOT NULL,
    dim     INTEGER NOT NULL,
    vec     BLOB NOT NULL
);
"""

_SHARED_DDL = """
CREATE TABLE IF NOT EXISTS contents (
    hash    TEXT PRIMARY KEY,
    size    INTEGER NOT NULL,
    n_faces INTEGER NOT NULL,
    dim     INTEGER NOT NULL,
    vec     BLOB NOT NULL
);
"""


@dataclass
class Match:
    path: str
    distance: float
    employee_id: str
    # (x, y, w, h) of the face in the *search* photo that gave this match —
    # lets the GUI show which person in a group photo was matched
    target_box: Optional[Tuple[int, int, int, int]] = None

    @property
    def similarity(self) -> float:
        return (1.0 - self.distance) * 100.0


ProgressCb = Callable[[int, int, str], None]


def _shared_cache_dir() -> Optional[str]:
    """Central content store, shared by every DB folder on this PC."""
    flag = os.environ.get("DEEFACE_SHARED_CACHE", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return None
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        return None
    return os.path.join(base, "Deeface", "cache")


def _safe_name(text: str) -> str:
    return text.replace("/", "_").replace("\\", "_").replace(":", "_")


class FaceSearch:
    def __init__(
        self,
        db_folder: str,
        model_name: str = DEFAULT_MODEL,
        detector: str = DEFAULT_DETECTOR,
        enforce_detection: bool = False,
        progress_cb: Optional[ProgressCb] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self.db_folder = os.path.abspath(db_folder)
        self.model_name = model_name
        self.detector = detector
        self.enforce_detection = enforce_detection
        self._progress_cb = progress_cb
        self._stop_event = stop_event

        safe_model = _safe_name(self.model_name)
        self.cache_dir = os.path.join(self.db_folder, CACHE_DIRNAME)
        suffix = "" if not enforce_detection else ".enf"
        self.cache_file = os.path.join(
            self.cache_dir, f"faces_{safe_model}.{self.detector}{suffix}.sqlite3"
        )
        # v1.0-1.1 cache (imported once, then ignored)
        self.legacy_cache_file = os.path.join(
            self.cache_dir, f"rep_{safe_model}.{self.detector}.npz"
        )

        shared_dir = _shared_cache_dir()
        self.shared_file = (
            os.path.join(shared_dir, f"contents_{safe_model}.{self.detector}.sqlite3")
            if shared_dir
            else None
        )

        self.paths: List[str] = []
        self.embeddings: Optional[np.ndarray] = None
        self.build_seconds = 0.0
        self.stats: Dict[str, object] = {}
        self.cache_files = 0
        self.cache_faces = 0
        self._warmup_lock = threading.Lock()
        self._warmed = False

        # per-build state
        self._conn: Optional[sqlite3.Connection] = None
        self._shared = False
        self._shared_hits = 0
        self._meta: Dict[str, Tuple[int, int]] = {}  # hash -> (n_faces, dim)
        self._rows: List[Tuple[str, str]] = []       # (path, hash) in scan order
        self._dim = 0
        self._new_contents = 0
        # rows the in-memory matrix was assembled from; a repeat search on an
        # unchanged folder reuses the matrix instead of re-reading the cache
        self._assembled_rows: Optional[List[Tuple[str, str]]] = None

    # ------------------------------------------------------------- warm-up
    def warmup(self) -> None:
        """Load the heavy model stack in the background so the first search
        is not slowed down by the TensorFlow import. Safe to call in a
        daemon thread; concurrent model builds are serialized on
        ``_MODEL_LOCK``."""
        # A grey buffer is enough: with enforce_detection=False the whole
        # image goes through detector + model, so both get built. (1.3 walked
        # the entire DB folder here just to pick a sample photo — and with an
        # empty DB field it walked the current directory, which could be a
        # whole drive.)
        try:
            probe = np.full((160, 160, 3), 128, dtype=np.uint8)
            self._represent(probe, enforce=False)
            self._warmed = True
            logger.info("warm-up finished (%s / %s)", self.model_name, self.detector)
        except Exception as exc:  # noqa: BLE001
            # probe failed (e.g. no face in the grey buffer) — model still
            # loaded; the real search will just proceed normally
            logger.warning("warm-up did not complete: %s", exc)
            assets = model_assets(self.model_name, self.detector)
            if not assets["ready"]:
                logger.warning(
                    "missing model files in %s: %s",
                    assets["dir"],
                    ", ".join(assets["missing"]),
                )

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _embeddings_from_repr(res) -> List[np.ndarray]:
        """Normalize DeepFace.represent() output across versions to a list of
        1-D embedding arrays (one per detected face)."""
        out: List[np.ndarray] = []
        if res is None:
            return out
        if isinstance(res, np.ndarray):
            # legacy single-face ndarray
            return [res.reshape(-1).astype(np.float32)] if res.size else []
        for item in res:
            if isinstance(item, dict):
                emb = item.get("embedding")
            elif isinstance(item, (list, tuple)):
                emb = item[0] if item else None
            else:
                emb = getattr(item, "embedding", None)
            if emb is None:
                continue
            emb = np.asarray(emb, dtype=np.float32).reshape(-1)
            if emb.size:
                out.append(emb)
        return out

    def _emit(self, done: int, total: int, phase: str) -> None:
        if self._progress_cb:
            self._progress_cb(done, total, phase)

    def _stop_requested(self) -> bool:
        return bool(self._stop_event is not None and self._stop_event.is_set())

    def _represent_detail(self, img, detector: Optional[str] = None) -> List[Tuple[np.ndarray, Optional[Tuple[int, int, int, int]], bool]]:
        """(embedding, face box, is_fallback) for every face deepface returns.

        With enforce_detection=False, a picture in which the detector finds
        no face is embedded *as a whole* (box = whole image, confidence 0).
        Such a "face" is meaningless for identification: in 1.x it made
        faceless DB pictures (backgrounds, placeholders) and badly detected
        search photos "match" each other at 80-99 %. Callers drop these.
        """
        if isinstance(img, str):
            arr = read_image(img)
            if arr is None:
                raise UnreadableImage(img)
            img = arr
        h, w = img.shape[:2]
        with _MODEL_LOCK:
            res = _deepface().represent(
                img_path=img,
                model_name=self.model_name,
                detector_backend=detector or self.detector,
                enforce_detection=False,
                align=True,
            )
        if detector == "skip":  # caller already cropped the face
            return [(e, None, False) for e in self._embeddings_from_repr(res)]
        if res is None or isinstance(res, np.ndarray):
            embs = self._embeddings_from_repr(res)
            return [(e, None, False) for e in embs]
        out = []
        for item in res:
            if not isinstance(item, dict):
                continue
            emb = item.get("embedding")
            if emb is None:
                continue
            emb = np.asarray(emb, dtype=np.float32).reshape(-1)
            if not emb.size:
                continue
            a = item.get("facial_area") or {}
            try:
                box = (int(a["x"]), int(a["y"]), int(a["w"]), int(a["h"]))
            except (KeyError, TypeError, ValueError):
                box = None
            conf = float(item.get("face_confidence") or 0.0)
            fallback = conf <= 0.0 and (
                box is None or (box[0] <= 0 and box[1] <= 0
                                and box[2] >= w - 1 and box[3] >= h - 1))
            out.append((emb, box, fallback))
        return out

    def _represent(self, img, enforce: Optional[bool] = None) -> List[np.ndarray]:
        """Embeddings of the *real* faces in a picture (path or BGR array).

        Raises :class:`UnreadableImage` for files that are not pictures.
        Returns [] when no face is found (``enforce`` is kept for API
        compatibility; the whole-image fallback is never returned)."""
        if isinstance(img, str):
            arr = read_image(img)
            if arr is None:
                raise UnreadableImage(img)
            img = arr
        found = self._find_faces(img, rescue_always=False)
        self._last_boxes = [b for _, b in found]
        return [e for e, _ in found]

    # ---------------------------------------------------- search-photo faces
    def _yunet_boxes(self, img: np.ndarray, score: float = 0.6):
        """Faces found by YuNet at (almost) full resolution.

        deepface pads the picture to 2x and shrinks it to 640 px before
        YuNet sees it, so faces in group photos end up ~15 px and are
        missed. Running the detector ourselves on the real-size picture
        finds them (≈0.05 s)."""
        path = os.path.join(weights_dir(), "face_detection_yunet_2023mar.onnx")
        if not os.path.isfile(path) or not hasattr(cv2, "FaceDetectorYN"):
            return []
        h, w = img.shape[:2]
        # big photos: shrink to 1920 px; tiny ID photos (e.g. 65x80 px):
        # enlarge to 480 px — YuNet misses faces smaller than ~20 px
        scale = min(1920.0 / max(h, w), max(1.0, 480.0 / max(h, w)))
        work = img if abs(scale - 1.0) < 1e-6 else cv2.resize(
            img, (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        try:
            det = cv2.FaceDetectorYN.create(path, "", (work.shape[1], work.shape[0]),
                                            score, 0.3, 5000)
            _, faces = det.detect(work)
        except cv2.error as exc:
            logger.warning("YuNet full-size detection failed: %s", exc)
            return []
        out = []
        for r in faces if faces is not None else []:
            x, y, bw, bh = (float(v) / scale for v in r[:4])
            if bw >= 12 and bh >= 12:
                out.append((int(x), int(y), int(bw), int(bh)))
        return out

    @staticmethod
    def _overlap(a, b) -> float:
        ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
        iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
        ih = max(0, min(ay2, by2) - max(a[1], b[1]))
        inter = iw * ih
        small = max(1, min(a[2] * a[3], b[2] * b[3]))
        return inter / small

    @staticmethod
    def _iou(a, b) -> float:
        ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
        iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
        ih = max(0, min(ay2, by2) - max(a[1], b[1]))
        inter = iw * ih
        union = a[2] * a[3] + b[2] * b[3] - inter
        return inter / union if union > 0 else 0.0

    def _target_faces(self, img: np.ndarray):
        return self._find_faces(img, rescue_always=True)

    def _find_faces(self, img: np.ndarray, rescue_always: bool):
        """Faces of a picture as (embedding, box).

        First the normal deepface pipeline. Then a full-size YuNet pass adds
        faces it missed — always for the search photo (group photos), and
        for DB photos only when the pipeline found nothing (tiny ID photos).
        Each rescued face is embedded from an enlarged crop around it, so
        the configured detector + alignment still run on it."""
        found = [(e, b) for e, b, fb in self._represent_detail(img) if not fb]
        if found and not rescue_always:
            return found
        yboxes = self._yunet_boxes(img)
        if rescue_always and yboxes and self.detector != "yunet":
            # Haar (opencv) fires on small non-face patches; such "faces"
            # all embed alike and matched unrelated people at ~99 %. On the
            # search photo keep only faces that YuNet confirms.
            # IoU, not overlap-of-smaller: a tiny false patch *inside* a
            # real face must not count as confirmed
            found = [(e, b) for e, b in found
                     if b and any(self._iou(b, y) > 0.3 for y in yboxes)]
        boxes = [b for _, b in found if b]
        H, W = img.shape[:2]
        for box in yboxes:
            if any(self._overlap(box, b) > 0.4 for b in boxes):
                continue
            x, y, bw, bh = box
            # opencv mode: Haar would re-detect (and mis-detect) inside the
            # crop, so embed YuNet's own tight crop directly
            direct = self.detector == "opencv"
            m = int(max(bw, bh) * (0.1 if direct else 0.8))
            x1, y1 = max(0, x - m), max(0, y - m)
            x2, y2 = min(W, x + bw + m), min(H, y + bh + m)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            if max(crop.shape[:2]) < 320:  # let the detector see a usable size
                r = 320.0 / max(crop.shape[:2])
                crop = cv2.resize(crop, (int(crop.shape[1] * r), int(crop.shape[0] * r)),
                                  interpolation=cv2.INTER_CUBIC)
            faces = self._represent_detail(np.ascontiguousarray(crop),
                                           detector="skip" if direct else None)
            # prefer a real face inside the crop; else the crop itself is the
            # face YuNet located, which is still a valid face embedding
            real = [f for f in faces if not f[2]]
            pick = max(real, key=lambda f: (f[1][2] * f[1][3]) if f[1] else 0) if real else (
                faces[0] if faces else None)
            if pick is None:
                continue
            found.append((pick[0], box))
            boxes.append(box)
        return found

    def _scan_db(self) -> List[Tuple[str, int, int]]:
        """(path, size, mtime) for every picture under the DB folder.

        os.scandir returns the size/mtime from the directory listing itself
        on Windows, so this avoids one stat() system call per file (17k
        calls on the production folder)."""
        out: List[Tuple[str, int, int]] = []
        stack = [self.db_folder]
        while stack:
            folder = stack.pop()
            try:
                it = os.scandir(folder)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name != CACHE_DIRNAME:
                                stack.append(e.path)
                            continue
                        if os.path.splitext(e.name)[1].lower() not in IMAGE_EXTS:
                            continue
                        st = e.stat()
                        out.append((e.path, int(st.st_size), int(st.st_mtime)))
                    except OSError:
                        continue
        out.sort(key=lambda t: t[0])
        return out

    def list_db_files(self) -> List[str]:
        return [p for p, _, _ in self._scan_db()]

    @staticmethod
    def _to_str(x) -> str:
        return x.decode("utf-8") if isinstance(x, bytes) else str(x)

    def _relkey(self, path: str) -> str:
        """Path relative to the DB root — invariant to the absolute location."""
        rel = os.path.relpath(path, self.db_folder)
        return rel.replace(os.sep, "/")

    def _path_of_relkey(self, rk: str) -> str:
        return os.path.join(self.db_folder, *rk.split("/"))

    @staticmethod
    def _hash_file(path: str) -> Optional[str]:
        """BLAKE2b-128 of the whole file (hex). Content identity — immune to
        moves, renames, copies and mtime shuffling. ~100 MB/s on a laptop
        disk, so a 16k-photo library is hashed in ~10 s."""
        h = hashlib.blake2b(digest_size=HASH_BYTES)
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(HASH_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
        except OSError:
            return None
        return h.hexdigest()

    @staticmethod
    def _normalise_rows(block: np.ndarray) -> np.ndarray:
        """L2-normalise every row in place-ish so search is a dot product."""
        block = np.asarray(block, dtype=np.float32)
        norms = np.linalg.norm(block, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return block / norms

    # ------------------------------------------------------------- cache I/O
    def _open_cache(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        os.makedirs(self.cache_dir, exist_ok=True)
        conn = sqlite3.connect(self.cache_file, timeout=30.0)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.executescript(_DDL)

        row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row is not None and row[0] != str(CACHE_SCHEMA):
            # incompatible/corrupt cache: keep a backup, start clean
            conn.close()
            try:
                os.replace(self.cache_file, f"{self.cache_file}.v{row[0]}.bak")
            except OSError:
                pass
            conn = sqlite3.connect(self.cache_file, timeout=30.0)
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_DDL)

        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('schema',?)",
            (str(CACHE_SCHEMA),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('model',?)",
            (self.model_name,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('detector',?)",
            (self.detector,),
        )
        conn.commit()
        self._conn = conn
        return conn

    def _attach_shared(self, conn: sqlite3.Connection) -> None:
        if not self.shared_file:
            return
        try:
            os.makedirs(os.path.dirname(self.shared_file), exist_ok=True)
            conn.execute("ATTACH DATABASE ? AS shared", (self.shared_file,))
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS shared.contents ("
                " hash TEXT PRIMARY KEY, size INTEGER NOT NULL,"
                " n_faces INTEGER NOT NULL, dim INTEGER NOT NULL,"
                " vec BLOB NOT NULL);"
            )
            self._shared = True
        except sqlite3.Error:
            self._shared = False

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value)
                )
        except sqlite3.Error:
            pass

    def _load_manifest(self, conn: sqlite3.Connection) -> Dict[str, tuple]:
        """relkey -> (size, mtime, hash) for every file ever processed."""
        out: Dict[str, tuple] = {}
        for rk, sz, mt, h in conn.execute(
            "SELECT relkey, size, mtime, hash FROM files"
        ):
            out[rk] = (int(sz), int(mt), h)
        return out

    def _content_meta(self, conn: sqlite3.Connection, h: str):
        """(n_faces, dim) for a content hash, or None when unknown.

        Falls back to the shared store, importing the row into the local
        cache so the next lookup is local."""
        cached = self._meta.get(h)
        if cached is not None:
            return cached
        row = conn.execute(
            "SELECT n_faces, dim FROM contents WHERE hash=?", (h,)
        ).fetchone()
        if row is None and self._shared:
            try:
                row = conn.execute(
                    "SELECT n_faces, dim, size, vec FROM shared.contents WHERE hash=?",
                    (h,),
                ).fetchone()
                if row is not None:
                    # join the current transaction; the batch flush commits it
                    conn.execute(
                        "INSERT OR IGNORE INTO contents"
                        "(hash,size,n_faces,dim,vec) VALUES(?,?,?,?,?)",
                        (h, int(row[2]), int(row[0]), int(row[1]), row[3]),
                    )
                    self._shared_hits += 1
                    row = (int(row[0]), int(row[1]))
            except sqlite3.Error:
                self._shared = False
                row = None
        if row is None:
            return None
        meta = (int(row[0]), int(row[1]))
        self._meta[h] = meta
        if meta[0] > 0 and self._dim == 0:
            self._dim = meta[1]
        return meta

    def _fetch_vec(self, conn: sqlite3.Connection, h: str):
        row = conn.execute("SELECT vec FROM contents WHERE hash=?", (h,)).fetchone()
        if row is None:
            return None
        return np.frombuffer(row[0], dtype=np.float32)

    def _flush_batch(
        self,
        conn: sqlite3.Connection,
        contents: List[tuple],
        files: List[tuple],
    ) -> None:
        if not contents and not files:
            return
        try:
            with conn:
                if contents:
                    conn.executemany(
                        "INSERT OR REPLACE INTO contents"
                        "(hash,size,n_faces,dim,vec) VALUES(?,?,?,?,?)",
                        contents,
                    )
                if files:
                    conn.executemany(
                        "INSERT OR REPLACE INTO files"
                        "(relkey,size,mtime,hash) VALUES(?,?,?,?)",
                        files,
                    )
        except sqlite3.Error:
            pass
        # publish new embeddings incrementally so a fresh DB folder on this PC
        # can reuse them (best effort, never fatal)
        if self._shared and contents:
            try:
                with conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO shared.contents"
                        "(hash,size,n_faces,dim,vec) VALUES(?,?,?,?,?)",
                        contents,
                    )
            except sqlite3.Error:
                self._shared = False
        new_contents = len(contents)
        contents.clear()
        files.clear()
        if new_contents:
            self._new_contents += new_contents

    def _sync_shared(self, conn: sqlite3.Connection) -> None:
        """Copy content rows we have not published yet into the shared store."""
        if not self._shared:
            return
        try:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO shared.contents"
                    "(hash,size,n_faces,dim,vec) "
                    "SELECT hash,size,n_faces,dim,vec FROM main.contents "
                    "WHERE hash NOT IN (SELECT hash FROM shared.contents)"
                )
        except sqlite3.Error:
            self._shared = False

    # --------------------------------------------------------- npz migration
    def _index_current_files(self):
        by_full: Dict[str, str] = {}
        by_name: Dict[str, List[str]] = {}
        for p in self.list_db_files():
            by_full[p] = p
            by_name.setdefault(os.path.basename(p), []).append(p)
        return by_full, by_name

    def _migrate_legacy_npz(self, conn: sqlite3.Connection) -> int:
        """Import a v1.0-1.1 ``rep_*.npz`` once.

        The old cache is keyed by path + (size, mtime, crc32). We re-key it by
        the real content hash of each file (one read pass, no model work), so
        from then on moves/renames are free. Files that are missing or whose
        size no longer matches are dropped (they will simply be embedded).
        """
        if conn.execute("SELECT 1 FROM files LIMIT 1").fetchone():
            return 0
        state = conn.execute("SELECT value FROM meta WHERE key='npz_import'").fetchone()
        if state is not None:
            if state[0] == "in-progress":
                # a previous upgrade was interrupted -> start it over cleanly
                try:
                    with conn:
                        conn.execute("DELETE FROM files")
                        conn.execute("DELETE FROM contents")
                        conn.execute("DELETE FROM meta WHERE key='npz_import'")
                except sqlite3.Error:
                    return 0
            else:
                return 0
        if not os.path.exists(self.legacy_cache_file):
            return 0
        try:
            data = np.load(self.legacy_cache_file, allow_pickle=True)
            emb = np.asarray(data["embeddings"], dtype=np.float32)
        except Exception:
            self._set_meta(conn, "npz_import", "unreadable")
            return 0
        n_rows = int(emb.shape[0]) if emb.ndim == 2 else 0
        if n_rows == 0:
            self._set_meta(conn, "npz_import", "empty")
            return 0

        # old cache -> relkey per row
        keys: List[Optional[str]] = []
        sizes: List[Optional[int]] = []
        if "relkeys" in data.files:
            keys = [self._to_str(x) for x in data["relkeys"]]
            if "sizes" in data.files:
                sizes = [int(x) for x in data["sizes"]]
        else:
            # very old cache: full path per row, no relkeys
            by_full, by_name = self._index_current_files()
            for p in (self._to_str(x) for x in data["paths"]):
                full = p if os.path.isabs(p) else os.path.join(self.db_folder, p)
                target = by_full.get(full) or by_full.get(os.path.normpath(full))
                if target is None:
                    cand = by_name.get(os.path.basename(p)) or []
                    target = cand[0] if len(cand) == 1 else None
                keys.append(self._relkey(target) if target else None)
                sizes.append(None)

        groups: Dict[str, List[int]] = {}
        for i, k in enumerate(keys[:n_rows]):
            if k:
                groups.setdefault(k, []).append(i)
        if not groups:
            self._set_meta(conn, "npz_import", "no-matching-files")
            return 0

        imported = 0
        total_groups = len(groups)
        # mark the upgrade as running: if the app dies mid-way the next run
        # restarts it instead of silently re-embedding the remaining pictures
        self._set_meta(conn, "npz_import", "in-progress")
        # normalise the whole matrix in place (one pass, no per-file alloc)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        emb /= norms

        contents_batch: List[tuple] = []
        files_batch: List[tuple] = []

        def flush_migrate() -> None:
            if not files_batch:
                return
            try:
                with conn:
                    if contents_batch:
                        conn.executemany(
                            "INSERT OR IGNORE INTO contents"
                            "(hash,size,n_faces,dim,vec) VALUES(?,?,?,?,?)",
                            contents_batch,
                        )
                    conn.executemany(
                        "INSERT OR REPLACE INTO files"
                        "(relkey,size,mtime,hash) VALUES(?,?,?,?)",
                        files_batch,
                    )
            except sqlite3.Error:
                pass
            if self._shared and contents_batch:
                try:
                    with conn:
                        conn.executemany(
                            "INSERT OR IGNORE INTO shared.contents"
                            "(hash,size,n_faces,dim,vec) VALUES(?,?,?,?,?)",
                            contents_batch,
                        )
                except sqlite3.Error:
                    self._shared = False
            contents_batch.clear()
            files_batch.clear()

        for j, (rk, idxs) in enumerate(groups.items(), start=1):
            if self._stop_requested():
                break
            path = self._path_of_relkey(rk)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if (
                sizes
                and idxs[0] < len(sizes)
                and sizes[idxs[0]] is not None
                and int(sizes[idxs[0]]) != st.st_size
            ):
                continue  # file replaced since the old cache was written
            h = self._hash_file(path)
            if h is None:
                continue
            block = emb[idxs]
            if block.ndim != 2:
                continue
            contents_batch.append(
                (h, int(st.st_size), int(block.shape[0]), int(block.shape[1]),
                 block.tobytes())
            )
            files_batch.append((rk, int(st.st_size), int(st.st_mtime), h))
            imported += 1
            if len(files_batch) >= 400:
                flush_migrate()
                self._emit(j, total_groups,
                           _p(f"กำลังแปลงแคชรุ่นเก่า ({j:,}/{total_groups:,})", f"Converting the old cache ({j:,}/{total_groups:,})"))
        flush_migrate()
        if self._stop_requested():
            # roll the partial upgrade back; the next run starts it again
            try:
                with conn:
                    conn.execute("DELETE FROM files")
                    conn.execute("DELETE FROM contents")
                    conn.execute("DELETE FROM meta WHERE key='npz_import'")
            except sqlite3.Error:
                pass
            return 0
        conn.commit()
        self._set_meta(conn, "npz_import", str(imported))
        self._new_contents += imported
        return imported

    # ------------------------------------------------------------------- build
    def build(self) -> np.ndarray:
        """Embed every DB image (with the content-addressed on-disk cache).

        A file is skipped when its relkey + size + mtime match the cache
        (stat only). Otherwise its bytes are hashed: an unchanged file hits
        its cached embedding (and the new mtime is saved); a file whose
        content was already seen elsewhere — moved, renamed, copied, or in a
        different DB folder — also hits. Only genuinely new pictures call the
        model.

        The cache connection is always closed — also when the build raises —
        so the folder never stays locked on Windows.
        """
        try:
            return self._build()
        finally:
            self.close()

    def _build(self) -> np.ndarray:
        assets = model_assets(self.model_name, self.detector)
        if not assets["ready"]:
            self._emit(
                0, 0,
                _p(
                    f"ไม่พบไฟล์โมเดล ({', '.join(assets['missing'])}) — "
                    f"กำลังดาวน์โหลดประมาณ {assets['download_mb']:,} MB "
                    "(ต้องใช้อินเทอร์เน็ต เฉพาะครั้งแรก)…",
                    f"Model files missing ({', '.join(assets['missing'])}) — "
                    f"downloading ~{assets['download_mb']:,} MB "
                    "(internet needed, first run only)…",
                ),
            )
            logger.warning(
                "model files missing in %s: %s",
                assets["dir"], ", ".join(assets["missing"]),
            )
        else:
            self._emit(0, 0, _p("กำลังตรวจรายชื่อรูปในโฟลเดอร์…", "Scanning the photo folder…"))
        logger.info("build started: %s / %s @ %s", self.model_name,
                    self.detector, self.db_folder)

        t0 = time.time()
        files = self._scan_db()
        total = len(files)
        logger.info("found %d image files", total)
        prev_rows = self._assembled_rows
        prev_embeddings, prev_paths = self.embeddings, self.paths
        self._rows = []
        self._meta = {}
        self._dim = 0
        self._shared_hits = 0
        self._new_contents = 0
        self.stats = {}

        conn = self._open_cache()
        self._attach_shared(conn)
        migrated = self._migrate_legacy_npz(conn)
        manifest = self._load_manifest(conn)
        # one query instead of one SELECT per picture
        for h, n, d in conn.execute("SELECT hash, n_faces, dim FROM contents"):
            self._meta[h] = (int(n), int(d))
        seen: set = set()

        self._emit(0, total, _p("กำลังอ่านข้อมูลที่วิเคราะห์ไว้…", "Reading analysed data…") if not migrated
                   else _p("กำลังแปลงแคชรุ่นเก่า…", "Converting the old cache…"))

        cached = 0          # files served from cache
        embedded = 0        # files that needed the model
        no_face = 0         # processed but no usable face
        failed = 0          # model call raised -> retried next run
        fails = 0           # consecutive failures
        pending_contents: List[tuple] = []
        pending_files: List[tuple] = []
        last_flush = time.time()
        last_emit = 0.0

        def flush_if_due(force: bool = False) -> None:
            nonlocal last_flush
            now = time.time()
            if force or len(pending_files) >= 25 or (now - last_flush) >= 1.5:
                self._flush_batch(conn, pending_contents, pending_files)
                last_flush = now

        for i, (path, size, mtime) in enumerate(files, start=1):
            if self._stop_requested():
                break
            rk = self._relkey(path)
            seen.add(rk)

            row = manifest.get(rk)
            c_size = row[0] if row else None
            c_mtime = row[1] if row else None
            c_hash = row[2] if row else None

            # 1) stat-only fast path (nothing changed since last run)
            if (
                row is not None
                and c_size == size
                and c_mtime == mtime
                and c_hash
            ):
                meta = self._content_meta(conn, c_hash)
                if meta is not None:
                    cached += 1
                    if meta[0] > 0:
                        self._rows.append((path, c_hash))
                    else:
                        no_face += 1
                    if i % 10 == 0 or i == total:
                        now = time.time()
                        if now - last_emit > 0.12 or i == total:
                            last_emit = now
                            self._emit(i, total, self._phase(i, total, cached, embedded))
                    continue

            # 2) content changed / moved / unknown -> identify by bytes
            h = self._hash_file(path)
            if h is None:
                continue  # unreadable right now; retry on the next run
            meta = self._content_meta(conn, h)
            if meta is not None:
                # same content as something we already embedded
                cached += 1
                pending_files.append((rk, size, mtime, h))
                if meta[0] > 0:
                    self._rows.append((path, h))
                else:
                    no_face += 1
            else:
                # 3) genuinely new content -> run the model once
                try:
                    embs = self._represent(path)
                    fails = 0
                except UnreadableImage:
                    # broken/truncated/not-really-an-image file: not an
                    # environment problem, so it must not count towards the
                    # FAIL_LIMIT abort. Retried next run (it may be mid-copy).
                    failed += 1
                    logger.warning("unreadable image skipped: %s", rk)
                    conn.execute("DELETE FROM files WHERE relkey=?", (rk,))
                    embs = None
                except Exception as exc:
                    # Never persist a failed model call. A transient problem
                    # (TensorFlow, memory, disk, driver) would otherwise mark
                    # thousands of photos as "no face" forever. This one file
                    # is skipped and retried on the next run, and its cached
                    # (older) row is left untouched.
                    fails += 1
                    failed += 1
                    logger.warning("model call failed for %s: %s", rk, exc)
                    if fails >= FAIL_LIMIT and embedded == 0:
                        # keep whatever succeeded earlier in this pass
                        flush_if_due(force=True)
                        logger.exception("aborting: %d consecutive failures", fails)
                        hint = ""
                        if not assets["ready"]:
                            hint = _p(
                                "\n\nไม่พบไฟล์โมเดลในโฟลเดอร์:\n"
                                f"{assets['dir']}\n"
                                "หากไม่มีอินเทอร์เน็ต ให้คัดลอกโฟลเดอร์ 'models' "
                                "จากเครื่องที่ใช้งานได้มาวางไว้ข้าง Deeface.exe",
                                "\n\nThe model files are missing from:\n"
                                f"{assets['dir']}\n"
                                "Without internet, copy the 'models' folder from "
                                "a working PC next to Deeface.exe.",
                            )
                        raise RuntimeError(
                            _p(
                                f"วิเคราะห์รูปไม่สำเร็จติดต่อกัน {fails} รูป "
                                "และยังไม่มีรูปใดสำเร็จเลย — น่าจะเป็นปัญหาที่"
                                f"โปรแกรมหรือไฟล์โมเดล ไม่ใช่ที่ตัวรูป: {exc}{hint}",
                                f"{fails} photos in a row failed before a single "
                                "success — this looks like an environment/model "
                                f"problem, not the photos: {exc}{hint}",
                            )
                        ) from exc
                    # drop any stale row for this path so a later run cannot
                    # stat-hit the old content and skip the retry
                    conn.execute("DELETE FROM files WHERE relkey=?", (rk,))
                    embs = None
                if embs is None:
                    pass  # transient failure -> retry next run
                elif embs:
                    block = self._normalise_rows(np.vstack(embs))
                    n_faces, dim = int(block.shape[0]), int(block.shape[1])
                    if self._dim == 0:
                        self._dim = dim
                    pending_contents.append(
                        (h, size, n_faces, dim, block.tobytes())
                    )
                    self._meta[h] = (n_faces, dim)
                    self._rows.append((path, h))
                    embedded += 1
                    pending_files.append((rk, size, mtime, h))
                else:
                    # model ran fine but returned no usable face -> remember it
                    pending_contents.append((h, size, 0, 0, b""))
                    self._meta[h] = (0, 0)
                    no_face += 1
                    pending_files.append((rk, size, mtime, h))

            flush_if_due()
            if i % 10 == 0 or i == total:
                now = time.time()
                if now - last_emit > 0.12 or i == total:
                    last_emit = now
                    self._emit(i, total, self._phase(i, total, cached, embedded))

        stopped = self._stop_requested()
        flush_if_due(force=True)

        # A completed scan may drop rows for files that no longer exist.
        if not stopped and total:
            stale = [(rk,) for rk in manifest if rk not in seen]
            if stale:
                try:
                    with conn:
                        conn.executemany("DELETE FROM files WHERE relkey=?", stale)
                except sqlite3.Error:
                    pass

        # Assemble the in-memory matrix in scan order — unless the folder is
        # exactly as it was for the previous search on this object, in which
        # case the matrix we already hold is reused (repeat searches are then
        # just: scan folder + embed the target).
        if (
            prev_rows is not None
            and prev_embeddings is not None
            and prev_rows == self._rows
        ):
            self.embeddings, self.paths = prev_embeddings, prev_paths
            self._dim = int(prev_embeddings.shape[1]) if prev_embeddings.ndim == 2 else 0
        else:
            self._assemble(conn)
        if not stopped:
            self._assembled_rows = list(self._rows)
        else:
            self._assembled_rows = None
        self.cache_files, self.cache_faces = self._cache_counts(conn)

        if not stopped and self._new_contents:
            self._sync_shared(conn)

        self.build_seconds = time.time() - t0
        self.stats = {
            "total": total,
            "cached": cached,
            "new": embedded,
            "no_face": no_face,
            "failed": failed,
            "rows": int(self.embeddings.shape[0]) if self.embeddings is not None else 0,
            "files": self.cache_files,
            "faces": self.cache_faces,
            "migrated": migrated,
            "shared_hits": self._shared_hits,
            "seconds": self.build_seconds,
            "cache_file": self.cache_file,
            "stopped": stopped,
        }
        tail = _p(f" · ข้าม {failed:,} รูปที่เปิดไม่ได้ (จะลองใหม่รอบหน้า)",
                  f" · {failed:,} unreadable photos skipped (retried next run)") if failed else ""
        logger.info(
            "build done in %.1fs: %d files, cached %d, new %d, no_face %d, "
            "failed %d, faces %d",
            self.build_seconds, total, cached, embedded, no_face, failed,
            self.stats["rows"],
        )
        self._emit(
            total,
            total,
            _p(
                f"เสร็จแล้ว — ใช้ข้อมูลเดิม {cached:,} รูป · วิเคราะห์ใหม่ {embedded:,} รูป · "
                f"รวม {self.stats['rows']:,} ใบหน้า{tail}",
                f"Done — {cached:,} reused · {embedded:,} newly analysed · "
                f"{self.stats['rows']:,} faces total{tail}",
            ),
        )
        # close() runs in build()'s finally, so the folder is never left locked.
        return self.embeddings if self.embeddings is not None else np.zeros((0, 512), np.float32)

    @staticmethod
    def _phase(i: int, total: int, cached: int, embedded: int) -> str:
        if embedded:
            return _p(
                f"ใช้ข้อมูลเดิม {cached:,} · วิเคราะห์ใหม่ {embedded:,} — "
                f"ตรวจแล้ว {i:,}/{total:,} รูป",
                f"{cached:,} reused · {embedded:,} newly analysed — "
                f"checked {i:,}/{total:,}",
            )
        return _p(
            f"ใช้ข้อมูลเดิม {cached:,} รูป (ไม่ต้องวิเคราะห์ซ้ำ) — ตรวจแล้ว {i:,}/{total:,} รูป",
            f"{cached:,} photos reused (nothing re-analysed) — "
            f"checked {i:,}/{total:,}",
        )

    def _assemble(self, conn: sqlite3.Connection) -> None:
        # The dimension is decided by the majority of the rows we actually
        # have, not by whichever content happened to be looked up first. A
        # cache that contains a few rows from another model build (or a
        # polluted shared row) then still yields a usable matrix instead of
        # silently dropping almost every face.
        counts: Dict[int, int] = {}
        for _, h in self._rows:
            n, d = self._meta[h]
            if n > 0 and d > 0:
                counts[d] = counts.get(d, 0) + n
        if not counts:
            self.embeddings = np.zeros((0, self._dim or 512), dtype=np.float32)
            self.paths = []
            return
        dim = max(counts, key=lambda d: (counts[d], d))
        self._dim = dim

        rows_total = sum(
            self._meta[h][0] for _, h in self._rows if self._meta[h][1] == dim
        )
        emb = np.empty((rows_total, dim), dtype=np.float32)
        paths: List[str] = []
        pos = 0
        for path, h in self._rows:
            n, d = self._meta[h]
            if n <= 0 or d != dim:
                continue
            vec = self._fetch_vec(conn, h)
            if vec is None or vec.size != n * dim:
                continue
            emb[pos:pos + n] = vec.reshape(n, dim)
            paths.extend([path] * n)
            pos += n
        self.embeddings = emb[:pos]
        self.paths = paths

    @staticmethod
    def _cache_counts(conn: sqlite3.Connection) -> Tuple[int, int]:
        try:
            files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            faces = int(
                conn.execute(
                    "SELECT COALESCE(SUM(c.n_faces),0) FROM files f "
                    "JOIN contents c ON c.hash = f.hash"
                ).fetchone()[0]
            )
        except sqlite3.Error:
            return 0, 0
        return files, faces

    def flush(self) -> None:
        """Persist any pending cache state (safe to call anytime)."""
        if self._conn is not None:
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        self.flush()
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def clear_cache(self) -> None:
        self.close()
        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)

    # -------------------------------------------------------------- reporting
    @classmethod
    def cache_summary(
        cls,
        db_folder: str,
        model_name: str = DEFAULT_MODEL,
        detector: str = DEFAULT_DETECTOR,
    ) -> dict:
        """Cheap, read-only cache status for the GUI."""
        db_folder = os.path.abspath(db_folder or ".")
        safe = _safe_name(model_name)
        path = os.path.join(db_folder, CACHE_DIRNAME, f"faces_{safe}.{detector}.sqlite3")
        legacy = os.path.join(db_folder, CACHE_DIRNAME, f"rep_{safe}.{detector}.npz")
        out = {
            "ready": False,
            "legacy": os.path.exists(legacy),
            "path": path,
            "files": 0,
            "faces": 0,
            "size": 0,
        }
        if os.path.exists(path):
            try:
                conn = sqlite3.connect(path, timeout=5)
                try:
                    out["files"], out["faces"] = cls._cache_counts(conn)
                finally:
                    conn.close()
                out["ready"] = out["files"] > 0 or out["faces"] > 0
                out["size"] = os.path.getsize(path)
            except Exception:
                pass
        elif out["legacy"]:
            try:
                out["size"] = os.path.getsize(legacy)
            except OSError:
                pass
        return out

    # -------------------------------------------------------------------- match
    # A DB row with this many near-identical (cos >= HUB_SIM) rows is a
    # collapsed embedding, not a person. deepface's ArcFace collapses ~5 %
    # of the production photos (808 rows) into one such cluster, which then
    # "matched" unrelated search photos at ~99 %. Buffalo_L has none.
    HUB_SIM = 0.95
    HUB_COUNT = 20

    def _mark_hubs(self, matrix: np.ndarray, rows, cache: Dict[int, bool]) -> None:
        todo = [int(r) for r in rows if int(r) not in cache]
        if not todo:
            return
        sims = matrix @ matrix[todo].T            # (N, len(todo))
        counts = (sims >= self.HUB_SIM).sum(axis=0)
        for r, c in zip(todo, counts):
            cache[r] = int(c) >= self.HUB_COUNT

    def match_target(self, target_image: str, top_n: int = 3) -> List[Match]:
        img = read_image(target_image)
        try:
            if img is None:
                raise UnreadableImage(target_image)
            found = self._target_faces(img)
            faces = [e for e, _ in found]
            boxes = [b for _, b in found]
        except UnreadableImage:
            raise RuntimeError(
                _p(f"เปิดรูปที่ต้องการค้นหาไม่ได้ (ไฟล์เสียหรือไม่ใช่ไฟล์รูปภาพ): {target_image}",
                   f"Cannot open the photo to search (damaged or not an image file): "
                   f"{target_image}")
            ) from None
        if not faces:
            raise NoFaceInTarget(
                _p("ไม่พบใบหน้าในรูปที่ค้นหา — กรุณาใช้รูปที่เห็นหน้าชัด หันหน้าตรง และไม่มืดเกินไป",
                   "No face was found in the photo — please use a clear, "
                   "front-facing, well-lit photo"))
        if self.embeddings is None or self.embeddings.shape[0] == 0:
            return []

        # Embeddings are stored L2-normalised, so cosine distance is 1 - dot.
        matrix = self.embeddings
        mdim = int(matrix.shape[1])
        if any(emb.size != mdim for emb in faces):
            got = sorted({int(emb.size) for emb in faces})
            raise RuntimeError(
                _p(
                    f"ข้อมูลในแคชมี {mdim} มิติ แต่โมเดลที่เลือกให้ {got} มิติ — "
                    "แคชอาจมาจากโมเดลอื่นหรือโปรแกรมรุ่นอื่น "
                    "กรุณากด ♻ ล้างแคช แล้วค้นหาใหม่",
                    f"The cache holds {mdim}-dim embeddings but the current model "
                    f"returns {got} dims — the cache may come from another "
                    "version/model. Press 'Clear cache' and search again.",
                )
            )
        # Best distance per *file*. 1.3 ranked matrix rows, so a DB photo
        # containing two faces could fill two of the three result slots.
        best: Dict[str, float] = {}
        best_face: Dict[str, int] = {}
        hub_cache: Dict[int, bool] = {}
        for fi, emb in enumerate(faces):
            n = float(np.linalg.norm(emb))
            if n == 0:
                continue
            q = emb / n
            d = 1.0 - (matrix @ q)
            k = min(d.shape[0], max(top_n * 4, 40))
            cand = np.argpartition(d, k - 1)[:k] if k < d.shape[0] else np.arange(d.shape[0])
            self._mark_hubs(matrix, cand, hub_cache)
            if sum(1 for c in cand if not hub_cache[int(c)]) < top_n and k < d.shape[0]:
                # most candidates were broken embeddings: look further
                k = min(d.shape[0], 400)
                cand = np.argpartition(d, k - 1)[:k]
                self._mark_hubs(matrix, cand, hub_cache)
            for idx in cand:
                i = int(idx)
                if hub_cache.get(i):
                    continue
                p = self.paths[i]
                di = float(d[i])
                if p not in best or di < best[p]:
                    best[p] = di
                    best_face[p] = fi
        ranked = sorted(best.items(), key=lambda kv: kv[1])
        matches: List[Match] = []
        for p, dist in ranked[:top_n]:
            matches.append(
                Match(
                    path=p,
                    distance=dist,
                    employee_id=os.path.splitext(os.path.basename(p))[0],
                    target_box=(boxes[best_face[p]]
                                if best_face.get(p, -1) < len(boxes) else None),
                )
            )
        return matches[:top_n]
