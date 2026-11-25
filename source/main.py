# -*- coding: utf-8 -*-
"""Deeface — ค้นหาใบหน้าพนักงานจากฐานข้อมูลรูปภาพ (GUI).

ชื่อไฟล์รูปในโฟลเดอร์ฐานข้อมูลคือรหัสพนักงาน (เช่น 10234.jpg => 10234)
เลือกโฟลเดอร์ฐานข้อมูล + รูปเป้าหมาย แล้วกด "ค้นหา"

v1.5 interface: blue monochrome palette with light/dark mode, Thai/English,
top-5 results with similarity bars and an enlarged preview on hover.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageOps

import face_search_core as core
import ui_theme as ui

APP_TITLE = "Deeface"
APP_VERSION = "1.6.0"

ctk.set_default_color_theme("blue")  # every widget below sets its own colours

_LOG_FILE = None
_LOG_PATH = ""


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


def _setup_logging() -> str:
    """Send every message (ours, DeepFace's download progress, tracebacks) to
    ``Deeface.log`` beside the exe.

    A windowed exe has no console, so when it stalls on a user's PC this file
    is the only way to see what it was doing. Falls back to %LOCALAPPDATA%
    when the program folder is read-only.
    """
    global _LOG_FILE, _LOG_PATH
    folders = [base_dir()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        folders.append(os.path.join(local, "Deeface"))

    for folder in folders:
        path = os.path.join(folder, "Deeface.log")
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > 4 * 1024 * 1024:
                os.replace(path, path + ".old")
            fh = open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            continue

        _LOG_FILE = fh
        _LOG_PATH = path
        # DeepFace prints to stdout; a windowed exe has none.
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh
        handler = logging.StreamHandler(fh)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        return path
    return ""


_setup_logging()
logger = logging.getLogger("deeface")


def _user_settings_path() -> str:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or base_dir()
    return os.path.join(base, "Deeface", "settings.json")


def _dir_writable(folder: str) -> bool:
    probe = os.path.join(folder, ".deeface_write_test")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


# Portable copy (exe on a USB stick / D:\...): settings.json lives beside the
# exe as before. Installed copy (C:\Program Files...): that folder is
# read-only for a normal user, so 1.3 silently lost every setting on exit.
# Then settings go to %APPDATA%\Deeface\settings.json instead.
_PORTABLE = _dir_writable(base_dir())
SETTINGS_PATH = (os.path.join(base_dir(), "settings.json") if _PORTABLE
                 else _user_settings_path())


def load_settings() -> dict:
    # an installed copy may ship a default settings.json beside the exe
    for p in (SETTINGS_PATH, os.path.join(base_dir(), "settings.json")):
        try:
            # utf-8-sig: Notepad/PowerShell may save the file with a BOM,
            # which plain utf-8 json.load rejects
            with open(p, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            continue
    return {}


def save_settings(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)  # never leave a half-written file
    except Exception:  # noqa: BLE001
        logger.warning("could not save settings to %s", SETTINGS_PATH)


TOP_N = 5          # results shown per search
THUMB = 84         # result thumbnail size (px)
PREVIEW = 300      # enlarged hover preview size (px)


def _thumb(path: str, size: int, box=None) -> Image.Image | None:
    """Load a picture (Unicode-safe, EXIF-rotated) shrunk to fit ``size``.

    ``box`` = (x, y, w, h) crops to that face first, with some margin, so a
    group photo shows the person who was actually matched."""
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        if box:
            x, y, w, h = box
            if w < im.width * 0.9 or h < im.height * 0.9:
                m = int(max(w, h) * 0.6)
                im = im.crop((max(0, x - m), max(0, y - m),
                              min(im.width, x + w + m), min(im.height, y + h + m)))
        im.thumbnail((size, size), Image.LANCZOS)
        if box and max(im.size) < size:  # small face: enlarge for viewing
            r = size / float(max(im.size))
            im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                           Image.LANCZOS)
        return im
    except Exception:  # noqa: BLE001
        return None


class HoverPreview(ctk.CTkToplevel):
    """Borderless pop-up with the search photo and the match side by side."""

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=ui.BORDER)
        self._app = app
        self._refs: list = []
        box = ctk.CTkFrame(self, fg_color=ui.SURFACE, corner_radius=0)
        box.pack(padx=1, pady=1)
        self._cols = []
        for _ in range(2):
            col = ctk.CTkFrame(box, fg_color="transparent")
            col.pack(side="left", padx=10, pady=10)
            img = ctk.CTkLabel(col, text="", width=PREVIEW, height=PREVIEW,
                               fg_color=ui.SURFACE_2, corner_radius=8)
            img.pack()
            cap = ctk.CTkLabel(col, text="", text_color=ui.TEXT)
            cap.pack(pady=(8, 0))
            self._cols.append((img, cap))

    def show(self, x: int, y: int, items) -> None:
        """items: [(PIL image or None, caption), (…)]"""
        self._refs.clear()
        f = self._app.f
        for (img_lbl, cap_lbl), (im, caption) in zip(self._cols, items):
            if im is not None:
                photo = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                self._refs.append(photo)
                img_lbl.configure(image=photo, text="")
            else:
                img_lbl.configure(image=None, text="—")
            cap_lbl.configure(text=caption, font=f.b(13, True))
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        px = x + 24 if x + 24 + w < sw else x - w - 24
        py = min(max(8, y - h // 2), sh - h - 48)
        self.geometry(f"+{max(8, px)}+{py}")
        self.deiconify()
        self.lift()

    def hide(self) -> None:
        self.withdraw()


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()
        # One-time move to the more accurate default (v1.6). Afterwards the
        # user's own choice in the menus is kept.
        if int(self._settings.get("defaults_version", 0) or 0) < 2:
            if (self._settings.get("model") in (None, "ArcFace", "VGG-Face")
                    and self._settings.get("detector") in (None, "opencv")):
                self._settings["model"] = core.DEFAULT_MODEL
                self._settings["detector"] = core.DEFAULT_DETECTOR
                logger.info("settings migrated to %s/%s",
                            core.DEFAULT_MODEL, core.DEFAULT_DETECTOR)
            self._settings["defaults_version"] = 2
            save_settings(self._settings)
        self.lang = ("en" if str(self._settings.get("lang", "th")).lower()
                     .startswith("en") else "th")
        core.set_ui_lang(self.lang)
        theme = self._settings.get("theme", "system")
        ctk.set_appearance_mode(theme if theme in ("light", "dark") else "system")

        self.f = ui.Typography(self.lang)
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry("1220x800")
        self.minsize(1060, 680)
        self.configure(fg_color=ui.BG)

        self._stop = threading.Event()
        self._searcher: core.FaceSearch | None = None
        self._busy = False
        self._t0 = 0.0
        self._progress_value = 0.0
        self._phase_text = ""
        self._status: dict = {"key": "ready_line", "kw": {}, "tone": "info", "text": ""}
        self._assets: dict = {}
        self._cache_info: dict | None = None
        self._search_stats: dict | None = None
        self._last_matches: list = []
        self._last_model = core.DEFAULT_MODEL
        self._last_target = ""
        self._photo_refs: list = []
        self._target = str(self._settings.get("target", "") or "")
        self._target_thumb_cache: dict = {}
        self._hover_job = None
        self.hover = HoverPreview(self)

        model = self._settings.get("model", core.DEFAULT_MODEL)
        self._model = model if model in core.MODELS else core.DEFAULT_MODEL
        det = self._settings.get("detector", core.DEFAULT_DETECTOR)
        self._detector = det if det in core.DETECTORS else core.DEFAULT_DETECTOR

        self._build_ui()
        self._prewarm()
        self._refresh_model_info()
        self._refresh_cache_info()
        self._status_key("ready_line", "info")

    # ------------------------------------------------------------- helpers
    def t(self, key: str, **kw) -> str:
        s = ui.strings(self.lang).get(key, key)
        try:
            return s.format(**kw) if kw else s
        except (KeyError, IndexError, ValueError):
            return s

    def _build_ui(self) -> None:
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self._build_header()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=18)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self._build_side(body)
        self._build_results(body)
        self._render_model_line()
        self._render_cache_line()
        self._render_results()

    # -------------------------------------------------------------- header
    def _build_header(self) -> None:
        self.header = ui.Gradient(self, height=78)
        self.header.pack(fill="x")
        self._header_title = self.header.create_text(
            26, 28, anchor="w", text=self.t("app_title"), fill="#FFFFFF",
            font=(self.f.num, 22, "bold"))
        self._header_sub = self.header.create_text(
            27, 55, anchor="w", text=self.t("app_subtitle"), fill="#D7E7FA",
            font=(self.f.body, 11))

        self.theme_seg = ui.segmented(
            self.header, [self.t("theme_light"), self.t("theme_dark")],
            self._on_theme, self.f.b(12, True))
        self.lang_seg = ui.segmented(
            self.header, [self.t("lang_th"), self.t("lang_en")],
            self._on_lang, self.f.b(12, True))
        self._theme_win = self.header.create_window(0, 39, window=self.theme_seg, anchor="e")
        self._lang_win = self.header.create_window(0, 39, window=self.lang_seg, anchor="e")
        self.header.bind("<Configure>", self._layout_header, add="+")
        self._sync_header_controls()

    def _layout_header(self, _e=None) -> None:
        w = self.header.winfo_width()
        self.header.coords(self._lang_win, w - 24, 39)
        lang_w = self.lang_seg.winfo_reqwidth()
        self.header.coords(self._theme_win, w - 24 - lang_w - 14, 39)

    def _sync_header_controls(self) -> None:
        self.theme_seg.set(self.t("theme_dark") if ui.mode() == "dark"
                           else self.t("theme_light"))
        self.lang_seg.set(self.t("lang_th") if self.lang == "th" else self.t("lang_en"))
        edge = ui.GRADIENT[ui.mode()][-1]
        for seg in (self.theme_seg, self.lang_seg):
            seg.configure(bg_color=edge)

    def _on_theme(self, value: str) -> None:
        new = "dark" if value == self.t("theme_dark") else "light"
        ctk.set_appearance_mode(new)
        self._settings["theme"] = new
        save_settings(self._settings)
        self.header.redraw()
        self._sync_header_controls()
        self._render_results()  # pop-up/badge colours are resolved per mode

    def _on_lang(self, value: str) -> None:
        code = "th" if value == self.t("lang_th") else "en"
        if code == self.lang:
            return
        self.lang = code
        core.set_ui_lang(code)
        self._settings["lang"] = code
        save_settings(self._settings)
        logger.info("UI language -> %s", code)
        self.f = ui.Typography(code)
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        db = self.sdb.get()
        status = dict(self._status)
        self.hover.hide()
        for w in self.winfo_children():
            if w is not self.hover:
                w.destroy()
        self._build_ui()
        self.sdb.delete(0, "end")
        self.sdb.insert(0, db)
        self.progress.set(self._progress_value)
        if status.get("key"):
            status["text"] = self.t(status["key"], **status.get("kw", {}))
        self._apply_status(status)
        if self._busy:
            self._set_busy_buttons(True)

    # ---------------------------------------------------------- side panel
    def _build_side(self, parent) -> None:
        side = ui.card(parent, width=380)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 18))
        side.grid_propagate(False)
        side.pack_propagate(False)
        inner = ctk.CTkFrame(side, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        # 1 — employee folder
        ui.section_title(inner, "1", self.t("step1"), self.f).pack(anchor="w")
        ctk.CTkLabel(inner, text=self.t("step1_hint"), font=self.f.b(12),
                     text_color=ui.MUTED).pack(anchor="w", pady=(4, 8))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.sdb = ui.entry(row, self.t("db_placeholder"), self.f.b(13))
        self.sdb.pack(side="left", fill="x", expand=True)
        self.sdb.insert(0, self._settings.get("db_folder", ""))
        self.sdb.bind("<Return>", lambda _e: (self._persist(), self._refresh_cache_info()))
        self.btn_db = ui.secondary_button(row, self.t("db_button"), self._pick_db,
                                          self.f.b(13, True), width=104)
        self.btn_db.pack(side="left", padx=(8, 0))

        # 2 — photo to search
        ui.section_title(inner, "2", self.t("step2"), self.f).pack(anchor="w", pady=(20, 8))
        prow = ctk.CTkFrame(inner, fg_color="transparent")
        prow.pack(fill="x")
        self.target_preview = ctk.CTkLabel(
            prow, text=self.t("preview_empty"), width=132, height=132,
            corner_radius=10, fg_color=ui.SURFACE_2, text_color=ui.MUTED,
            font=self.f.b(12), cursor="hand2")
        self.target_preview.pack(side="left")
        self.target_preview.bind("<Button-1>", lambda _e: self._pick_target())
        pcol = ctk.CTkFrame(prow, fg_color="transparent")
        pcol.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.target_name = ctk.CTkLabel(pcol, text="", font=self.f.b(12),
                                        text_color=ui.TEXT, anchor="w",
                                        justify="left", wraplength=180)
        self.target_name.pack(anchor="w", fill="x")
        self.btn_target = ui.secondary_button(pcol, self.t("target_button"),
                                              self._pick_target, self.f.b(13, True),
                                              width=120)
        self.btn_target.pack(anchor="w", side="bottom")
        self._render_target()

        # model
        mrow = ctk.CTkFrame(inner, fg_color="transparent")
        mrow.pack(fill="x", pady=(20, 0))
        ctk.CTkLabel(mrow, text=self.t("model_label"), font=self.f.b(13),
                     text_color=ui.MUTED).pack(side="left")
        self.model_var = ui.option_menu(mrow, core.MODELS, self.f.b(13), width=150)
        self.model_var.set(self._model)
        self.model_var.configure(command=self._model_changed)
        self.model_var.pack(side="right")

        drow = ctk.CTkFrame(inner, fg_color="transparent")
        drow.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(drow, text=self.t("detector_label"), font=self.f.b(13),
                     text_color=ui.MUTED).pack(side="left")
        self._det_by_label = {ui.DETECTOR_LABELS.get(d, d): d for d in core.DETECTORS}
        self.det_var = ui.option_menu(drow, list(self._det_by_label), self.f.b(13),
                                      width=150)
        self.det_var.set(ui.DETECTOR_LABELS.get(self._detector, self._detector))
        self.det_var.configure(command=self._detector_changed)
        self.det_var.pack(side="right")

        # actions
        arow = ctk.CTkFrame(inner, fg_color="transparent")
        arow.pack(fill="x", pady=(18, 0))
        self.btn_search = ui.primary_button(arow, "🔍  " + self.t("search"),
                                            self._start_search, self.f.b(16, True),
                                            height=46)
        self.btn_search.pack(side="left", fill="x", expand=True)
        self.btn_stop = ui.danger_button(arow, self.t("stop"), self._stop_requested,
                                         self.f.b(14, True), width=84, height=46)
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_stop.configure(state="disabled")

        self.progress = ctk.CTkProgressBar(inner, height=6, corner_radius=3,
                                           fg_color=ui.SURFACE_2,
                                           progress_color=ui.ACCENT)
        self.progress.pack(fill="x", pady=(14, 8))
        self.progress.set(self._progress_value)
        self.status_lbl = ctk.CTkLabel(inner, text="", font=self.f.b(13),
                                       anchor="w", justify="left",
                                       text_color=ui.MUTED, wraplength=330)
        self.status_lbl.pack(fill="x")

        # bottom: model / cache state + clear cache
        bottom = ctk.CTkFrame(inner, fg_color="transparent")
        bottom.pack(side="bottom", fill="x")
        ctk.CTkFrame(bottom, height=1, fg_color=ui.BORDER).pack(fill="x", pady=(0, 12))
        self.model_line = ui.StatusLine(bottom, self.f.b(11, True), self.f.b(12))
        self.model_line.pack(fill="x", pady=(0, 6))
        self.cache_line = ui.StatusLine(bottom, self.f.b(11, True), self.f.b(12))
        self.cache_line.pack(fill="x")
        self.btn_reset = ui.ghost_button(bottom, "♻  " + self.t("reset"),
                                         self._reset_cache, self.f.b(12),
                                         width=120, height=32)
        self.btn_reset.pack(anchor="e", pady=(10, 0))

    def _render_target(self) -> None:
        path = self._target
        im = _thumb(path, 132) if path and os.path.isfile(path) else None
        if im is None:
            self.target_preview.configure(image=None, text=self.t("preview_empty"))
            self.target_name.configure(text=self.t("target_placeholder"),
                                       text_color=ui.MUTED)
            return
        photo = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
        self._target_photo = photo
        self.target_preview.configure(image=photo, text="")
        self.target_name.configure(text=os.path.basename(path), text_color=ui.TEXT)

    # ------------------------------------------------------------- results
    def _build_results(self, parent) -> None:
        panel = ui.card(parent)
        panel.grid(row=0, column=1, sticky="nsew")
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 0))
        ctk.CTkLabel(head, text=self.t("results_title"), font=self.f.h(20),
                     text_color=ui.TEXT).pack(side="left")
        ctk.CTkLabel(head, text=self.t("results_hint"), font=self.f.b(12),
                     text_color=ui.MUTED).pack(side="left", padx=14, pady=(4, 0))
        self.results = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=ui.BORDER,
            scrollbar_button_hover_color=ui.ACCENT)
        self.results.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        ctk.CTkLabel(panel, text="ⓘ  " + self.t("results_note"), font=self.f.b(11),
                     text_color=ui.MUTED).pack(anchor="w", padx=22, pady=(0, 12))

    def _render_results(self) -> None:
        if not hasattr(self, "results"):
            return
        for w in self.results.winfo_children():
            w.destroy()
        self._photo_refs.clear()
        if not self._last_matches:
            ctk.CTkLabel(self.results, text=self.t("results_empty"),
                         font=self.f.b(15), text_color=ui.MUTED,
                         justify="center").pack(pady=120)
            return
        for i, m in enumerate(self._last_matches):
            self._add_result_row(i, m)

    def _add_result_row(self, i: int, m: core.Match) -> None:
        level = ui.match_level(self._last_model, m.distance)
        colour = ui.LEVEL_COLOUR[level]
        best = i == 0
        row = ctk.CTkFrame(self.results, corner_radius=12,
                           fg_color=ui.PRIMARY_SOFT if best else ui.SURFACE_2,
                           border_width=2 if best else 0, border_color=ui.PRIMARY)
        row.pack(fill="x", padx=8, pady=5)

        ctk.CTkLabel(row, text=str(i + 1), width=36, height=36, corner_radius=18,
                     fg_color=ui.PRIMARY if best else ui.SURFACE,
                     text_color=ui.ON_PRIMARY if best else ui.TEXT,
                     font=self.f.n(15)).pack(side="left", padx=(14, 12), pady=12)

        im = _thumb(m.path, THUMB)
        if im is not None:
            photo = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self._photo_refs.append(photo)
            pic = ctk.CTkLabel(row, image=photo, text="", width=THUMB, height=THUMB,
                               fg_color=ui.SURFACE, corner_radius=8, cursor="hand2")
        else:
            pic = ctk.CTkLabel(row, text="—", width=THUMB, height=THUMB,
                               fg_color=ui.SURFACE, corner_radius=8)
        pic.pack(side="left", pady=10)
        self._bind_hover(pic, m)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=(16, 8))
        ctk.CTkLabel(info, text=self.t("employee_id_label"), font=self.f.b(11),
                     text_color=ui.MUTED, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=m.employee_id, font=self.f.n(22),
                     text_color=ui.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=os.path.basename(m.path), font=self.f.b(11),
                     text_color=ui.MUTED, anchor="w").pack(anchor="w")

        score = ctk.CTkFrame(row, fg_color="transparent", width=230)
        score.pack(side="left", padx=8)
        top = ctk.CTkFrame(score, fg_color="transparent")
        top.pack(fill="x")
        pct = max(0.0, min(100.0, m.similarity))
        ctk.CTkLabel(top, text=f"{pct:.1f}%", font=self.f.n(22),
                     text_color=colour).pack(side="left")
        ctk.CTkLabel(top, text=self.t("level_" + level), font=self.f.b(12, True),
                     text_color=colour).pack(side="left", padx=(10, 0), pady=(6, 0))
        bar = ctk.CTkProgressBar(score, width=220, height=8, corner_radius=4,
                                 fg_color=ui.SURFACE, progress_color=colour)
        bar.set(pct / 100.0)
        bar.pack(anchor="w", pady=(6, 0))

        make = ui.primary_button if best else ui.secondary_button
        copy = make(row, self.t("copy"), None, self.f.b(12, True),
                    width=108, height=34)
        copy.configure(command=lambda em=m.employee_id, b=copy: self._copy(em, b))
        copy.pack(side="right", padx=(8, 16))

    # ----------------------------------------------------- hover enlarging
    def _bind_hover(self, widget, m: core.Match) -> None:
        def enter(e):
            self._cancel_hover()
            self._hover_job = self.after(
                120, lambda: self._show_hover(e.x_root, e.y_root, m))

        def leave(_e):
            self._cancel_hover()
            self.hover.hide()

        for w in (widget, *widget.winfo_children()):
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    def _cancel_hover(self) -> None:
        if self._hover_job is not None:
            try:
                self.after_cancel(self._hover_job)
            except Exception:  # noqa: BLE001
                pass
            self._hover_job = None

    def _show_hover(self, x: int, y: int, m: core.Match) -> None:
        self._hover_job = None
        key = (self._last_target, m.target_box)
        if key not in self._target_thumb_cache:
            if len(self._target_thumb_cache) > 16:
                self._target_thumb_cache.clear()
            self._target_thumb_cache[key] = _thumb(self._last_target, PREVIEW,
                                                   m.target_box)
        items = [
            (self._target_thumb_cache[key], self.t("hover_target")),
            (_thumb(m.path, PREVIEW),
             self.t("hover_match", id=m.employee_id, pct=m.similarity)),
        ]
        self.hover.show(x, y, items)

    # -------------------------------------------------------------- pickers
    def _prewarm(self) -> None:
        """Load ONNX Runtime + the face model in the background so the first
        search does not wait for it."""
        model, detector = self._model, self._detector

        def _run():
            try:
                # warm-up only loads the model; it does not touch the folder
                core.FaceSearch(db_folder=base_dir(), model_name=model,
                                detector=detector).warmup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("prewarm failed: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    def _pick_db(self) -> None:
        d = ctk.filedialog.askdirectory(title=self.t("db_label"))
        if d:
            self.sdb.delete(0, "end")
            self.sdb.insert(0, os.path.normpath(d))
            self._persist()
            self._refresh_cache_info()

    def _pick_target(self) -> None:
        if self._busy:
            return
        start = os.path.dirname(self._target) if self._target else ""
        f = ctk.filedialog.askopenfilename(
            title=self.t("target_label"), initialdir=start or None,
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("All files", "*.*")],
        )
        if f:
            self._target = os.path.normpath(f)
            self._render_target()
            self._persist()

    def _detector_changed(self, label) -> None:
        self._detector = self._det_by_label.get(label, core.DEFAULT_DETECTOR)
        self._persist()
        self._refresh_model_info()
        self._refresh_cache_info()

    def _model_changed(self, value) -> None:
        self._model = value
        self._persist()
        self._refresh_model_info()
        self._refresh_cache_info()

    def _persist(self) -> None:
        self._settings.update({
            "db_folder": self.sdb.get().strip(),
            "target": self._target,
            "model": self._model,
            "detector": self._detector,
            "lang": self.lang,
        })
        save_settings(self._settings)

    # ------------------------------------------------------ model / cache UI
    def _refresh_model_info(self) -> None:
        self._assets = core.model_assets(self._model, self._detector)
        self._render_model_line()

    def _render_model_line(self) -> None:
        if not hasattr(self, "model_line") or not self._assets:
            return
        if self._assets["ready"]:
            name = f"{self._model} + {ui.DETECTOR_LABELS.get(self._detector, self._detector)}"
            self.model_line.set(self.t("status_model"),
                                self.t("model_ready", model=name), "success")
        else:
            self.model_line.set(
                self.t("status_model"),
                self.t("model_missing", model=self._model,
                       mb=self._assets["download_mb"], folder=core.MODELS_DIRNAME),
                "error")

    def _refresh_cache_info(self) -> None:
        db = self.sdb.get().strip()
        model, detector = self._model, self._detector
        if not db or not os.path.isdir(db):
            self._cache_info = None
            self._render_cache_line()
            return

        def _run():
            try:
                info = core.FaceSearch.cache_summary(db, model, detector)
            except Exception:  # noqa: BLE001
                info = None
            self.after(0, lambda: self._apply_cache_info(info))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_cache_info(self, info) -> None:
        self._cache_info = info
        self._render_cache_line()

    def _render_cache_line(self) -> None:
        if not hasattr(self, "cache_line"):
            return
        label = self.t("status_cache")
        if self._search_stats:
            s = self._search_stats
            parts = [self.t("stats_cached", n=s.get("cached", 0))]
            if s.get("new"):
                parts.append(self.t("stats_new", n=s["new"]))
            if s.get("no_face"):
                parts.append(self.t("stats_no_face", n=s["no_face"]))
            if s.get("failed"):
                parts.append(self.t("stats_failed", n=s["failed"]))
            parts.append(self.t("stats_faces", faces=s.get("faces", 0)))
            parts.append(self.t("stats_seconds", s=s.get("seconds", 0.0)))
            self.cache_line.set(label, " · ".join(parts), "success")
            return
        info = self._cache_info
        if not info:
            self.cache_line.set(label, self.t("cache_missing_dir"), "neutral")
        elif info["ready"]:
            self.cache_line.set(label, self.t(
                "cache_ready", files=info["files"], faces=info["faces"],
                mb=info["size"] / (1024 * 1024)), "success")
        elif info["legacy"]:
            self.cache_line.set(label, self.t("cache_legacy"), "warning")
        else:
            self.cache_line.set(label, self.t("cache_none"), "warning")

    # -------------------------------------------------------------- status
    def _apply_status(self, status: dict) -> None:
        self._status = status
        if hasattr(self, "status_lbl"):
            self.status_lbl.configure(
                text=status.get("text", ""),
                text_color=ui.TONE_FG.get(status.get("tone", "neutral"), ui.MUTED))

    def _set_status(self, text: str, tone: str = "neutral", key: str = "", **kw) -> None:
        self._apply_status({"text": text, "tone": tone, "key": key, "kw": kw})

    def _status_key(self, key: str, tone: str = "neutral", **kw) -> None:
        self._set_status(self.t(key, **kw), tone, key=key, **kw)

    def _set_busy_buttons(self, busy: bool) -> None:
        self.btn_search.configure(state="disabled" if busy else "normal")
        self.btn_reset.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")
        self.model_var.configure(state="disabled" if busy else "normal")
        self.det_var.configure(state="disabled" if busy else "normal")

    # ---------------------------------------------------------- cache reset
    def _reset_cache(self) -> None:
        db = self.sdb.get().strip()
        if not db or not os.path.isdir(db):
            self._status_key("need_db", "error")
            return
        if not messagebox.askyesno(self.t("reset_title"), self.t("reset_body")):
            return
        try:
            core.FaceSearch(db, self._model, self._detector).clear_cache()
            self._search_stats = None
            self._searcher = None  # drop the in-memory matrix as well
            self._status_key("cache_cleared", "success")
            logger.info("cache cleared: %s", db)
        except Exception as e:  # noqa: BLE001
            logger.exception("cache reset failed")
            self._set_status(f"{self.t('error_title')}: {e}", "error")
        self._refresh_cache_info()

    # -------------------------------------------------------------- search
    def _stop_requested(self) -> None:
        self._stop.set()
        self.btn_stop.configure(state="disabled")
        self._status_key("stopping", "warning")
        self._phase_text = self.t("stopping")

    def _start_search(self) -> None:
        db = self.sdb.get().strip()
        target = self._target
        if not db or not os.path.isdir(db):
            self._status_key("need_db", "error")
            return
        if not target or not os.path.isfile(target):
            self._status_key("need_target", "error")
            return

        assets = core.model_assets(self._model, self._detector)
        if not assets["ready"] and not messagebox.askyesno(
            self.t("download_title"),
            self.t("download_body", model=self._model,
                   mb=assets["download_mb"], folder=core.MODELS_DIRNAME),
        ):
            self._status_key("cancel_no_model", "warning")
            return

        self._persist()
        self._stop.clear()
        self._search_stats = None
        self._set_busy_buttons(True)
        self.progress.set(0)
        self._progress_value = 0.0
        self._busy = True
        self._t0 = time.time()
        self._phase_text = self.t("starting")
        self._status_key("starting", "info")
        self.after(1000, self._tick)
        self._last_matches = []
        self._render_results()
        model, detector = self._model, self._detector
        logger.info("search requested: db=%s target=%s model=%s/%s", db, target,
                    model, detector)
        # Tk widgets must only be read on the UI thread, so the worker gets
        # plain values.
        threading.Thread(target=self._search_worker,
                         args=(db, target, model, detector), daemon=True).start()

    def _tick(self) -> None:
        """Show elapsed time next to the current phase."""
        if not self._busy:
            return
        secs = int(time.time() - self._t0)
        if secs >= 3 and hasattr(self, "status_lbl"):
            base = self._phase_text or self.t("starting")
            self.status_lbl.configure(
                text=f"{base}   ⏱ {self.t('seconds_short', s=secs)}")
        self.after(1000, self._tick)

    def _search_worker(self, db: str, target: str, model: str,
                       detector: str) -> None:
        def cb(done, total, phase):
            self.after(0, lambda: self._progress(done, total, phase))

        fs = None
        try:
            prev = self._searcher
            if (
                prev is not None
                and prev.db_folder == os.path.abspath(db)
                and prev.model_name == model
                and prev.detector == detector
            ):
                # same folder + model: keep the in-memory face matrix
                fs = prev
                fs._progress_cb = cb
                fs._stop_event = self._stop
            else:
                fs = core.FaceSearch(db_folder=db, model_name=model,
                                     detector=detector, enforce_detection=False,
                                     progress_cb=cb, stop_event=self._stop)
            self._searcher = fs
            fs.build()
            if self._stop.is_set():
                self.after(0, self._show_stopped)
                return
            matches = fs.match_target(target, top_n=TOP_N)
            stats = dict(fs.stats)
            logger.info("search finished: %s", stats)
            self.after(0, lambda: self._show_results(matches, stats, model))
        except core.NoFaceInTarget as e:
            logger.info("no face in target: %s", target)
            msg = str(e)
            self.after(0, lambda: self._show_no_face(msg))
        except Exception as e:  # noqa: BLE001
            logger.exception("search failed")
            msg = str(e) or type(e).__name__
            self.after(0, lambda: self._show_error(msg))
        finally:
            if fs is not None:
                try:
                    fs.close()
                except Exception:  # noqa: BLE001
                    pass
            self.after(0, self._search_done)

    def _search_done(self) -> None:
        self._busy = False
        self._set_busy_buttons(False)

    def _progress(self, done, total, phase) -> None:
        frac = (done / total) if total else 0
        self._progress_value = frac
        self.progress.set(frac)
        self._phase_text = phase
        if hasattr(self, "status_lbl"):
            self.status_lbl.configure(text=phase, text_color=ui.MUTED)

    # ------------------------------------------------------------- results
    def _show_error(self, msg: str) -> None:
        self._busy = False
        self._progress_value = 1
        self.progress.set(1)
        text = msg.strip() or self.t("error_title")
        self._set_status(text.splitlines()[0], "error")
        detail = text
        if _LOG_PATH:
            detail += "\n\n" + self.t("log_hint", path=_LOG_PATH)
        try:
            messagebox.showerror(self.t("error_title"), detail)
        except Exception:  # noqa: BLE001
            pass

    def _show_no_face(self, msg: str) -> None:
        self._busy = False
        self._progress_value = 1
        self.progress.set(1)
        self._last_matches = []
        self._render_results()
        self._set_status(msg, "warning")

    def _show_stopped(self) -> None:
        self._busy = False
        self._progress_value = 1
        self.progress.set(1)
        self._status_key("stopped", "warning")

    def _show_results(self, matches, stats=None, model=None) -> None:
        self._busy = False
        self._search_stats = stats or None
        self._last_model = model or self._model
        self._last_target = self._target
        self._last_matches = list(matches or [])
        self._render_cache_line()
        self._render_results()
        self.progress.set(1)
        self._progress_value = 1
        if not matches:
            self._status_key("no_match", "warning")
            return
        best = matches[0]
        self._set_status(
            self.t("best", id=best.employee_id, pct=best.similarity), "success",
            key="best", id=best.employee_id, pct=best.similarity)

    def _copy(self, text: str, btn=None) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:  # noqa: BLE001
            pass
        if btn is not None:
            try:
                btn.configure(text=self.t("copied"))
                self.after(1400, lambda: btn.winfo_exists()
                           and btn.configure(text=self.t("copy")))
            except Exception:  # noqa: BLE001
                pass


def _selftest(argv: list) -> int:
    """Headless check used after building:
    ``Deeface.exe --selftest <db_folder> <target> [model]``.
    Results go to Deeface.log; exit code 0 = a match was found."""
    db, target = argv[0], argv[1]
    model = argv[2] if len(argv) > 2 else core.DEFAULT_MODEL
    detector = argv[3] if len(argv) > 3 else core.DEFAULT_DETECTOR
    t0 = time.time()
    try:
        fs = core.FaceSearch(db, model, detector)
        fs.build()
        matches = fs.match_target(target, top_n=3)
    except Exception:  # noqa: BLE001
        logger.exception("SELFTEST FAILED")
        return 2
    logger.info("SELFTEST %s/%s in %.2fs: stats=%s", model, detector, time.time() - t0,
                {k: fs.stats.get(k) for k in ("total", "cached", "new", "failed", "rows")})
    for m in matches:
        logger.info("SELFTEST match %s %.1f%% %s", m.employee_id, m.similarity, m.path)
    return 0 if matches else 1


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest":
        logger.info("=== Deeface v%s selftest ===", APP_VERSION)
        sys.exit(_selftest(sys.argv[2:]))
    logger.info("=== Deeface v%s starting (frozen=%s, python=%s) ===",
                APP_VERSION, getattr(sys, "frozen", False), sys.version.split()[0])
    logger.info("program dir: %s", base_dir())
    logger.info("DEEPFACE_HOME: %s", os.environ.get("DEEPFACE_HOME", "(default)"))
    assets = core.model_assets(core.DEFAULT_MODEL, core.DEFAULT_DETECTOR)
    logger.info("weights dir: %s | ready=%s | missing=%s",
                assets["dir"], assets["ready"], assets["missing"])
    if _LOG_PATH:
        logger.info("log file: %s", _LOG_PATH)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
