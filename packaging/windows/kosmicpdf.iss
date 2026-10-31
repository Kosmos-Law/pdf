; Inno Setup script for the Kosmic PDF Windows installer. Built by the workflow in
; .github/workflows/windows.yml after PyInstaller has filled dist\KosmicPDF:
;
;     ISCC /DAppVersion=0.3.1 packaging\windows\kosmicpdf.iss
;
; Installs for the current user by default (no administrator password), with the
; option to install for everyone. Registers Kosmic PDF as an "Open with" choice and in
; Default Apps for PDFs and images, without making it the default: Windows leaves that
; choice to the user.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Kosmic PDF"
#define AppExe "KosmicPDF.exe"
#define ProgId "KosmicPDF.Document"

[Setup]
AppId={{7C2E8B1A-4B7D-4F0E-9A63-2D5C1F8E6B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kosmos
AppPublisherURL=https://kosmos.law/
AppSupportURL=https://kosmos.law/pdf/
AppUpdatesURL=https://kosmos.law/pdf/
DefaultDirName={autopf}\Kosmic PDF
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=KosmicPDF-Setup-{#AppVersion}
SetupIconFile=..\..\kosmicpdf\icons\app\kosmicpdf.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; The terms of use (no warranty): the installer goes on only once they are accepted.
LicenseFile=..\..\kosmicpdf\terms.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\KosmicPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD-PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\kosmicpdf\terms.txt"; DestDir: "{app}"; DestName: "TERMS.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "View, organise, annotate and redact PDFs"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; The document type Kosmic PDF opens.
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
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "View, organise, annotate and redact PDFs"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".png"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpg"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpeg"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tif"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tiff"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Kosmic PDF"; ValueData: "Software\Kosmos\Kosmic PDF\Capabilities"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Kosmos"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Kosmos\Kosmic PDF"; Flags: uninsdeletekeyifempty

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,Kosmic PDF}"; Flags: nowait postinstall skipifsilent
