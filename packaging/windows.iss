; Per-user installation: no administrator account required.
#ifndef AppVersion
  #error AppVersion must come from app_metadata.py through build_desktop.py
#endif
[Setup]
AppId={{D30FD858-281F-4E27-95AD-FA84A8E74A1B}
AppName=JumpTrack
AppVersion={#AppVersion}
AppPublisher=Emon
AppPublisherURL=https://github.com/emoninet2/lb-jumptrack-python
DefaultDirName={localappdata}\Programs\JumpTrack
DefaultGroupName=JumpTrack
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputPath}
OutputBaseFilename={#InstallerName}
SetupIconFile={#IconPath}
UninstallDisplayIcon={app}\JumpTrack.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "{#BundlePath}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Replace only the installer-owned runtime, never user data outside it.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\JumpTrack"; Filename: "{app}\JumpTrack.exe"
Name: "{autodesktop}\JumpTrack"; Filename: "{app}\JumpTrack.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\JumpTrack.exe"; Description: "Open JumpTrack"; Flags: nowait postinstall skipifsilent
