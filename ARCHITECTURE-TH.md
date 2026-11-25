# Deeface — โครงสร้างการทำงานทั้งหมด (v1.3.0)

> เอกสารอ้างอิงถาวรสำหรับพัฒนาต่อ — เขียนจากโค้ดจริง ณ v1.3.0
> อัปเดต: 2026-11 (offline models, QuestUI theme + TH/EN, log file, content-addressed cache)

## 1. ภาพรวมโปรเจกต์

แอป GUI (customtkinter, QuestUI dark theme) สำหรับค้นหาใบหน้าพนักงานจาก
ฐานข้อมูลรูปหลักหมื่นไฟล์ — ชื่อไฟล์คือรหัสพนักงาน (เช่น `10234.jpg` → `10234`)
รองรับภาษาไทย/อังกฤษ สลับได้ทันทีจากหน้าจอ

```
D:\TPIPL\11-2026\Deeface\
├── Deeface.exe            ← .exe ที่ deploy (v1.3.0, one-file)
├── models\                ← โมเดล AI ที่แนบมากับโปรแกรม (.deepface\weights)
├── Deeface.log            ← log ล่าสุด (สร้างอัตโนมัติ)
├── settings.json          ← ค่าที่จำไว้ (โฟลเดอร์, โมเดล, ภาษา)
├── README-TH.md           ← คู่มือผู้ใช้
├── ARCHITECTURE-TH.md     ← ไฟล์นี้
├── New folder\            ← รูปทดสอบ/เป้าหมายตัวอย่าง (616884.jpg, 10377.jpg...)
└── source\
    ├── face_search_core.py ← โค้ด core (headless, ไม่พึ่ง GUI)
    ├── main.py             ← GUI (customtkinter)
    ├── ui_theme.py         ← QuestUI theme + ฟอนต์ + ข้อความ TH/EN + widget
    ├── assets\fonts\       ← Cinzel / Spectral / Noto Serif Thai (.ttf)
    ├── Deeface.spec        ← PyInstaller spec (แนบ assets\fonts เข้า exe)
    ├── version_info.txt    ← Windows version resource (1.3.0.0)
    ├── deeface.ico         ← ไอคอน
    └── .venv\              ← Python 3.13 venv (สร้างใหม่ได้: python -m venv .venv)
```

### Stack และเวอร์ชันที่ lock
| สิ่ง | ค่า |
|---|---|
| Python | 3.13.5 (venv ที่ `source\.venv`) |
| deepface | 0.0.104 |
| PyInstaller | 6.22.3 |
| GUI | customtkinter + PIL |
| TF/InsightFace | เข้ามาผ่าน deepface เท่านั้น (อย่า import โดยตรง) |
| ฐานข้อมูล production | `D:\TEMP\` (16,464 ไฟล์บน disc, 17,196 face rows) |
| Cache ของแอป | `D:\TEMP\deepface_cache\faces_VGG-Face.opencv.sqlite3` (schema 3) |
| Shared cache | `%LOCALAPPDATA%\Deeface\cache\contents_VGG-Face.opencv.sqlite3` |
| Legacy cache | `D:\TEMP\deepface_cache\rep_VGG-Face.opencv.npz` (import ครั้งเดียว) |

โมเดลที่ deepface 0.0.104 รองรับ: `VGG-Face`, `Facenet512`, `ArcFace`
(เลือกได้ใน GUI; default = VGG-Face + detector `opencv`)

### 1.1 Model home — ทำให้เครื่องใหม่/ไม่มีเน็ตใช้งานได้ (v1.3.0)

`face_search_core.configure_model_home()` ทำงานตอน import และก่อน import
deepface ครั้งแรก:

```python
home = <โฟลเดอร์ของ exe หรือ source>\models
if os.environ.get("DEEPFACE_HOME"):      # ผู้ใช้ตั้งเอง = เคารพค่านั้น
    return
if not os.path.isdir(home):
    if not frozen: return                # dev/source -> ใช้ ~/.deepface เดิม
    os.makedirs(home/".deepface"/"weights")   # exe: ดาวน์โหลดลงข้างโปรแกรม
os.environ["DEEPFACE_HOME"] = home
```

deepface เก็บ weights ที่ `$DEEPFACE_HOME/.deepface/weights/...` ดังนั้นการ
แนบโฟลเดอร์ `models\` ไปกับ exe ก็เพียงพอ — ไม่ต้องติดตั้ง/ต่อเน็ต

`model_assets(model, detector)` ตรวจไฟล์ที่ต้องใช้ (ขนาด ≥ 100 KB) และคืน
`{dir, required, missing, download_mb, ready}` ให้ GUI แสดงบรรทัด `MODEL`
และถามยืนยันก่อนดาวน์โหลด ไฟล์ที่ต้องมี:

| model | ไฟล์ |
|---|---|
| VGG-Face | `vgg_face_weights.h5` (553 MB) |
| Facenet512 | `facenet512_weights.h5` (91 MB) |
| ArcFace | `arcface_weights.h5` (131 MB) |
| detector opencv | `haarcascade_frontalface_default.xml`, `haarcascade_eye.xml` |

### 1.2 UI / ภาษา / ฟอนต์ / log (v1.3.0)

- `ui_theme.py` เก็บ palette QuestUI, ตัวสร้าง widget (การ์ด/ปุ่ม/ชิป/อินพุต),
  ฟอนต์ และข้อความ 2 ภาษา (`I18N["th"]`, `I18N["en"]`)
- ฟอนต์ Cinzel / Spectral / Noto Serif Thai ถูก pack เข้า exe ที่
  `assets/fonts` แล้วลงทะเบียนแบบ private ด้วย `AddFontResourceExW(..., 0x10)`
  (ไม่ติดตั้งลงเครื่อง) — ถ้าโหลดไม่ได้จะ fallback เป็น Georgia/Tahoma
- `App._set_lang()` สลับภาษาแล้วสร้าง UI ใหม่ (`_rebuild_ui`) โดยคงค่า
  ช่องกรอก/ผลลัพธ์/ความคืบหน้าไว้; เก็บภาษาที่เลือกใน `settings.json`
- core มี `set_ui_lang()` + `_p(th, en)` สำหรับข้อความเฟส/error ที่ส่งเข้า GUI
- `_setup_logging()` เขียน `Deeface.log` ข้าง exe (fallback `%LOCALAPPDATA%\Deeface`)
  หมุนไฟล์เมื่อเกิน 4 MB, ผูก `sys.stdout/sys.stderr` ที่เป็น `None` ของ
  windowed exe เข้าไฟล์ → เห็นข้อความดาวน์โหลด/stack trace ของ deepface
- `_tick()` เติม `⏱ วินาที` ในบรรทัดสถานะทุกวินาที เพื่อไม่ให้ดูเหมือนค้าง

## 2. Data flow (หนึ่งรอบค้นหา)

```
ผู้ใช้กด "🔍 ค้นหาใบหน้า"
        │
        ▼
App._start_search()            (main.py)
  · validate โฟลเดอร์ DB + รูปเป้าหมาย
  · self._stop.clear(); ปุ่ม: search/reset disable, stop enable
  · spawn thread → _search_worker(db, target)
        │
        ▼  (thread: ไม่ใช่ main thread ของ Tk)
_search_worker()
  · สร้าง core.FaceSearch(db_folder, model, detector,
                          progress_cb=cb, stop_event=self._stop)
  · fs.build()                    ← ฝังภาพทุกไฟล์ใน DB (มี cache)
  · ถ้า self._stop.is_set():
      → self.after(0, self._show_stopped); return  ← ไม่ match
  · matches = fs.match_target(target, top_n=3)
  · stats   = dict(fs.stats)
  · self.after(0, lambda: self._show_results(matches, stats))
  · finally: fs.close(); self.after(0, self._search_done)
        │
        ▼  (main thread, ผ่าน Tk .after(0, ...))
_show_results(): status "✅ รหัสพนักงานที่คาดเดา: <id> (ความใกล้เคียง X%)"
  + cache stats label + result cards 3 อันดับ + preview รูปของอันดับ 1
  + ปุ่ม "คัดลอกรหัส"
```

**กฎ threading สำคัญ:** ทุกอย่างที่ต้องแตะ widget ต้องส่งกลับ main thread
ด้วย `self.after(0, fn)` — worker thread เรียก widget โดยตรงไม่ได้
(error path ต้องจับ `msg = str(e)` **ก่อน** lambda เพราะ except ลบ `e` ทิ้ง)

## 3. face_search_core.py — โครงสร้างเชิงลึก

### 3.1 Lazy TensorFlow (v1.1.2 — ยังใช้อยู่)
```python
DeepFace = None                       # module-level singleton
_MODEL_LOCK = threading.Lock()        # serialize ทุก model call

def _deepface():                      # เรียกทุกครั้งที่ต้องใช้โมเดล
    global DeepFace
    if DeepFace is None:
        from deepface import DeepFace as _DF   # ← TF import ~5 วินาที
        DeepFace = _DF
    return DeepFace
```
- module import **ไม่ดึง TensorFlow** (window เปิดใน ~0.7s ไม่ใช่ 6s)
- `DeepFace.represent(...)` ทุกจุดเรียกผ่าน `_deepface()` ใต้ `_MODEL_LOCK`
- เทสต์ใช้การแทนที่ `core.DeepFace = FakeDF()` ได้โดยไม่ต้องมี TF

### 3.2 FaceSearch — state
```python
self.paths          # absolute path ต่อ 1 face row (row i ↔ paths[i])
self.embeddings     # np.ndarray (N, dim) float32 — L2-normalised แล้ว
self.build_seconds
self.stats          # dict: total, cached, new, no_face, failed, rows,
                    #       files, faces, migrated, shared_hits, seconds,
                    #       cache_file, stopped
self.cache_files    # จำนวนไฟล์ใน files table หลัง build
self.cache_faces    # ผลรวม n_faces ใน contents
self._warmed        # True หลัง warmup สำเร็จ

# per-build state
self._conn          # sqlite3 connection (None เมื่อ idle)
self._shared        # True เมื่อ ATTACH shared store สำเร็จ
self._shared_hits   # กี่ content ที่ดึงจาก shared
self._meta          # hash -> (n_faces, dim) — in-memory memo
self._rows          # [(path, hash)] ตาม scan order
self._dim           # embedding dimension ที่เจอ (VGG = 4096)
self._new_contents  # กี่ content ใหม่ที่เขียนรอบนี้
```
**row ≠ ไฟล์เสมอ!** ไฟล์เดียวที่มีหลายใบหน้า → หลาย rows
(16,464 ไฟล์ → 17,196 rows ใน D:\TEMP)

### 3.3 Cache — content-addressed SQLite (หัวใจของแอป)

cache file: `<db_folder>/deepface_cache/faces_<model>.<detector>[.enf].sqlite3`
(`.enf` ต่อท้ายเมื่อ `enforce_detection=True`; schema ปัจจุบัน = **3**)

```sql
meta     (key TEXT PRIMARY KEY, value TEXT)
files    (relkey TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, hash TEXT)
         -- relkey = relpath จาก DB root, ใช้ '/' เป็น separator
         -- index: ix_files_hash(hash)
contents (hash TEXT PRIMARY KEY, size INTEGER, n_faces INTEGER,
          dim INTEGER, vec BLOB)
         -- 1 row ต่อ 1 เนื้อไฟล์ที่ไม่ซ้ำ (เวกเตอร์ทุกใบหน้าเรียงต่อกัน)
_seen    (relkey TEXT PRIMARY KEY)   -- scratch ต่อ 1 build ไว้ลบ row ที่หายไป
```

**ทำไมเปลี่ยนจาก npz+crc32 (v1.1.x) มาเป็น SQLite+BLAKE2b-128:**
- v1.1.x ยังผูก cache กับ *relkey + size + mtime* แล้วใช้ crc32 เป็นตัวยืนยัน
  → ย้าย/เปลี่ยนชื่อโฟลเดอร์ย่อย, เปลี่ยนชื่อไฟล์, หรือ mtime ถูกแก้
  ทำให้ hash ใหม่ทั้งคลังทุกครั้ง (และบั๊กเดิมไม่เคยบันทึก mtime ใหม่กลับ)
- crc32 มีโอกาสชนกันแบบ birthday ~3% ที่ ~16,000 ไฟล์
- npz ต้องเขียน matrix ทั้งก้อน (`np.savez_compressed`) ทุก 25 rows
  → build แรกช้า, stop ไม่ทันที, ไฟล์เสียหายง่ายถ้า process ตายกลางทาง

v1.2.0 จึงเก็บ **hash ของเนื้อไฟล์ (BLAKE2b-128, 16 bytes = 32 hex)**
เป็น identity จริง และแยก embedding ไว้ใน `contents` ต่อ hash:

**ขั้นตอนใน `build()` ต่อ 1 ไฟล์:**
1. `stat` ได้ size + mtime
2. **stat fast path:** `files[relkey]` มีอยู่ + size + mtime + hash ตรง
   → `contents[hash]` มี → hit ทันที (ไม่เปิดไฟล์อ่าน)
3. ไม่ตรง → `_hash_file()` (อ่านไฟล์ทีละ 1 MiB)
4. `contents[hash]` มี (ในเครื่อง หรือใน shared store) → hit
   → บันทึก size/mtime ใหม่ลง `files` (รอบหน้าจะเป็น stat-only)
5. ไม่มีจริง ๆ → เรียกโมเดล 1 ครั้ง → normalize → เขียน `contents` + `files`

ผลลัพธ์: **ย้ายโฟลเดอร์ / เปลี่ยนชื่อไฟล์ / จัดโฟลเดอร์ใหม่ / คัดลอกข้ามเครื่อง
→ ไม่เรียกโมเดลเลย** (อ่าน hash อย่างเดียว ~85 MB/s)

**Shared content store (v1.2.0):**
- `%LOCALAPPDATA%\Deeface\cache\contents_<model>.<detector>.sqlite3`
- ATTACH เป็น `shared` แล้ว lookup `shared.contents` เมื่อ local ไม่มี
- content ที่หาเจอจะถูก `INSERT OR IGNORE` เข้า cache local ทันที
- content ใหม่ถูก publish ระหว่าง build (per batch)
- ปิดด้วย env `DEEFACE_SHARED_CACHE=0` (ทดสอบใช้ตัวนี้เพื่อ isolate)
- ถ้า attach/write พัง → `self._shared = False` แล้วทำงานต่อ (ไม่ fatal)

**รูปที่ไม่มีใบหน้า:** โมเดลคืน list ว่าง (ไม่ raise เพราะ default
`enforce_detection=False`) → บันทึก `contents(hash, n_faces=0, dim=0, vec=b"")`
→ รอบต่อไปไม่ต้องตรวจจับซ้ำ

**รูปที่โมเดล error:** **ไม่บันทึกอะไรลง cache เลย** (สำคัญ!)
- `failed += 1`, ข้ามไฟล์นั้น, รอบหน้าลองใหม่
- ถ้า `fails >= FAIL_LIMIT (5)` และ `embedded == 0` → flush งานที่สำเร็จแล้ว
  แล้ว raise `RuntimeError("วิเคราะห์ใบหน้าไม่สำเร็จติดกัน …")`
- เหตุผล: TensorFlow/หน่วยความจำ/ไดรฟ์ ผิดพลาดชั่วคราวไม่ควรทำให้รูปหมื่นรูป
  ถูกจำว่า "ไม่มีใบหน้า" ถาวร (ซึ่งจะทำ cache เสียและค้นไม่เจอตลอดไป)

**Legacy migration (v1.0–1.1 npz):**
- ถ้า `files` ว่าง และมี `rep_<model>.<detector>.npz` → import ครั้งเดียว
- hash ไฟล์จริงหนึ่งรอบ (ไม่เรียกโมเดล) แล้วเขียนเป็น `contents` + `files`
- ตรวจ size ตรงก่อน import; ไฟล์ที่หาย/ถูกแทนที่จะถูกข้าม (embed ใหม่)
- กันหยุดกลางทาง: `meta['npz_import'] = 'in-progress'` → ถ้า stop ให้ลบ
  `files`/`contents` ทิ้งแล้วเริ่มใหม่รอบหน้า; สำเร็จแล้วเก็บเป็นตัวเลข
- วัดจริง: 16,464 ไฟล์ / 17,196 rows ใช้ ~52 วินาที; รอบถัดไป 1.5 วินาที

**Schema mismatch:** `meta['schema']` ไม่ตรง → rename เป็น `<file>.v<old>.bak`
แล้วเริ่ม cache ใหม่ (ไม่ทำข้อมูลผู้ใช้หายเงียบ ๆ)

### 3.4 build() — รายละเอียด loop

```python
def build(self):
    try:
        return self._build()
    finally:
        self.close()          # ปลดล็อกไฟล์เสมอ แม้ raise (Windows)
```

- `list_db_files()` = walk โฟลเดอร์ DB (ข้าม `deepface_cache`), filter
  `.jpg .jpeg .png .bmp .webp .tif .tiff`, sorted
- ตรวจ `self._stop_event` **ทุกไฟล์** (early exit)
- progress emit: ทุก 10 ไฟล์ แต่ throttle ~0.12s เพื่อไม่ให้ Tk อืด
- **incremental write:** `flush_if_due()` ทุก 25 ไฟล์ หรือทุก 1.5 วินาที
  → `INSERT OR REPLACE` ลง `contents` + `files` ใน transaction เดียว
  (ไม่มีการเขียน matrix ทั้งก้อน; ข้อมูลที่ทำแล้วไม่หายเมื่อหยุด)
- จบแบบไม่ stopped → `DELETE FROM files WHERE relkey NOT IN _seen`
  (ลบไฟล์ที่ถูกลบออกจากโฟลเดอร์) — ถ้า stopped จะไม่ลบ
- `_assemble(conn)` → อ่าน `contents` ตาม `_rows` สร้าง matrix ในหน่วยความจำ
- stopped หรือไม่ → `close()` ผ่าน `finally` ไม่มี lock ค้าง
- ถ้ามี content ใหม่และไม่ stopped → `_sync_shared(conn)`

### 3.5 match_target()
- `_deepface().represent(target, ...)` ใต้ `_MODEL_LOCK` → ทุก face
- embedding ถูกเก็บ L2-normalised แล้ว → query normalize แล้ว
  `d = 1 - matrix @ q` = cosine distance
- `argsort` top-N ต่อ face, merge ด้วย `min` distance, dedupe path, rank
- `employee_id = basename` ไม่ติด extension
- `similarity = (1 - distance) * 100`
- ค่าอ้างอิงจริง: `616884.jpg` → top `10377` dist **0.4864**
  (รอง: S4073 0.5078, 08851 0.5158) — ใช้เป็น regression gate ทุกครั้ง

### 3.6 warmup()
- เรียก `_deepface()` (import TF + build model) + `represent()` ภาพแรก
  ของ DB (ถ้าไม่มีไฟล์ จะสร้าง PNG สีเทาชั่วคราวแล้วลบ — deepface 0.0.104
  รับ `img_path=` เท่านั้น ไม่รับ `img=`) → `_warmed = True`
- safe ต่อ daemon thread (`_MODEL_LOCK` serialize)
- error ใด ๆ ถูก log ไว้ (โมเดลยังโหลดอยู่; search จริงจะทำงานปกติ)

### 3.7 cache_summary() / clear_cache()
- `cache_summary(db, model, detector)` = read-only เร็ว ๆ สำหรับ GUI
  คืน `{ready, legacy, path, files, faces, size}` (เปิด sqlite timeout 5s)
- `clear_cache()` = close + `shutil.rmtree(cache_dir)`
  (ลบเฉพาะ `<db>/deepface_cache`; shared store ไม่ถูกลบ)

## 4. main.py — โครงสร้าง GUI

```
App(ctk.CTk)
├── _setup_logging()        Deeface.log + ผูก stdout/stderr
├── lang / f                ภาษา + Typography (Cinzel/Spectral/Noto Serif Thai)
├── _build_ui()
│   ├── header              โลโก้ ⚜ + ชื่อแอป + ปุ่ม ไทย/EN
│   ├── search card         db/target entries + เลือกไฟล์ + model/detector
│   │   ├── actions         btn_search / btn_stop / btn_reset
│   │   ├── progress        CTkProgressBar (ทอง)
│   │   ├── status_lbl      ข้อความเฟส + ⏱ วินาที
│   │   └── model_line / cache_line  StatusLine (ชิป MODEL/CACHE)
│   └── results             CTkScrollableFrame + result cards
├── _prewarm(); _refresh_model_info(); _refresh_cache_info(); ready status
└── _tick()                 เติมเวลาที่ใช้ทุก 1 วินาที ขณะ busy
```

### 4.1 Prewarm (v1.1.2)
`__init__` → `self._prewarm()` → spawn **daemon thread** สร้าง
`core.FaceSearch(db, model, detector).warmup()` — TF+model โหลดในพื้นหลัง

### 4.2 Stop button (v1.1.2, ปรับใน v1.2.0)
1. `_stop_requested()`: `self._stop.set()` + feedback ทันที
   (btn disable, status "⏹ กำลังหยุด...")
2. `build()` ตรวจ `stop_event` ทุกไฟล์ → break เร็ว
3. v1.2.0: ข้อมูลถูกเขียนลง SQLite ไปแล้วทีละ batch → stop แล้วไม่ต้อง
   เขียนไฟล์ใหญ่ท้ายรอบ (ตัด `fs.flush()` 500 MB ออก) และ `close()` อยู่ใน
   `finally` ของ `build()`
4. `_search_worker()`: หลัง `build()` ถ้า `_stop.is_set()` →
   `self.after(0, self._show_stopped)` แล้ว **return** (ไม่ match)
5. `_show_stopped()`: progress=1, "⏹ หยุดแล้ว — แคชที่เก็บได้ถูกบันทึกไว้แล้ว..."

### 4.3 Cache / model UI (v1.2.0, ปรับใน v1.3.0)
- `_refresh_cache_info()` เปิด thread เรียก `core.FaceSearch.cache_summary`
  แล้ว `after(0, _apply_cache_info)` — ไม่บล็อก UI
- แสดงผ่านชิป `CACHE`: พร้อมใช้ (เขียว) / แคชเก่า (ทอง) / ยังไม่มี (ทอง)
  หลังค้นหาแสดง cached/new/no_face/failed/faces/seconds
- ชิป `MODEL`: `core.model_assets()` → พร้อมใช้ (เขียว) หรือขาดไฟล์
  (ทอง + ขนาดที่ต้องโหลด + วิธีคัดลอกโฟลเดอร์ `models`)
- ปุ่ม **♻ รีเซ็ตแคช**: `messagebox.askyesno` → `clear_cache()` →
  refresh; disable ระหว่าง search

### 4.4 Settings
`settings.json` อยู่ **ข้าง exe** (via `base_dir()` = dirname ของ `sys.argv[0]`
เมื่อ frozen) เก็บ `db_folder, target, model, detector, lang`
อ่านด้วย `encoding="utf-8-sig"` (ทน BOM ที่ Notepad/PowerShell เติมให้ —
ถ้าใช้ `utf-8` ธรรมดา `json.load` จะ error แล้วหน้าจอเริ่มแบบว่างเปล่า)
เขียนด้วย `utf-8` (ไม่มี BOM)

### 4.5 ภาษา (v1.3.0)
`_set_lang(code)` → `core.set_ui_lang()` + `ui.Typography(code)` +
`_rebuild_ui()` (destroy/สร้าง widget ใหม่ แล้วใส่ค่าเดิมกลับ: ช่องกรอก,
โมเดล, detector, progress, สถานะ, ผลลัพธ์) — ไม่ต้องปิดโปรแกรม

## 5. Build / Deploy pipeline

```bash
cd /d/TPIPL/11-2026/Deeface/source
./.venv/Scripts/python -m PyInstaller Deeface.spec --clean --noconfirm
# ~5 นาที → dist\Deeface.exe (~512 MB)
```

- `Deeface.spec`: `collect_all("deepface","customtkinter","cv2","numpy",
  "insightface","gdown","tf_keras")`; `console=False`; `version="version_info.txt"`
- v1.3.0: `datas += [(SPECPATH/assets/fonts, "assets/fonts")]` (ฟอนต์ TH/EN)
- venv ต้องมี `numpy`, `Pillow`, `pyinstaller` ด้วย (deepface ไม่ได้ลงให้)
- **ต้อง kill process เดิมก่อน copy** — exe ที่รันอยู่ lock ไฟล์ตัวเอง:
```powershell
Get-Process Deeface | Stop-Process -Force
```
- Deploy = copy `dist\Deeface.exe` → `D:\TPIPL\11-2026\Deeface\Deeface.exe`
  **พร้อมโฟลเดอร์ `models\`** (และ `settings.json` ถ้าต้องการค่าตั้งต้น)
- Verify version:
```powershell
(Get-Item D:\TPIPL\11-2026\Deeface\Deeface.exe).VersionInfo.FileVersion
```
- Launch test: Popen + wait 30s + poll alive
- Model weights **ไม่ถูก pack เข้า exe** — แนบเป็นโฟลเดอร์ `models\`
  ข้าง exe (ดู §1.1); ถ้าไม่มีจะดาวน์โหลดเข้า `models\.deepface\weights`
  เอง (ต้องต่อเน็ต) หรือผู้ใช้คัดลอกโฟลเดอร์มาให้

### เวลาเปิด (วัดจริง)
| รูปแบบ | v1.1.1 | v1.1.2 | v1.2.0 |
|---|---|---|---|
| source (venv python) | ~6 s | 0.7 s | 0.7 s |
| exe (one-file, unpack ~512 MB) | ~14 s | ~11 s | ~11 s |
| TF warmup (background) | — | ~4 s | ~4 s |

ส่วนที่ลดไม่ได้ใน exe คือ PyInstaller one-file unpacking (~8-10s) —
จะลดเหลือ ~3s ต้อง switch spec เป็น **onedir**

## 6. เวอร์ชัน & การ bump
- `main.py`: `APP_VERSION = "1.3.0"` (แสดงใน title)
- `version_info.txt`: `filevers=(1, 3, 0, 0)`, `prodvers=(1, 3, 0, 0)`,
  `StringStruct('FileVersion', '1.3.0.0')`, `StringStruct('ProductVersion', '1.3.0.0')`
- `face_search_core.py`: `CACHE_SCHEMA = 3` — **เปลี่ยนโครงสร้าง cache
  ต้อง bump เลขนี้** (schema เก่าจะถูก backup เป็น `.bak` แล้วเริ่มใหม่)
- convention: MAJOR.MINOR.PATCH — bump ทุก feature/fix, rebuild exe
- README-TH.md: เพิ่ม section ใหม่ตาม version
  (v1.1.1 cache, v1.1.2 speed+stop, v1.2.0 content-addressed cache,
  v1.3.0 offline models + QuestUI/TH-EN)

## 7. Verification gates (pattern ที่ใช้ทุกครั้ง)
เขียน ad-hoc script `.py` ใน `%TEMP%` รันด้วย `C:\Python313\python.exe`
(มี numpy/PIL แต่ไม่มี TF → แทน `core.DeepFace` ด้วย fake):

1. **Lazy TF:** subprocess import `face_search_core` → `sys.modules`
   ต้องไม่มี `tensorflow`
2. **Cache warm:** fake `represent()` นับ call → build() ต้อง = 0 calls
3. **Move/rename:** เปลี่ยนชื่อโฟลเดอร์, เปลี่ยนชื่อไฟล์, ย้ายเข้า subfolder,
   เปลี่ยน mtime → model calls = 0, hash ≤ จำนวนไฟล์
4. **mtime persistence:** hash รอบแรกแล้ว รอบถัดไป hash = 0 (stat-only)
5. **Content change:** แทนเนื้อไฟล์ 1 ไฟล์ → model calls = 1
6. **Failure safety:** fake raise → `failed` นับ, ไม่มี row ใน cache,
   รอบถัดไปสำเร็จ; raise ติด 5 ไฟล์ → `RuntimeError`, cache ว่าง
7. **Migration:** npz จริง 16,464 ไฟล์ → rows 17,196, model calls = 0
8. **Match correctness:** `616884.jpg` → `10377` @ 0.4864 (±0.01)
9. **Stop:** `stop_event` กลางทาง → build return เร็ว, งานก่อนหน้าอยู่ใน cache
10. **GUI smoke:** `App().update()`, cache label/reset wiring, launch exe alive 30s

สคริปต์ที่ใช้ล่าสุด:
`%TEMP%\opencode\df_test_v12.py` (core), `df_test_fail.py` (failure paths),
`df_consistency.py` (237 MB→290 MB, top-5 ตรงกับ cache เก่า), `df_gui_search.py`

## 8. Pitfalls ที่เจอแล้ว (อย่าแก้ใหม่)
- **Windows file lock:** ต้อง `close()` connection ทุกครั้ง — v1.2.0 ใช้
  `try/finally` ใน `build()`; GUI ก็เรียก `fs.close()` ใน finally
- **อย่า persist exception เป็น n_faces=0** — environment error จะกลายเป็น
  cache เสียถาวร; ใช้ `FAIL_LIMIT` หยุดเมื่อล้มติดกัน
- **except var ถูกลบหลัง block:** `lambda: self._show_error(str(e))` จะ
  NameError → เก็บ `msg = str(e)` ก่อน
- **`INSERT OR REPLACE` ต้อง commit** — `_flush_batch` ใช้ `with conn`
- **shared ATTACH ใช้ transaction ร่วม** — row ที่ import จาก shared ยังไม่
  commit จนกว่า batch flush; อย่าปิด connection ก่อน flush
- MSYS shell strip `$` จาก inline PowerShell → ต้องเขียน `.ps1`
- Tk widget จาก worker thread → `self.after(0, fn)` ทุกครั้ง
- exe ที่กำลังรัน lock ไฟล์ตัวเอง → kill ก่อน copy deploy
- PyInstaller build ~5 นาที — รัน background แล้วรอ notify
- `collect_all` ใน PyInstaller 6.x คืน tuple 3 ค่า

## 9. Roadmap แนะนำ (ไอเดียพัฒนาต่อ)
- **onedir build** → exe window < 3s (แลกขนาดโฟลเดอร์)
- **enforce_detection toggle** ใน GUI (ตอนนี้ hardcode False)
- **top-N adjustable** (ตอนนี้ hardcode 3)
- **multi-face target** — match_target จัดการแล้ว แต่ UI แสดง preview อันดับ 1
- **log/export** ผลค้นหา (CSV/JSON)
- **batch scan** หลายรูปเป้าหมายในครั้งเดียว
- **GPU option** (TF GPU build) ถ้าเครื่องปลายทางมี GPU
- **i18n** — UI ไทยล้วน (string กระจายใน main.py, status text ใน core)
- **auto-update** — เปรียบเทียบ FileVersion กับ server
