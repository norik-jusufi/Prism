; Inno Setup script for PRISM-Setup-<version>.exe. Run by build_windows.bat
; (it passes the version and draws the artwork first); needs Inno Setup 6.7+.
;
; Looks like PRISM: dark wizard on PRISM's green-black background, with the
; prism logo (artwork from packaging/make_installer_art.py, colours from
; ui/theme.css).
;
; Fresh install: "for me only" (no admin, %LOCALAPPDATA%\Programs\PRISM) or
; "for all users" (Program Files), then edition and shortcuts.
; Update: when PRISM is already installed, the wizard offers "Update" (one
; click, keeps the folder, edition and shortcuts) or "Change options".
; Browsing data and settings live in %APPDATA%\Synterra\PRISM either way and
; survive updates and uninstalls.
;
; Silent installs (IT):  PRISM-Setup-x.y.z.exe /VERYSILENT /CURRENTUSER
;   partner edition:     ... /TASKS="partner"
;   desktop shortcut:    ... /TASKS="desktopicon"     (combine: /TASKS="partner,desktopicon")
; In-app update (updates.py): /SILENT /SUPPRESSMSGBOXES /CURRENTUSER|/ALLUSERS /RELAUNCH
;   /RELAUNCH starts PRISM again when the update is done.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppNumVersion
  #define AppNumVersion "0.0.0.0"
#endif
#ifndef ArtDir
  #define ArtDir "..\..\build\installer"
#endif
; Test builds can pass another /DAppGuid so they never touch a real install.
#ifndef AppGuid
  #define AppGuid "{B7F3DE41-E98E-4D77-B771-21F65B1A9E78}"
#endif

[Setup]
; Never change AppId: it ties updates and the uninstaller to earlier installs.
AppId={{#AppGuid}
AppName=PRISM
AppVersion={#AppVersion}
AppVerName=PRISM {#AppVersion}
AppPublisher=Synterra
AppPublisherURL=https://github.com/norik-jusufi/Prism
AppUpdatesURL=https://github.com/norik-jusufi/Prism/releases
AppComments=Privacy-first research browser, built and maintained by Synterra
DefaultDirName={autopf}\PRISM
DisableWelcomePage=no
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist
OutputBaseFilename=PRISM-Setup-{#AppVersion}
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\PRISM.exe
UninstallDisplayName=PRISM
VersionInfoVersion={#AppNumVersion}
VersionInfoProductVersion={#AppNumVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription=PRISM installer
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=yes
; Tell Explorer about the browser / .html registration below.
ChangesAssociations=yes
; --- look: PRISM's dark green theme
WizardStyle=modern dark hidebevels
WizardBackColor=#07110c
WizardBackImageFile={#ArtDir}\back-*.png
WizardBackImageOpacity=255
WizardImageFile={#ArtDir}\wizard-*.png
WizardSmallImageFile={#ArtDir}\small-*.png

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[LangOptions]
WelcomeFontName=Consolas
WelcomeFontSize=15

[Messages]
SetupAppTitle=PRISM setup
SetupWindowTitle=%1 setup
WelcomeLabel1=PRISM
WelcomeLabel2=The privacy-first browser, built and maintained by Synterra.%n%nThis installs PRISM {#AppVersion} on this PC: ad, tracker and malware blocking, containers, encrypted DNS and the developer panel, ready to go.%n%nClose PRISM before you continue.
FinishedHeadingLabel=PRISM is ready
FinishedLabelNoIcons=PRISM {#AppVersion} is installed.
FinishedLabel=PRISM {#AppVersion} is installed. Start it from the Start menu, or right here.
ClickFinish=Click Finish to close setup.
SelectTasksLabel2=Pick the edition and shortcuts, then click Next.
ReadyLabel1=Ready to install PRISM {#AppVersion}.
StatusExtractFiles=Copying PRISM...

[CustomMessages]
UpdateCaption=Update PRISM
UpdateDescription=PRISM %1 is already installed on this PC.
UpdatePrompt=Your settings, tabs, logins, vault and stats are kept either way: they live in your user profile, not in the app folder.
UpdateKeep=Update to {#AppVersion} (recommended)%nKeeps the folder, edition and shortcuts. One click.
UpdateChange=Change options%nPick the edition and shortcuts again.
UpdateWelcome=The privacy-first browser, built and maintained by Synterra.%n%nPRISM %1 is installed. This updates it to {#AppVersion}.%n%nYour settings, tabs, logins and stats stay as they are. PRISM is closed while it updates.
UpdateButton=&Update
UpdatedLabel=PRISM is updated to {#AppVersion}. Everything you saved is still there.
UpdatedHeading=PRISM is up to date

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "partner"; Description: "Partner edition (locked down: no terminal or password vault)"; GroupDescription: "Edition:"; Flags: unchecked

[InstallDelete]
; An update replaces the whole app folder, so no stale DLL from an older Qt stays behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\PRISM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PRISM"; Filename: "{app}\PRISM.exe"; Comment: "Privacy-first research browser"
Name: "{autoprograms}\PRISM - Update blocklists"; Filename: "{app}\PRISM.exe"; Parameters: "--update-blocklists"; Comment: "Download the latest ad, tracker and malware lists"
Name: "{autodesktop}\PRISM"; Filename: "{app}\PRISM.exe"; Tasks: desktopicon

[Registry]
; Registers PRISM as a web browser, so Windows lists it under Settings > Apps >
; Default apps (where it can also be picked for PDFs) and in "Open with" for pages,
; PDFs, images and text files. It does not make PRISM the
; default: only the user can, in Settings. Links then arrive as PRISM.exe "<url>"
; (see instance.py). HKA = HKCU for "for me only", HKLM for "for all users".
Root: HKA; Subkey: "Software\Classes\PRISMHTML"; ValueType: string; ValueName: ""; ValueData: "PRISM HTML Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PRISMHTML"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PRISM HTML Document"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "PRISM"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "Synterra"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\Application"; ValueType: string; ValueName: "AppUserModelId"; ValueData: "Synterra.Prism"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Classes\PRISMHTML\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"" ""%1"""

; PDFs, and other files PRISM can show (images, text, SVG, XML).
Root: HKA; Subkey: "Software\Classes\PRISMPDF"; ValueType: string; ValueName: ""; ValueData: "PRISM PDF Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PRISMPDF"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PRISM PDF Document"
Root: HKA; Subkey: "Software\Classes\PRISMPDF\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "PRISM"
Root: HKA; Subkey: "Software\Classes\PRISMPDF\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "Synterra"
Root: HKA; Subkey: "Software\Classes\PRISMPDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Classes\PRISMPDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\PRISMFILE"; ValueType: string; ValueName: ""; ValueData: "PRISM Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PRISMFILE"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PRISM Document"
Root: HKA; Subkey: "Software\Classes\PRISMFILE\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "PRISM"
Root: HKA; Subkey: "Software\Classes\PRISMFILE\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "Synterra"
Root: HKA; Subkey: "Software\Classes\PRISMFILE\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Classes\PRISMFILE\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"" ""%1"""

Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM"; ValueType: string; ValueName: ""; ValueData: "PRISM"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PRISM.exe"""
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "PRISM"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Privacy-first research browser"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\PRISM.exe"",0"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\StartMenu"; ValueType: string; ValueName: "StartMenuInternet"; ValueData: "PRISM"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\URLAssociations"; ValueType: string; ValueName: "http"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\URLAssociations"; ValueType: string; ValueName: "https"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".htm"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".html"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".shtml"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xhtml"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "PRISMPDF"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mhtml"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mht"; ValueData: "PRISMHTML"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".svg"; ValueData: "PRISMFILE"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webp"; ValueData: "PRISMFILE"
Root: HKA; Subkey: "Software\Clients\StartMenuInternet\PRISM\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xml"; ValueData: "PRISMFILE"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "PRISM"; ValueData: "Software\Clients\StartMenuInternet\PRISM\Capabilities"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.htm\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.html\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
; "Open with > PRISM" for files PRISM can show; never makes PRISM their default by itself.
Root: HKA; Subkey: "Software\Classes\.xhtml\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.shtml\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mhtml\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mht\OpenWithProgids"; ValueType: string; ValueName: "PRISMHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PRISMPDF"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.svg\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.webp\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.avif\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.gif\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.bmp\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.txt\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.json\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.xml\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.log\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: string; ValueName: "PRISMFILE"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\PRISM.exe"; Description: "{cm:LaunchProgram,PRISM}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Windows only lets the user pick the default browser, so offer to open the
; Default apps page on PRISM's entry (unticked; "Set default" is one click there).
Filename: "ms-settings:defaultapps?registeredAppUser=PRISM"; Description: "Make PRISM my default browser (opens Windows Settings)"; Flags: shellexec nowait postinstall skipifsilent unchecked runasoriginaluser; Check: not IsAdminInstallMode
Filename: "ms-settings:defaultapps?registeredAppMachine=PRISM"; Description: "Make PRISM my default browser (opens Windows Settings)"; Flags: shellexec nowait postinstall skipifsilent unchecked runasoriginaluser; Check: IsAdminInstallMode
; In-app updates run setup silently with /RELAUNCH: start PRISM again afterwards
; (as the user, never elevated, even when an all-users update asked for admin rights).
Filename: "{app}\PRISM.exe"; Flags: nowait skipifnotsilent runasoriginaluser; Check: Relaunch

[UninstallDelete]
Type: files; Name: "{app}\deployment.json"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1';
  Green = $9BF536;       // #36f59b (Pascal colours are $BBGGRR)
  Text2 = $B5C9A9;       // #a9c9b5

var
  PrevVersion: String;
  UpdatePage: TInputOptionWizardPage;

// The PRISM already installed in this install mode (per user / all users), or ''.
function InstalledVersion: String;
var
  Root: Integer;
begin
  Result := '';
  if IsAdminInstallMode then Root := HKLM else Root := HKCU;
  if not RegQueryStringValue(Root, UninstallKey, 'DisplayVersion', Result) then
    Result := '';
end;

function Updating: Boolean;
begin
  Result := PrevVersion <> '';
end;

function QuickUpdate: Boolean;
begin
  Result := Updating and (UpdatePage <> nil) and UpdatePage.Values[0];
end;

function Relaunch: Boolean;
begin
  Result := Pos('/RELAUNCH', UpperCase(GetCmdTail)) > 0;
end;

procedure SetNextCaption;
begin
  if (WizardForm.CurPageID = UpdatePage.ID) and UpdatePage.Values[0] then
    WizardForm.NextButton.Caption := CustomMessage('UpdateButton')
  else if WizardForm.CurPageID <> wpReady then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure UpdateChoiceClick(Sender: TObject);
begin
  SetNextCaption;
end;

procedure Tint(Lbl: TNewStaticText; Color: TColor);
begin
  Lbl.StyleElements := Lbl.StyleElements - [seFont];
  Lbl.Font.Color := Color;
end;

procedure InitializeWizard;
begin
  PrevVersion := InstalledVersion;

  UpdatePage := CreateInputOptionPage(wpWelcome,
    CustomMessage('UpdateCaption'),
    FmtMessage(CustomMessage('UpdateDescription'), [PrevVersion]),
    CustomMessage('UpdatePrompt'), True, False);
  UpdatePage.Add(CustomMessage('UpdateKeep'));
  UpdatePage.Add(CustomMessage('UpdateChange'));
  UpdatePage.Values[0] := True;
  UpdatePage.CheckListBox.OnClickCheck := @UpdateChoiceClick;

  if Updating then
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('UpdateWelcome'), [PrevVersion]);

  // PRISM green for headings, like the browser's own UI. (seFont off: else
  // the dark style paints every label in its own text colour.)
  Tint(WizardForm.WelcomeLabel1, Green);
  Tint(WizardForm.FinishedHeadingLabel, Green);
  Tint(WizardForm.PageNameLabel, Green);
  Tint(WizardForm.PageDescriptionLabel, Text2);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = UpdatePage.ID then
    Result := not Updating
  else if QuickUpdate and ((PageID = wpSelectDir) or (PageID = wpSelectTasks) or (PageID = wpReady)) then
    Result := True;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  SetNextCaption;
  if (CurPageID = wpFinished) and Updating then
  begin
    WizardForm.FinishedHeadingLabel.Caption := CustomMessage('UpdatedHeading');
    WizardForm.FinishedLabel.Caption := CustomMessage('UpdatedLabel');
  end;
end;

// deployment.json next to PRISM.exe picks the edition (see edition.py).
// Partner: write it. Employee: remove a partner file left by an earlier install,
// but keep any other deployment.json IT may have put there (e.g. update settings).
procedure CurStepChanged(CurStep: TSetupStep);
var
  Path: String;
  Existing: AnsiString;
begin
  if CurStep <> ssPostInstall then
    exit;
  Path := ExpandConstant('{app}\deployment.json');
  if WizardIsTaskSelected('partner') then
    SaveStringToFile(Path, '{"edition": "partner"}' + #13#10, False)
  else if FileExists(Path) and LoadStringFromFile(Path, Existing) then
    if (Pos('partner', Existing) > 0) and (Pos('updateRepo', Existing) = 0) then
      DeleteFile(Path);
end;
