; Inno Setup script for PASTA (per-user install, no administrator rights needed).
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
; Input: dist\PASTA (PyInstaller one-folder build). Output: dist\PASTA-Setup-<version>.exe

#define AppName "PASTA"
#define AppVersion "3.0.0"
#define AppExe "PASTA.exe"

[Setup]
AppId={{6B0E6C1E-2E4A-4E0B-9D63-5A57A0F3C0D1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=PASTA
AppComments=Local speech-to-text and voice commands for Windows (Greek & English)
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PASTA-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
; 64-bit compressor process: a solid 3 GB archive exhausts the 32-bit compiler
LZMAUseSeparateProcess=yes
LZMADictionarySize=131072
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\PASTA_single_instance
CloseApplications=yes

[Languages]
Name: "greek"; MessagesFile: "Greek.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
greek.StartWithWindows=Εκκίνηση μαζί με τα Windows
english.StartWithWindows=Start with Windows
greek.RemoveData=Να διαγραφούν και το μοντέλο ομιλίας (~1,6 GB), οι ρυθμίσεις και το ιστορικό;
english.RemoveData=Also delete the downloaded speech model (~1.6 GB), settings and history?
greek.LaunchNow=Άνοιγμα του PASTA τώρα
english.LaunchNow=Launch PASTA now

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:StartWithWindows}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PASTA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PASTA"; \
    ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im {#AppExe} /f"; Flags: runhidden; RunOnceId: "KillPasta"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PASTA');
    if MsgBox(CustomMessage('RemoveData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\PESTO'), True, True, True);
  end;
end;
