; Installer di SentinelAI (Inno Setup 6). Per l'utente corrente: non chiede i permessi di amministratore.
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppId={{6C1E7A5E-3B7D-4D3F-9E2A-5A1F0C9E7B21}
AppName=SentinelAI Vision Guard
AppVersion={#Version}
AppPublisher=Roberto
DefaultDirName={localappdata}\Programs\SentinelAI
DefaultGroupName=SentinelAI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SentinelAI-Setup-{#Version}
SetupIconFile=sentinel.ico
UninstallDisplayIcon={app}\SentinelAI.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"
Name: "autostart"; Description: "Avvia SentinelAI insieme a Windows (solo l'icona vicino all'orologio)"; GroupDescription: "Avvio:"; Flags: unchecked

[Files]
Source: "..\dist\SentinelAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SentinelAI"; Filename: "{app}\SentinelAI.exe"
Name: "{autodesktop}\SentinelAI"; Filename: "{app}\SentinelAI.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SentinelAI"; ValueData: """{app}\SentinelAI.exe"" --minimizzato"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\SentinelAI.exe"; Description: "Apri SentinelAI"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM SentinelAI.exe"; Flags: runhidden; RunOnceId: "ChiudiSentinel"
