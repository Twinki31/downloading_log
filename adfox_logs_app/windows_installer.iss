#ifndef MyAppVersion
  #error MyAppVersion must be passed to ISCC
#endif

#define MyAppName "AdFox Logs"
#define MyAppExeName "AdFox Logs.exe"

[Setup]
AppId={{F80EADAB-7D65-4D35-A1BD-55E509034AF7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Twinki31
AppPublisherURL=https://github.com/Twinki31/downloading_log
AppSupportURL=https://github.com/Twinki31/downloading_log/issues
DefaultDirName={localappdata}\Programs\AdFox Logs
DefaultGroupName=AdFox Logs
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=AdFox-Logs-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
