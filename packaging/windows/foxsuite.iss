#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
[Setup]
AppId={{139DE022-4F4F-449D-96F9-05255913AC87}
AppName=FoxSuite
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\FoxSuite
DefaultGroupName=FoxSuite
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir=..\..\dist\installer
OutputBaseFilename=FoxSuite-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\FoxSuite.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "..\..\dist\FoxSuite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FoxSuite"; Filename: "{app}\FoxSuite.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\FoxSuite.exe"; Description: "FoxSuite"; Flags: nowait postinstall skipifsilent

; Deliberately no [UninstallDelete] and no files installed into the user-data root.
; USB/virtual-COM drivers are never installed by this installer.
