; Inno Setup script for the Kosmos PDF Windows installer. Built by the workflow in
; .github/workflows/windows.yml after PyInstaller has filled dist\KosmosPDF:
;
;     ISCC /DAppVersion=0.3.1 packaging\windows\kosmospdf.iss
;
; Installs for the current user by default (no administrator password), with the
; option to install for everyone. Registers Kosmos PDF as an "Open with" choice and in
; Default Apps for PDFs and images, without making it the default: Windows leaves that
; choice to the user.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Kosmos PDF"
#define AppExe "KosmosPDF.exe"
#define ProgId "KosmosPDF.Document"
; Its name until 0.3.7. The AppId above stays the same, so this installer upgrades a Kosmic
; PDF installation in place; it then tidies away what was installed under the old name.
#define OldName "Kosmic PDF"
#define OldProgId "KosmicPDF.Document"

[Setup]
AppId={{7C2E8B1A-4B7D-4F0E-9A63-2D5C1F8E6B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kosmos
AppPublisherURL=https://kosmos.law/
AppSupportURL=https://kosmos.law/pdf/
AppUpdatesURL=https://kosmos.law/pdf/
DefaultDirName={autopf}\Kosmos PDF
; Not the "Kosmic PDF" folder an earlier version was installed in (removed below).
UsePreviousAppDir=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=KosmosPDF-Setup-{#AppVersion}
SetupIconFile=..\..\kosmospdf\icons\app\kosmospdf.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; The terms of use (no warranty): the installer goes on only once they are accepted.
LicenseFile=..\..\kosmospdf\terms.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\KosmosPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD-PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\kosmospdf\terms.txt"; DestDir: "{app}"; DestName: "TERMS.txt"; Flags: ignoreversion

[InstallDelete]
; What Kosmic PDF installed under its old name: its folder and shortcuts.
Type: filesandordirs; Name: "{autopf}\{#OldName}"
Type: files; Name: "{autoprograms}\{#OldName}.lnk"
Type: files; Name: "{autodesktop}\{#OldName}.lnk"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "View, organise, annotate and redact PDFs"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; The old name's entries in Default apps and Open with, so the app isn't listed twice.
Root: HKA; Subkey: "Software\Kosmos\{#OldName}"; ValueType: none; Flags: deletekey
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: none; ValueName: "{#OldName}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.tif\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\.tiff\OpenWithProgids"; ValueType: none; ValueName: "{#OldProgId}"; Flags: deletevalue
; The old document type itself stays, opening the new program: anyone who chose Kosmic PDF
; as their PDF app has that choice recorded against it, and Windows guards that choice, so
; it can't be moved to the new type. This way their PDFs go on opening in Kosmos PDF.
Root: HKA; Subkey: "Software\Classes\{#OldProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#OldProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#OldProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; The document type Kosmos PDF opens.
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; Offered under "Open with" for these types (each selected file is handed to the running copy).
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.tif\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.tiff\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
; Listed in Settings > Default apps, so it can be chosen as the PDF app there.
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "View, organise, annotate and redact PDFs"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".png"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpg"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpeg"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tif"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tiff"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Kosmos PDF"; ValueData: "Software\Kosmos\Kosmos PDF\Capabilities"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Kosmos"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Kosmos\Kosmos PDF"; Flags: uninsdeletekeyifempty

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,Kosmos PDF}"; Flags: nowait postinstall skipifsilent
