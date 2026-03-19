[Setup]
AppName=EzPrint
AppVersion=1.0.0
AppPublisher=EzPrint
DefaultDirName={localappdata}\EzPrint
ArchitecturesInstallIn64BitMode=x64
DefaultGroupName=EzPrint
OutputDir=installer_output
OutputBaseFilename=EzPrint_Setup
SetupIconFile=assets\icons\ezprint.ico
UninstallDisplayIcon={app}\assets\icons\ezprint.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist_nuitka\main.dist\*"; DestDir: "{app}"; Flags: replacesameversion recursesubdirs

[Icons]
Name: "{group}\EzPrint"; Filename: "{app}\main.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\ezprint.ico"
Name: "{autodesktop}\EzPrint"; Filename: "{app}\main.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\ezprint.ico"; Tasks: desktopicon

