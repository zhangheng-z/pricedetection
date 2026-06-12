#define AppName "PriceDetection"
#define AppVersion "1.0.0"
#define SourceDir "E:\java learning\AgentProject\priceDetection\dist\PriceDetection"

[Setup]
AppId={{A1F4A8D4-7DB0-41C2-AE96-4427240B9A66}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
OutputDir=E:\java learning\AgentProject\priceDetection\packaging\installer\output
OutputBaseFilename=PriceDetectionSetup
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=no
UninstallDisplayIcon={app}\PriceDetection.exe

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\PriceDetection.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\PriceDetection.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: checkedonce

[Run]
Filename: "{app}\PriceDetection.exe"; WorkingDir: "{app}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
