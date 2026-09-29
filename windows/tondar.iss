; Inno Setup script: builds Tondar-Setup-<version>.exe from dist\Tondar
; Usage: ISCC.exe /DAppVersion=1.3.0 windows\tondar.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B2C1E-8A4D-4F7B-9C2E-5D1A7B3E9F40}
AppName=Tondar Download Manager
AppVersion={#AppVersion}
AppPublisher=Tondar
DefaultDirName={localappdata}\Programs\Tondar
DefaultGroupName=Tondar
DisableProgramGroupPage=yes
; Per-user install: no admin rights needed, and yt-dlp can update itself.
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Tondar-Setup-{#AppVersion}
SetupIconFile=..\data\tondar.ico
UninstallDisplayIcon={app}\Tondar.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start Tondar when I log in (needed for the scheduler and browser integration)"; GroupDescription: "Options:"

[Files]
Source: "..\dist\Tondar\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Tondar Download Manager"; Filename: "{app}\Tondar.exe"
Name: "{userdesktop}\Tondar"; Filename: "{app}\Tondar.exe"; Tasks: desktopicon

[Registry]
; Let the browser extension find the native messaging bridge
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.tondar.host"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host-chrome.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Chromium\NativeMessagingHosts\com.tondar.host"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host-chrome.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.tondar.host"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host-chrome.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\com.tondar.host"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host-firefox.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Tondar"; ValueData: """{app}\Tondar.exe"" --background"; Tasks: autostart

[Run]
Filename: "{app}\Tondar.exe"; Description: "Launch Tondar"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Tondar.exe /F"; Flags: runhidden; RunOnceId: "KillTondar"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Tondar');
end;
