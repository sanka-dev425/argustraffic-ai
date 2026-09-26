; ArgusTraffic AI - Inno Setup Script
; Generates a professional 1-click Windows Installer (.exe) with desktop shortcut

[Setup]
AppName=ArgusTraffic AI Enterprise
AppVersion=1.2.0
AppPublisher=ArgusTraffic AI Platform
DefaultDirName={autopf}\ArgusTraffic AI
DefaultGroupName=ArgusTraffic AI
OutputDir=..\dist\installer
OutputBaseFilename=ArgusTraffic-AI-v1.2-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ArgusTraffic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ArgusTraffic AI"; Filename: "{app}\ArgusTraffic.exe"
Name: "{group}\Uninstall ArgusTraffic AI"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArgusTraffic AI"; Filename: "{app}\ArgusTraffic.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ArgusTraffic.exe"; Description: "{cm:LaunchProgram,ArgusTraffic AI}"; Flags: nowait postinstall skipifsilent
