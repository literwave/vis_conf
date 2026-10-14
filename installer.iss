#define MyAppName "星图 游戏配置导表工具"
#define MyAppExeName "star_map.exe"

[Setup]
AppId={{AB1A78DA-ABBA-4D2C-AF2B-8C76723CB966}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=literwave
DefaultDirName={localappdata}\Programs\GameConfigAssistant
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=StarMap-Setup-{#MyAppVersion}
SetupIconFile=assets\assistant-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "dist\package\star_map\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "test\*"; DestDir: "{app}\examples\test"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\assistant-icon.png"; DestDir: "{app}\examples\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: postinstall skipifsilent
