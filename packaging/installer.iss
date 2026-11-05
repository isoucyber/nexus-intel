; Instalador Windows (Inno Setup 6). O CI passa /DAppVersion=x.y.z.
; O desinstalador NÃO apaga a pasta de dados do usuário (%APPDATA%\NexusIntel).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E1C2F0A-8B9D-4C6B-9D3E-4F2A7B1C9E51}
AppName=NEXUS INTEL
AppVersion={#AppVersion}
AppPublisher=Arthur Bomfim
AppPublisherURL=https://github.com/isoucyber/nexus-intel
DefaultDirName={autopf}\NEXUS INTEL
DefaultGroupName=NEXUS INTEL
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=NexusIntel-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\NexusIntel.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\NexusIntel\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\NEXUS INTEL"; Filename: "{app}\NexusIntel.exe"
Name: "{autodesktop}\NEXUS INTEL"; Filename: "{app}\NexusIntel.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NexusIntel.exe"; Description: "Abrir o NEXUS INTEL"; Flags: nowait postinstall skipifsilent
