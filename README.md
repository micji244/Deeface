# Deeface

โปรแกรมค้นหา **รหัสพนักงานจากรูปใบหน้า** สำหรับ Windows ใช้งานแบบออฟไลน์ ทำงานบน CPU ได้ดี (ทดสอบกับรูปพนักงานประมาณ 17,000 รูป ค้นหาครั้งละราว 2 วินาที)

> **English summary** — Offline Windows desktop app that finds an employee ID from a face photo by
> comparing it with a folder of employee photos whose file names are the IDs (`10234.jpg` → `10234`).
> Runs on ONNX Runtime (no TensorFlow, no GPU needed). Recommended setup: **ArcFace**
> recognition + **YuNet** detector. Embeddings are cached in SQLite so only new photos are analysed.
> Thai/English UI, light/dark theme. Build a portable exe or an installer with `source\build.ps1`.

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue) ![python](https://img.shields.io/badge/python-3.13-blue) ![runtime](https://img.shields.io/badge/runtime-ONNX-blue)

---

## สารบัญ
1. [หลักการทำงาน](#หลักการทำงาน)
2. [ใช้งานโปรแกรม (ผู้ใช้ทั่วไป)](#ใช้งานโปรแกรม-ผู้ใช้ทั่วไป)
3. [รันจากซอร์สโค้ด (นักพัฒนา)](#รันจากซอร์สโค้ด-นักพัฒนา)
4. [ดาวน์โหลดไฟล์โมเดล](#ดาวน์โหลดไฟล์โมเดล)
5. [บิลด์เป็น exe และตัวติดตั้ง](#บิลด์เป็น-exe-และตัวติดตั้ง)
6. [โมเดลที่เลือกได้](#โมเดลที่เลือกได้)
7. [แคช (Cache)](#แคช-cache)
8. [โครงสร้างโปรเจกต์](#โครงสร้างโปรเจกต์)
9. [แก้ปัญหาที่พบบ่อย](#แก้ปัญหาที่พบบ่อย)

---

## หลักการทำงาน

```
โฟลเดอร์รูปพนักงาน            รูปที่ต้องการค้นหา
(10234.jpg, 10235.jpg, …)         (รูปถ่าย/รูปหมู่)
        │                               │
   หาตำแหน่งหน้า (YuNet)           หาตำแหน่งหน้า (YuNet, ความละเอียดเต็ม)
        │                               │
   แปลงหน้าเป็นเวกเตอร์ (ArcFace)    แปลงหน้าเป็นเวกเตอร์
        │                               │
   เก็บในแคช SQLite ─────────► เทียบความเหมือน (cosine) ──► 5 อันดับแรก + %
```

- **ชื่อไฟล์รูปคือรหัสพนักงาน** เช่น `10234.jpg` → รหัส `10234` (โฟลเดอร์ย่อยก็ได้)
- รองรับ `.jpg .jpeg .png .bmp .webp .tif .tiff` และชื่อไฟล์/โฟลเดอร์ภาษาไทย
- ครั้งแรกต้องวิเคราะห์รูปทั้งหมด หลังจากนั้นวิเคราะห์เฉพาะรูปใหม่หรือรูปที่ถูกแก้ไข

---

## ใช้งานโปรแกรม (ผู้ใช้ทั่วไป)

มีสองแบบ (บิลด์ได้จาก [ขั้นตอนนี้](#บิลด์เป็น-exe-และตัวติดตั้ง)) ความเร็วในการค้นหาเท่ากัน

| | Portable | ตัวติดตั้ง (Setup) |
|---|---|---|
| ไฟล์ | `Deeface.exe` + โฟลเดอร์ `models\` | `Deeface-x.y.z-Setup.exe` |
| ติดตั้ง | ไม่ต้อง คัดลอกโฟลเดอร์แล้วดับเบิลคลิก | Next → Install ลง `C:\Program Files\Deeface` |
| เปิดโปรแกรม | ~4–5 วินาที (ต้องแตกไฟล์ทุกครั้ง) | เร็วกว่า |
| เก็บค่าที่ตั้งไว้ / log | ข้าง exe | `%APPDATA%\Deeface` / `%LOCALAPPDATA%\Deeface` |
| เหมาะกับ | พกไปใช้ เครื่องที่ไม่มีสิทธิ์ admin | เครื่องที่ใช้ประจำ |

> ⚠️ แบบ portable ต้องวางโฟลเดอร์ `models\` ไว้ข้าง `Deeface.exe` เสมอ ถ้าไม่มี โปรแกรมจะพยายามดาวน์โหลดโมเดลจากอินเทอร์เน็ต

### ขั้นตอนใช้งาน
1. **① โฟลเดอร์รูปพนักงาน** กด "เลือกโฟลเดอร์" แล้วเลือกโฟลเดอร์ที่เก็บรูปพนักงาน
2. **② รูปที่ต้องการค้นหา** คลิกที่กรอบรูปหรือกด "เลือกรูป"
3. กด **🔍 ค้นหา** (ครั้งแรกกับโฟลเดอร์ใหม่จะใช้เวลานาน ดูหัวข้อ [แคช](#แคช-cache))
4. ผลลัพธ์แสดง **5 คนที่หน้าคล้ายที่สุด** พร้อม % ความเหมือนและป้ายระดับ
   - **ชี้เมาส์ที่รูป** เพื่อดูภาพขยายเทียบกับหน้าในรูปที่ค้นหา (ถ้าเป็นรูปหมู่ จะครอปเฉพาะคนที่ตรงกัน)
   - กด **คัดลอกรหัส** เพื่อนำรหัสไปใช้ต่อ
5. มุมขวาบนสลับ **สว่าง/มืด** และ **ไทย/EN** ได้

> % เป็นค่าความคล้ายที่โมเดลคำนวณ ไม่ใช่ความน่าจะเป็น แต่ละโมเดลให้ช่วงตัวเลขต่างกัน ให้ดูจากระยะห่างระหว่างอันดับ 1 กับอันดับถัดไปประกอบ **ควรตรวจสอบด้วยตาอีกครั้งก่อนนำผลไปใช้**

---

## รันจากซอร์สโค้ด (นักพัฒนา)

ต้องมี **Windows 10/11 (64-bit)** และ **Python 3.13**

```powershell
git clone https://github.com/micji244/Deeface.git
```

```powershell
cd Deeface\source
```

```powershell
python -m pip install -r requirements.txt
```

วางไฟล์โมเดลตาม [ดาวน์โหลดไฟล์โมเดล](#ดาวน์โหลดไฟล์โมเดล) แล้วเลือกวิธีใดวิธีหนึ่งให้โปรแกรมหาโมเดลเจอ
- วางไว้ที่ `source\models\.deepface\weights\` (โปรแกรมหาโฟลเดอร์ `models` ข้างไฟล์ `.py` เอง) หรือ
- ตั้งตัวแปร `DEEPFACE_HOME` ให้ชี้โฟลเดอร์ที่มี `.deepface\weights\` ข้างใน

```powershell
$env:DEEPFACE_HOME = "D:\path\to\models_onnx"
```

```powershell
python main.py
```

### ทดสอบแบบไม่เปิดหน้าจอ (selftest)
ใช้ตรวจว่าโปรแกรมหรือ exe ที่บิลด์แล้วทำงานได้ ผลลัพธ์จะเขียนลง `Deeface.log` (exit code 0 = พบผลลัพธ์)

```powershell
python main.py --selftest "D:\photos" "C:\target.jpg" ArcFace yunet
```

กับไฟล์ exe ใช้รูปแบบเดียวกัน: `Deeface.exe --selftest <โฟลเดอร์รูป> <รูปที่ค้นหา> [โมเดล] [ตัวหาหน้า]`

---

## ดาวน์โหลดไฟล์โมเดล

ไฟล์โมเดล **ไม่ได้อยู่ใน repo นี้** (ไฟล์ใหญ่ และบางตัวห้ามแจกต่อ) ให้ดาวน์โหลดมาวางตามโครงสร้างนี้

```
models_onnx\
└── .deepface\
    └── weights\
        ├── face_detection_yunet_2023mar.onnx      (0.2 MB)
        ├── arcface_weights.onnx                   (130 MB)
        ├── facenet512_weights.onnx                ( 90 MB)
        ├── vgg_face_weights.onnx                  (512 MB)
        ├── haarcascade_frontalface_default.xml    (0.9 MB)
        └── haarcascade_eye.xml                    (0.3 MB)
```

| ไฟล์ | แหล่งดาวน์โหลด |
|---|---|
| `face_detection_yunet_2023mar.onnx` | [opencv_zoo / face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| `arcface_weights.onnx`, `facenet512_weights.onnx`, `vgg_face_weights.onnx` | [serengil/deepface_models releases v1.0](https://github.com/serengil/deepface_models/releases/tag/v1.0) |
| `haarcascade_*.xml` | [opencv/data/haarcascades](https://github.com/opencv/opencv/tree/4.x/data/haarcascades) |

ถ้าจะใช้ ArcFace + YuNet ต้องมีอย่างน้อย `arcface_weights.onnx` กับ `face_detection_yunet_2023mar.onnx`

---

## บิลด์เป็น exe และตัวติดตั้ง

ต้องมี
- Python 3.13 + `requirements.txt` (มี PyInstaller อยู่ในนั้นแล้ว)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) ติดตั้งได้ด้วยคำสั่งนี้

```powershell
winget install JRSoftware.InnoSetup
```

- ไฟล์โมเดลครบ อยู่ที่ `..\models_onnx\.deepface\weights\` (โฟลเดอร์ระดับเดียวกับ `source\`)

แล้วรัน

```powershell
powershell -ExecutionPolicy Bypass -File source\build.ps1
```

ผลลัพธ์อยู่ใน `release\`
- `Deeface-x.y.z-portable\` → `Deeface.exe` (~90 MB) + `models\`
- `Deeface-x.y.z-Setup.exe` → ตัวติดตั้ง (รวมโมเดลทุกตัว)

**เปลี่ยนเลขเวอร์ชัน** ต้องแก้ 4 ที่: `APP_VERSION` ใน `main.py`, `version_info.txt`, `#define AppVersion` ใน `installer.iss` และ `$Version` ใน `build.ps1`

> `Deeface.spec` ตัด TensorFlow, PyTorch, pandas, scipy ฯลฯ ออกจากไฟล์ exe แม้เครื่องที่บิลด์จะติดตั้งไว้ก็ตาม

---

## โมเดลที่เลือกได้

เลือกได้จากเมนู "โมเดลจดจำใบหน้า" และ "ตัวหาตำแหน่งหน้า" ในโปรแกรม

ผลทดสอบกับรูปจริง (รูปพนักงาน 300 รูปที่ทำให้คุณภาพแย่ลงแบบรูปมือถือ ค้นหาในกลุ่ม 3,000 คน, CPU):

| ชุด | หาถูกอันดับ 1 | เวลาต่อรูป | หมายเหตุ |
|---|---|---|---|
| **ArcFace + YuNet** | **88.3%** | 51 ms | แนะนำ |
| ArcFace + OpenCV | 86.7% | 74 ms | ชุดเดิมของ v1.x |
| Facenet512 / VGG-Face | — | — | มีให้เลือกเพื่อใช้กับแคชเดิม |

แต่ละชุด (โมเดล + ตัวหาหน้า) มีแคชแยกกัน เปลี่ยนไปชุดที่ยังไม่มีแคช โปรแกรมจะต้องวิเคราะห์รูปทั้งหมดใหม่ครั้งแรก

---

## แคช (Cache)

- เก็บไว้ในโฟลเดอร์รูปเอง: `<โฟลเดอร์รูป>\deepface_cache\faces_<โมเดล>.<ตัวหาหน้า>.sqlite3`
- จำรูปจาก **เนื้อหาไฟล์** (hash) ไม่ใช่จากชื่อหรือตำแหน่ง ย้ายโฟลเดอร์ เปลี่ยนชื่อไฟล์ หรือคัดลอกไปเครื่องอื่น ก็ไม่ต้องวิเคราะห์ใหม่
- รูปที่ไม่มีหน้า (เช่น รูปพื้นหลัง) ถูกจดไว้ว่า "ไม่มีหน้า" และจะไม่แสดงในผลลัพธ์
- มีคลังกลางที่ `%LOCALAPPDATA%\Deeface\cache` ให้โฟลเดอร์รูปอื่นในเครื่องเดียวกันใช้ผลวิเคราะห์ร่วมกันได้ (ปิดได้ด้วย `DEEFACE_SHARED_CACHE=0`)
- กด **ล้างแคช** ในโปรแกรม ถ้าต้องการให้วิเคราะห์ใหม่ทั้งหมด

**ย้ายไปใช้อีกเครื่อง:** คัดลอกโฟลเดอร์รูปไปพร้อม `deepface_cache\` เครื่องปลายทางจะใช้ได้ทันที ไม่ต้องรอวิเคราะห์ใหม่ (ประมาณ 25–40 นาทีต่อ 17,000 รูป)

---

## โครงสร้างโปรเจกต์

```
Deeface\
├── README.md               ← ไฟล์นี้
├── README-TH.md            ← บันทึกการเปลี่ยนแปลงแต่ละเวอร์ชัน
├── ARCHITECTURE-TH.md      ← รายละเอียดสถาปัตยกรรม (บางส่วนเป็นของ v1.3)
└── source\
    ├── main.py             ← หน้าจอ (customtkinter), ค่าที่ตั้งไว้, log, --selftest
    ├── face_search_core.py ← หาหน้า, แปลงเป็นเวกเตอร์, แคช SQLite, เทียบความเหมือน
    ├── ui_theme.py         ← สี/ธีมสว่าง-มืด, ฟอนต์, ข้อความไทย-อังกฤษ
    ├── Deeface.spec        ← ตั้งค่า PyInstaller (onefile / onedir)
    ├── build.ps1           ← บิลด์ portable + ตัวติดตั้ง
    ├── installer.iss       ← สคริปต์ Inno Setup
    ├── version_info.txt    ← ข้อมูลเวอร์ชันของไฟล์ exe
    ├── requirements.txt
    └── deeface.ico
```

แก้ข้อความบนหน้าจอได้ที่ `I18N` ใน `ui_theme.py` และแก้สีได้ที่ส่วน palette ด้านบนของไฟล์เดียวกัน (ทุกสีเป็นคู่ `(สว่าง, มืด)`)

---

## แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| แถบ "โมเดล" เป็นสีแดง / ขึ้นว่าต้องดาวน์โหลด | ไม่มีโฟลเดอร์ `models\` ข้างโปรแกรม ให้คัดลอกโฟลเดอร์ `models` มาวาง |
| "ไม่พบใบหน้าในรูปที่ค้นหา" | ใช้รูปที่เห็นหน้าชัด หันหน้าตรง ไม่มืดเกินไป |
| ค้นหาครั้งแรกนานมาก | ปกติ ระบบต้องวิเคราะห์ทุกรูปครั้งแรก กด "หยุด" ได้ ผลที่ทำไปแล้วถูกบันทึกไว้ |
| ผลลัพธ์ดูไม่ถูกต้อง | ใช้ตัวหาหน้า YuNet และใช้รูปที่หน้าชัด ถ้ารูปในฐานข้อมูลมีปัญหา ให้ลองกด "ล้างแคช" |
| โปรแกรมปิดเองหรือค้าง | ดูไฟล์ `Deeface.log` (ข้าง exe หรือที่ `%LOCALAPPDATA%\Deeface\`) |
