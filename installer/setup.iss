[Setup]
AppName=StreamOS
AppVersion=0.0.1
AppPublisher=StreamOS
DefaultDirName={localappdata}\StreamOS
DefaultGroupName=StreamOS
UninstallDisplayIcon={app}\StreamOS.exe
Compression=lzma2
SolidCompression=yes
OutputDir=..\
OutputBaseFilename=StreamOS_0.0.1_Setup
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"
Name: "betterttv"; Description: "BetterTTV automatisch installieren (Firefox)"; GroupDescription: "Erweiterungen:"; Flags: unchecked

[Files]
Source: "..\dist\StreamOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Add icon if we have one
; Source: "..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\StreamOS"; Filename: "{app}\StreamOS.exe"
Name: "{group}\Deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\StreamOS"; Filename: "{app}\StreamOS.exe"; Tasks: desktopicon

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  AppdataDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    // Create AppData folder for configs
    AppdataDir := ExpandConstant('{userappdata}\StreamOS');
    if not DirExists(AppdataDir) then
    begin
      CreateDir(AppdataDir);
    end;
    
    // BetterTTV logic (Placeholder for real installation)
    if IsTaskSelected('betterttv') then
    begin
      MsgBox('BetterTTV wird im Hintergrund konfiguriert (in Zukunft).', mbInformation, MB_OK);
    end;
  end;
end;
