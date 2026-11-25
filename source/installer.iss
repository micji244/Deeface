; Inno Setup script for Deeface (installer edition).
; Build with build.ps1, or:  ISCC.exe installer.iss
;
; Installs the folder build (dist_installer\Deeface) + the ONNX model files
; into C:\Program Files\Deeface (64-bit app -> "Program Files", not "(x86)").
; Settings are then kept per user in %APPDATA%\Deeface, logs in
; %LOCALAPPDATA%\Deeface; the face cache stays inside each photo folder.

#define AppName "Deeface"
#define AppVersion "1.6.0"
#define AppExe "Deeface.exe"
#define BuildDir "dist_installer\Deeface"
#define ModelsDir "..\models_onnx\.deepface\weights"

[Setup]
AppId={{6F2B8C1E-4D5A-4E7B-9C3D-DEEFACE00001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Deeface
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=deeface.ico
OutputDir=..\release
OutputBaseFilename=Deeface-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; admin install into Program Files by default; the first page lets a user
; without admin rights install just for themselves instead
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ModelsDir}\arcface_weights.onnx"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion
Source: "{#ModelsDir}\facenet512_weights.onnx"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion
Source: "{#ModelsDir}\vgg_face_weights.onnx"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion
Source: "{#ModelsDir}\buffalo_l\webface_r50.onnx"; DestDir: "{app}\models\.deepface\weights\buffalo_l"; Flags: ignoreversion
Source: "{#ModelsDir}\face_detection_yunet_2023mar.onnx"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion
Source: "{#ModelsDir}\haarcascade_frontalface_default.xml"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion
Source: "{#ModelsDir}\haarcascade_eye.xml"; DestDir: "{app}\models\.deepface\weights"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; files the app may create beside itself when the user has write access
Type: files; Name: "{app}\Deeface.log"
Type: files; Name: "{app}\Deeface.log.old"
Type: files; Name: "{app}\settings.json"
