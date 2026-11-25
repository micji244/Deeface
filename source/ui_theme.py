# -*- coding: utf-8 -*-
"""Deeface theme (v1.5) — blue monochrome palette, light & dark mode,
fonts, bilingual strings and small widget helpers.

Every colour is a ``(light, dark)`` pair, the form customtkinter understands
natively: ``ctk.set_appearance_mode("light" | "dark")`` then recolours the
whole window live, without rebuilding it.
"""
from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont
from typing import Iterable, Optional, Sequence, Tuple

import customtkinter as ctk

logger = logging.getLogger("deeface")

# ------------------------------------------------------------------ palette
#              light        dark
BG =        ("#EEF4FB", "#0B1422")   # window background
SURFACE =   ("#FFFFFF", "#111E33")   # cards
SURFACE_2 = ("#E3EDF9", "#182A47")   # inputs, hover, badges
BORDER =    ("#C7D7EC", "#243B61")
TEXT =      ("#0E2747", "#E4EEFB")
MUTED =     ("#5A7393", "#8EA7C7")
PRIMARY =   ("#1F62C4", "#4C93F0")   # main action, strong match
PRIMARY_HOVER = ("#184F9F", "#3A7BD6")
PRIMARY_SOFT = ("#D6E6FA", "#1B3560")  # tinted backgrounds
ACCENT =    ("#4E9BE8", "#7DB8F7")   # medium match, progress
LOW =       ("#9AAEC6", "#4E6584")   # weak match
ON_PRIMARY = ("#FFFFFF", "#FFFFFF")
DANGER =    ("#C0392B", "#F07167")
DANGER_SOFT = ("#FBE3E0", "#3A1D22")
SUCCESS =   ("#1F62C4", "#6FB1FA")   # "ready" lines stay in the blue family

# header gradient, left -> right
GRADIENT = {
    "light": ("#163F7A", "#2D6FC4", "#6AAEF0"),
    "dark": ("#081427", "#0F2C57", "#1D4F94"),
}

TONE_FG = {
    "neutral": MUTED, "info": TEXT, "success": SUCCESS,
    "warning": ACCENT, "error": DANGER,
}


def mode() -> str:
    return "dark" if ctk.get_appearance_mode().lower() == "dark" else "light"


def pick(colour) -> str:
    """Resolve a (light, dark) pair for plain Tk widgets / PIL."""
    if isinstance(colour, (tuple, list)):
        return colour[1] if mode() == "dark" else colour[0]
    return colour


# -------------------------------------------------------------------- fonts
def load_fonts() -> None:
    """Kept for compatibility; v1.5 uses the system UI fonts below."""


def _families() -> set:
    try:
        return set(tkfont.families())
    except Exception:  # noqa: BLE001
        return set()


def pick_family(preferred: str, fallbacks: Iterable[str]) -> str:
    have = _families()
    for name in (preferred, *fallbacks):
        if name in have:
            return name
    return "Segoe UI"


class Typography:
    """Clean sans-serif UI fonts that ship with Windows 10/11."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        if lang == "th":
            self.body = pick_family("Leelawadee UI", ("Leelawadee", "Tahoma"))
        else:
            self.body = pick_family("Segoe UI", ("Tahoma", "Arial"))
        self.head = self.body
        self.num = pick_family("Segoe UI", ("Tahoma", "Arial"))  # IDs, %

    def h(self, size: int, bold: bool = True) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.head, size=size,
                           weight="bold" if bold else "normal")

    def b(self, size: int, bold: bool = False) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.body, size=size,
                           weight="bold" if bold else "normal")

    def n(self, size: int, bold: bool = True) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.num, size=size,
                           weight="bold" if bold else "normal")


# ----------------------------------------------------------------- strings
I18N = {
    "th": {
        "app_title": "Deeface",
        "app_subtitle": "ค้นหารหัสพนักงานจากรูปใบหน้า",
        "lang_th": "ไทย",
        "lang_en": "EN",
        "theme_light": "☀  สว่าง",
        "theme_dark": "☾  มืด",
        "step1": "โฟลเดอร์รูปพนักงาน",
        "step1_hint": "ชื่อไฟล์รูปคือรหัสพนักงาน เช่น 10234.jpg",
        "db_label": "เลือกโฟลเดอร์รูปพนักงาน",
        "db_placeholder": "ยังไม่ได้เลือกโฟลเดอร์",
        "db_button": "เลือกโฟลเดอร์",
        "step2": "รูปที่ต้องการค้นหา",
        "target_label": "เลือกรูปที่ต้องการค้นหา",
        "target_placeholder": "ยังไม่ได้เลือกรูป",
        "target_button": "เลือกรูป",
        "preview_empty": "ยังไม่ได้เลือกรูป\nคลิกเพื่อเลือก",
        "model_label": "โมเดลจดจำใบหน้า",
        "detector_label": "ตัวหาตำแหน่งหน้า",
        "combo_hint_new": "ชุดนี้ยังไม่มีแคช — ค้นหาครั้งแรกจะวิเคราะห์รูปทั้งหมดใหม่ (ครั้งเดียว)",
        "search": "ค้นหา",
        "stop": "หยุด",
        "reset": "ล้างแคช",
        "ready_line": "พร้อมใช้งาน — เลือกโฟลเดอร์และรูป แล้วกด “ค้นหา”",
        "status_model": "โมเดล",
        "status_cache": "แคช",
        "cache_missing_dir": "ยังไม่ได้เลือกโฟลเดอร์รูปพนักงาน",
        "cache_ready": "วิเคราะห์ไว้แล้ว {files:,} รูป · {faces:,} ใบหน้า ({mb:,.0f} MB) — รูปเดิมไม่ต้องวิเคราะห์ซ้ำ",
        "cache_legacy": "พบแคชรุ่นเก่า — ระบบจะแปลงให้อัตโนมัติครั้งเดียว (ประมาณ 1 นาที)",
        "cache_none": "ยังไม่มีแคช — การค้นหาครั้งแรกต้องวิเคราะห์รูปทั้งหมด อาจใช้เวลานาน",
        "model_ready": "{model} พร้อมใช้งาน",
        "model_missing": "ไม่พบไฟล์โมเดล {model} — ต้องดาวน์โหลดประมาณ {mb:,} MB หรือคัดลอกโฟลเดอร์ “{folder}” มาไว้ข้างโปรแกรม",
        "results_title": "ผลการค้นหา",
        "results_hint": "5 คนที่หน้าคล้ายที่สุด · ชี้เมาส์ที่รูปเพื่อขยาย",
        "results_empty": "เลือกรูปแล้วกด “ค้นหา”\nผลลัพธ์ 5 อันดับแรกจะแสดงที่นี่",
        "results_note": "ผลลัพธ์เป็นการประมาณจากโมเดล โปรดตรวจสอบด้วยตาอีกครั้งก่อนนำไปใช้",
        "employee_id_label": "รหัสพนักงาน",
        "similarity": "เหมือน {pct:.1f}%",
        "level_high": "เหมือนมาก",
        "level_mid": "อาจเป็นคนเดียวกัน",
        "level_low": "ไม่ค่อยเหมือน",
        "copy": "คัดลอกรหัส",
        "copied": "คัดลอกแล้ว ✓",
        "starting": "กำลังเริ่มต้น…",
        "need_db": "กรุณาเลือกโฟลเดอร์รูปพนักงานให้ถูกต้อง",
        "need_target": "กรุณาเลือกรูปที่ต้องการค้นหา",
        "stopping": "กำลังหยุด…",
        "stopped": "หยุดแล้ว — ผลที่วิเคราะห์ไปแล้วถูกบันทึกไว้ ครั้งถัดไปจะทำต่อจากเดิม",
        "reset_title": "ล้างแคช",
        "reset_body": "ต้องการลบข้อมูลใบหน้าที่วิเคราะห์ไว้ของโฟลเดอร์นี้ใช่หรือไม่?\n\nการค้นหาครั้งถัดไปจะต้องวิเคราะห์รูปทั้งหมดใหม่ ซึ่งอาจใช้เวลานาน",
        "cache_cleared": "ลบแคชแล้ว — การค้นหาครั้งถัดไปจะวิเคราะห์รูปทั้งหมดใหม่",
        "error_title": "ค้นหาไม่สำเร็จ",
        "log_hint": "ดูรายละเอียดได้ที่ไฟล์บันทึก:\n{path}",
        "download_title": "ไม่พบไฟล์โมเดล",
        "download_body": "เครื่องนี้ยังไม่มีไฟล์โมเดล {model}\n\nต้องดาวน์โหลดประมาณ {mb:,} MB (ครั้งแรกครั้งเดียว อาจใช้เวลาหลายนาที)\n\nหากเครื่องนี้ไม่มีอินเทอร์เน็ต ให้กด “ไม่” แล้วคัดลอกโฟลเดอร์ “{folder}” จากเครื่องที่ใช้งานได้มาไว้ข้าง Deeface.exe\n\nต้องการดาวน์โหลดเลยหรือไม่?",
        "cancel_no_model": "ยกเลิกแล้ว — ยังไม่มีไฟล์โมเดล",
        "no_match": "ไม่พบรูปที่ใกล้เคียง — ลองใช้รูปที่เห็นหน้าชัดและหันหน้าตรง",
        "best": "น่าจะเป็นรหัส {id}  (เหมือน {pct:.1f}%)",
        "stats_cached": "ใช้ข้อมูลเดิม {n:,} รูป",
        "stats_new": "วิเคราะห์ใหม่ {n:,} รูป",
        "stats_no_face": "ไม่พบหน้า {n:,} รูป",
        "stats_failed": "ข้าม {n:,} รูป (จะลองใหม่รอบหน้า)",
        "stats_faces": "รวม {faces:,} ใบหน้า",
        "stats_seconds": "{s:.1f} วินาที",
        "seconds_short": "{s:,} วินาที",
        "hover_target": "รูปที่ค้นหา",
        "hover_match": "รหัส {id} · เหมือน {pct:.1f}%",
    },
    "en": {
        "app_title": "Deeface",
        "app_subtitle": "Find an employee ID from a face photo",
        "lang_th": "ไทย",
        "lang_en": "EN",
        "theme_light": "☀  Light",
        "theme_dark": "☾  Dark",
        "step1": "Employee photo folder",
        "step1_hint": "Each file name is the employee ID, e.g. 10234.jpg",
        "db_label": "Choose the employee photo folder",
        "db_placeholder": "No folder selected",
        "db_button": "Browse",
        "step2": "Photo to search",
        "target_label": "Choose the photo to search",
        "target_placeholder": "No photo selected",
        "target_button": "Choose photo",
        "preview_empty": "No photo selected\nClick to choose one",
        "model_label": "Recognition model",
        "detector_label": "Face detector",
        "combo_hint_new": "No cache for this combination yet — the first search analyses every photo once",
        "search": "Search",
        "stop": "Stop",
        "reset": "Clear cache",
        "ready_line": "Ready — choose a folder and a photo, then press “Search”",
        "status_model": "Model",
        "status_cache": "Cache",
        "cache_missing_dir": "No employee photo folder selected yet",
        "cache_ready": "{files:,} photos · {faces:,} faces already analysed ({mb:,.0f} MB) — unchanged photos are not re-analysed",
        "cache_legacy": "Old cache format found — it will be converted automatically once (about 1 minute)",
        "cache_none": "No cache yet — the first search must analyse every photo and can take a while",
        "model_ready": "{model} is ready",
        "model_missing": "Model file for {model} not found — download about {mb:,} MB or copy the “{folder}” folder next to the program",
        "results_title": "Search results",
        "results_hint": "The 5 most similar faces · hover a photo to enlarge it",
        "results_empty": "Choose a photo and press “Search”\nThe top 5 matches will appear here",
        "results_note": "Results are model estimates — please confirm them visually before use",
        "employee_id_label": "Employee ID",
        "similarity": "{pct:.1f}% similar",
        "level_high": "Very similar",
        "level_mid": "Possible match",
        "level_low": "Unlikely",
        "copy": "Copy ID",
        "copied": "Copied ✓",
        "starting": "Starting…",
        "need_db": "Please choose a valid employee photo folder",
        "need_target": "Please choose the photo to search",
        "stopping": "Stopping…",
        "stopped": "Stopped — progress so far is saved and the next run continues from here",
        "reset_title": "Clear cache",
        "reset_body": "Delete the analysed face data for this folder?\n\nThe next search will have to analyse every photo again, which can take a long time.",
        "cache_cleared": "Cache cleared — the next search will analyse every photo again",
        "error_title": "Search failed",
        "log_hint": "Details are in the log file:\n{path}",
        "download_title": "Model file not found",
        "download_body": "This PC does not have the {model} model file yet.\n\nAbout {mb:,} MB must be downloaded once (this can take several minutes).\n\nIf this PC has no internet, press “No” and copy the “{folder}” folder from a working PC next to Deeface.exe.\n\nDownload now?",
        "cancel_no_model": "Cancelled — the model file is missing",
        "no_match": "No similar photo found — try a clear, front-facing photo",
        "best": "Most likely employee {id}  ({pct:.1f}% similar)",
        "stats_cached": "{n:,} reused",
        "stats_new": "{n:,} newly analysed",
        "stats_no_face": "{n:,} without a face",
        "stats_failed": "{n:,} skipped (retried next run)",
        "stats_faces": "{faces:,} faces in total",
        "stats_seconds": "{s:.1f} s",
        "seconds_short": "{s:,} s",
        "hover_target": "Search photo",
        "hover_match": "ID {id} · {pct:.1f}% similar",
    },
}


def strings(lang: str) -> dict:
    return I18N.get(lang, I18N["th"])


# ------------------------------------------------------------- match levels
# deepface's own cosine-distance thresholds ("same person" below them). They
# are tuned for 1:1 verification and are too generous when one photo is
# compared with ~17,000 people, so the labels use stricter fractions:
#   very similar  <= 55 % of the threshold
#   possible      <= 75 % of the threshold
THRESHOLDS = {"VGG-Face": 0.68, "Facenet512": 0.30, "ArcFace": 0.68,
              "Buffalo_L": 0.55}


# Each model spreads similarities differently. Buffalo_L was calibrated on
# the real D:\TEMP data (true matches ~50-70 %, other people ~25-40 %);
# the others keep the threshold fractions above.
LEVEL_CUTOFFS = {  # (very similar, possible) in similarity %
    "Buffalo_L": (55.0, 42.0),
}


def match_level(model: str, distance: float) -> str:
    if model in LEVEL_CUTOFFS:
        hi, mid = LEVEL_CUTOFFS[model]
        sim = (1.0 - distance) * 100.0
        return "high" if sim >= hi else ("mid" if sim >= mid else "low")
    thr = THRESHOLDS.get(model, 0.68)
    if distance <= thr * 0.55:
        return "high"
    if distance <= thr * 0.75:
        return "mid"
    return "low"


LEVEL_COLOUR = {"high": PRIMARY, "mid": ACCENT, "low": LOW}

DETECTOR_LABELS = {"yunet": "YuNet", "opencv": "OpenCV"}


# ------------------------------------------------------------------ widgets
class Gradient(tk.Canvas):
    """Horizontal gradient band (Tk has no gradients, so we paint strips)."""

    def __init__(self, master, height: int) -> None:
        super().__init__(master, height=height, highlightthickness=0, bd=0)
        self._items = []
        self.bind("<Configure>", lambda _e: self.redraw())

    @staticmethod
    def _hex(c: str) -> Tuple[int, int, int]:
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    def redraw(self) -> None:
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        stops = [self._hex(c) for c in GRADIENT[mode()]]
        self.delete("grad")
        step = 4
        for x in range(0, w, step):
            t = x / max(1, w - 1) * (len(stops) - 1)
            i = min(int(t), len(stops) - 2)
            f = t - i
            a, b = stops[i], stops[i + 1]
            col = "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
            self.create_rectangle(x, 0, x + step, h, fill=col, outline=col, tags="grad")
        self.tag_lower("grad")


class StatusLine(ctk.CTkFrame):
    """A small tinted label (Model / Cache) followed by an explanation."""

    def __init__(self, master, font_chip, font_body) -> None:
        super().__init__(master, fg_color="transparent")
        self.chip = ctk.CTkLabel(self, text="", font=font_chip, width=56,
                                 corner_radius=6, fg_color=PRIMARY_SOFT,
                                 text_color=PRIMARY)
        self.chip.pack(side="left", anchor="n", pady=1)
        self.text = ctk.CTkLabel(self, text="", font=font_body, anchor="w",
                                 justify="left", text_color=MUTED,
                                 fg_color="transparent", wraplength=250)
        self.text.pack(side="left", padx=(8, 0), fill="x", expand=True)

    def set(self, prefix: str, text: str, tone: str = "neutral") -> None:
        soft = DANGER_SOFT if tone == "error" else PRIMARY_SOFT
        fg = DANGER if tone == "error" else PRIMARY
        self.chip.configure(text=prefix, fg_color=soft, text_color=fg)
        self.text.configure(text=text, text_color=TONE_FG.get(tone, MUTED))


def primary_button(master, text, command, font, width=200, height=44) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, font=font,
        width=width, height=height, corner_radius=10,
        fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY,
        text_color_disabled=("#E8F0FA", "#9FB4D1"),
    )


def secondary_button(master, text, command, font, width=140, height=38) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, font=font,
        width=width, height=height, corner_radius=8,
        fg_color=PRIMARY_SOFT, hover_color=BORDER, text_color=PRIMARY,
        border_width=0,
    )


def ghost_button(master, text, command, font, width=130, height=38) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, font=font,
        width=width, height=height, corner_radius=8,
        fg_color="transparent", hover_color=SURFACE_2, text_color=MUTED,
        border_width=1, border_color=BORDER,
    )


def danger_button(master, text, command, font, width=110, height=44) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, font=font,
        width=width, height=height, corner_radius=10,
        fg_color="transparent", hover_color=DANGER_SOFT, text_color=DANGER,
        border_width=1, border_color=DANGER,
        text_color_disabled=LOW,
    )


def card(master, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=SURFACE, corner_radius=14,
                        border_width=1, border_color=BORDER, **kw)


def entry(master, placeholder: str, font) -> ctk.CTkEntry:
    e = ctk.CTkEntry(
        master, placeholder_text=placeholder, font=font,
        height=38, corner_radius=8, fg_color=SURFACE_2,
        border_color=BORDER, border_width=1,
        text_color=TEXT, placeholder_text_color=MUTED,
    )
    e.bind("<FocusIn>", lambda _e: e.configure(border_color=PRIMARY))
    e.bind("<FocusOut>", lambda _e: e.configure(border_color=BORDER))
    return e


def option_menu(master, values: Sequence[str], font, width=170) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        master, values=list(values), font=font, width=width, height=38,
        corner_radius=8, fg_color=SURFACE_2, button_color=PRIMARY_SOFT,
        button_hover_color=BORDER, text_color=TEXT,
        dropdown_fg_color=SURFACE, dropdown_hover_color=SURFACE_2,
        dropdown_text_color=TEXT, dropdown_font=font,
    )


def segmented(master, values: Sequence[str], command, font) -> ctk.CTkSegmentedButton:
    """Pill switch used in the header (on the gradient, so fixed colours)."""
    return ctk.CTkSegmentedButton(
        master, values=list(values), command=command, font=font, height=30,
        corner_radius=15, fg_color=("#123566", "#0A1B36"),
        selected_color=("#4E9BE8", "#4C93F0"),
        selected_hover_color=("#3F8BDA", "#3A7BD6"),
        unselected_color=("#123566", "#0A1B36"),
        unselected_hover_color=("#1D4A86", "#15305A"),
        text_color=("#FFFFFF", "#FFFFFF"),
        text_color_disabled=("#9FB4D1", "#6C83A3"),
    )


def section_title(master, number: str, text: str, f: Typography) -> ctk.CTkFrame:
    row = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(row, text=number, width=26, height=26, corner_radius=13,
                 fg_color=PRIMARY, text_color=ON_PRIMARY,
                 font=f.n(13)).pack(side="left")
    ctk.CTkLabel(row, text=text, font=f.b(15, True),
                 text_color=TEXT).pack(side="left", padx=(10, 0))
    return row
