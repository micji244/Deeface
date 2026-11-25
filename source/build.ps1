# Deeface build script (v1.6)
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Produces, in ..\release:
#   Deeface-1.6.0-portable\  Deeface.exe + models\   (copy anywhere, run)
#   Deeface-1.6.0-Setup.exe                         (Next > Install > Finish)
#
# Needs: Python 3.13 with requirements.txt, Inno Setup 6, and the ONNX model
# files in ..\models_onnx\.deepface\weights (see README-TH.md).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Version  = "1.6.0"
$Root     = Split-Path $PSScriptRoot -Parent
$Weights  = Join-Path $Root "models_onnx\.deepface\weights"
$Release  = Join-Path $Root "release"
$Portable = Join-Path $Release "Deeface-$Version-portable"

foreach ($f in "arcface_weights.onnx", "facenet512_weights.onnx", "vgg_face_weights.onnx",
               "buffalo_l\webface_r50.onnx", "face_detection_yunet_2023mar.onnx",
               "haarcascade_frontalface_default.xml", "haarcascade_eye.xml") {
    if (-not (Test-Path (Join-Path $Weights $f))) { throw "missing model file: $Weights\$f" }
}

Write-Host "== 1/3 portable one-file exe"
$env:DEEFACE_ONEDIR = ""
python -m PyInstaller --noconfirm --clean --workpath build\onefile --distpath dist Deeface.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onefile) failed" }

Write-Host "== 2/3 folder build for the installer"
$env:DEEFACE_ONEDIR = "1"
python -m PyInstaller --noconfirm --clean --workpath build\onedir --distpath dist_installer Deeface.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onedir) failed" }
$env:DEEFACE_ONEDIR = ""
# never ship files a test run left behind (logs, settings, downloaded models)
foreach ($junk in "models", "Deeface.log", "Deeface.log.old", "settings.json") {
    $p = Join-Path "dist_installer\Deeface" $junk
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Write-Host "== packaging portable folder"
New-Item -ItemType Directory -Force (Join-Path $Portable "models\.deepface\weights") | Out-Null
Copy-Item dist\Deeface.exe $Portable -Force
Copy-Item (Join-Path $Weights "*") (Join-Path $Portable "models\.deepface\weights") -Recurse -Force

Write-Host "== 3/3 installer"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

Write-Host "Done -> $Release"
