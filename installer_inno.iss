; =====================================================================
; ArgusTraffic AI - Enterprise Inno Setup Compiler Script
; Generates enterprise Windows installer (ArgusTraffic_Setup.exe)
; =====================================================================

[Setup]
AppId={{8B1A2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}
AppName=ArgusTraffic AI
AppVersion=2.0.0
AppPublisher=ArgusTraffic Autonomous Systems
AppPublisherURL=https://github.com/argustraffic
AppSupportURL=https://github.com/argustraffic
AppUpdatesURL=https://github.com/argustraffic
DefaultDirName={autopf}\ArgusTraffic AI
DefaultGroupName=ArgusTraffic AI
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=ArgusTraffic_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
UninstallDisplayIcon={app}\ArgusTraffic.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\ArgusTraffic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ArgusTraffic AI"; Filename: "{app}\ArgusTraffic.exe"
Name: "{group}\{cm:UninstallProgram,ArgusTraffic AI}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArgusTraffic AI"; Filename: "{app}\ArgusTraffic.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ArgusTraffic.exe"; Description: "{cm:LaunchProgram,ArgusTraffic AI}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if (Version.Major < 10) then
  begin
    MsgBox('ArgusTraffic AI Enterprise requires Windows 10 (64-bit) or Windows 11 with DirectX 11 support.' + #13#10 +
           'Please upgrade your operating system to proceed.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;
