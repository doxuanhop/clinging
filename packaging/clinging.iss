; Clinging - trinh cai dat cho ban dong goi (PyInstaller onedir).
; Bien dich: ISCC.exe packaging\clinging.iss
; Cai dat per-user, KHONG can UAC: toan bo nam trong {localappdata}\Programs.
; FFmpeg/ffprobe di kem trong dist\Clinging\_internal\tools (nguon: tools\ffmpeg),
; nen ban cai chay duoc tren may khong co FFmpeg trong PATH.

#define MyAppName      "Clinging"
#define MyAppVersion   "1.0.5"
#define MyAppPublisher "Qeafivels Software"
#define MyAppExeName   "Clinging.exe"
#define BundleDir      "..\dist\Clinging"

[Setup]
; AppId giu nguyen de lan cai sau nang cap dung chu, khong tao ban second.
AppId={{8F0C4A6E-2C31-4E1B-9C1D-5A7B9E2D4C10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; FileVersion/Company/Copyright cua chinh setup.exe. Inno khong tu lay tu
; AppVersion cho VersionInfoVersion: neu bo trong thi Properties -> Details cua
; file tai ve in ra 0.0.0.0 va chu so huu trong. Khong anh huong gi toi cai dat.
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup
VersionInfoCompany={#MyAppPublisher}
VersionInfoCopyright=Copyright 2026 {#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
AllowUNCPath=no
OutputDir=..\build\installer
OutputBaseFilename=ClingingSetup-{#MyAppVersion}
SetupIconFile=..\assets\app-icon\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Ban dong goi kieu onedir: danh sach file trong _internal DOI THEO tung lan
; build, ma Inno chi ghi de nhung file no biet ten. Lan nang cap vua do de lai
; 160 MB faster-whisper nam chet trong thu muc cai dat (ctranslate2 59 MB luc
; 08:14, av.libs 63 MB luc 08:13, onnxruntime 38 MB tu 10-17 — trong khi exe
; moi cua cung bundle mang timestamp 09:47). Xoa sach _internal truoc khi giai
; nen moi lan cai la dung bundle cua lan build do, khong phai pha tron hai lan.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Nhấp đúp một file .clinq phải vào thẳng cửa dựng phim, không phải mở Home
; rồi mới tìm lại thẻ.
;
; VI SAO LA HKCU\Software\Classes CHU KHONG PHAI HKCR: da do tren may nay.
; Voi PrivilegesRequired=lowest, mot write HKCR cho khoa MOI (HKCR\.clinq chua
; tung ton tai) bi tu choi — "RegCreateKeyEx failed; code 5" — va Inno lam dieu
; te hon loi thong bao: no ROLLBACK toan bo bo cai dat, xoa ca shortcut Desktop
; lan Start Menu cua lan cai TRUOC do. HKCU\Software\Classes duoc ghep vao HKCR
; cho rieng user nay, ghi khong can UAC, va uninstall don sach.
Root: HKCU; Subkey: "Software\Classes\.clinq"; ValueType: string; ValueName: ""; ValueData: "Clinging.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Clinging.Project"; ValueType: string; ValueName: ""; ValueData: "Clinging Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Clinging.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\Clinging.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Chi don rac cua bundle, khong dong .clinqing (du lieu project cua nguoi dung).
Type: filesandordirs; Name: "{app}\_internal"
