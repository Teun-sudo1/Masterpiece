; Inno Setup script for Masterpiece-Setup-<version>.exe
; Built by:  python packaging\build.py --setup   (after the PyInstaller step)
;
; Installs for the current user only (no admin rights, no UAC prompt) into
; %LOCALAPPDATA%\Programs\Masterpiece. Uninstalling stops the rotation, puts your
; previous wallpaper back and removes the shortcuts; your paintings
; (Pictures\Masterpiece) and settings are kept.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define Root ".."

[Setup]
AppId={{8E4C2B7A-5D3F-4A91-B6E2-1F7C9A0D3E54}
AppName=Masterpiece
AppVersion={#AppVersion}
AppVerName=Masterpiece {#AppVersion}
AppPublisher=Teun Broekhuizen
AppComments=Public-domain paintings as your Windows wallpaper
DefaultDirName={localappdata}\Programs\Masterpiece
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#Root}\dist
OutputBaseFilename=Masterpiece-Setup-{#AppVersion}
SetupIconFile={#Root}\build\masterpiece.ico
UninstallDisplayIcon={app}\Masterpiece.exe
UninstallDisplayName=Masterpiece
LicenseFile={#Root}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Masterpiece
VersionInfoDescription=Masterpiece setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Masterpiece with Windows (tray icon only)"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; an update replaces the bundled libraries completely
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\build\app\Masterpiece\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Same names the app itself uses, so the tray's "Start with Windows" and
; "Masterpiece.exe install" manage these very shortcuts.
Name: "{userprograms}\Masterpiece"; Filename: "{app}\Masterpiece.exe"; Comment: "Public-domain paintings as your Windows wallpaper"
Name: "{userdesktop}\Masterpiece"; Filename: "{app}\Masterpiece.exe"; Comment: "Public-domain paintings as your Windows wallpaper"; Tasks: desktopicon
Name: "{userstartup}\Masterpiece"; Filename: "{app}\Masterpiece.exe"; Parameters: "--background"; Comment: "Masterpiece tray icon"; Tasks: startup

[Run]
; after an update or a move: an existing rotation now runs this copy
Filename: "{app}\Masterpiece.exe"; Parameters: "relink"; Flags: runhidden waituntilterminated
Filename: "{app}\Masterpiece.exe"; Description: "Open Masterpiece now"; Flags: nowait postinstall skipifsilent
; an update from inside Masterpiece runs this setup silently: start the new version again
Filename: "{app}\Masterpiece.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{app}\Masterpiece.exe"; Parameters: "cleanup"; Flags: runhidden waituntilterminated; RunOnceId: "MasterpieceCleanup"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
procedure StopMasterpiece();
var
  Code: Integer;
begin
  { the tray app keeps its files open; quit it before replacing or removing them }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Masterpiece.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopMasterpiece();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopMasterpiece();
  Result := True;
end;
