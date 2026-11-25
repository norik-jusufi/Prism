; Inno Setup script for PRISM-Setup-<version>.exe. Run by build_windows.bat
; (it passes the version and draws the artwork first); needs Inno Setup 6.7+.
;
; Not the stock wizard: PRISM's own borderless, rounded setup window with a
; side rail (logo with a scanning line, live step list), a typed headline,
; sliding pages, pill buttons and a glowing progress bar ([Code] below; rail
; artwork from packaging/make_installer_art.py, colours from ui/theme.css).
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
WizardResizable=no
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
WelcomeLabel2=This installs PRISM {#AppVersion} on this PC: ad, tracker and malware blocking, containers, encrypted DNS, the developer panel and the Privacy Time Machine, ready to go.%n%nClose PRISM before you continue.
ClickNext=Press next to continue, or the cross at the top to cancel.
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
UpdateWelcome=PRISM %1 is installed. This updates it to {#AppVersion}.%n%nYour settings, tabs, logins and stats stay as they are. PRISM is closed while it updates.
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
; the setup window's side rail, one per DPI step ([Code] picks one)
Source: "{#ArtDir}\rail-*.png"; Flags: dontcopy
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
// ---------------------------------------------------------------------------
// PRISM's own setup window. Not the stock wizard: one borderless, rounded
// window with a side rail (logo with a scanning line, live step list), a
// typed headline, pages that slide in, pill buttons that light up under the
// mouse and a glowing progress bar. Inno's own pages and logic still do the
// work underneath; their buttons are moved out of sight and the pills click
// them (BM_CLICK), so Enter / Esc, silent installs and updates behave as before.
// Sizes are at 100% DPI and go through ScaleX / ScaleY.
// ---------------------------------------------------------------------------
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1';
  // Pascal colours are $BBGGRR
  Green = $9BF536;       // #36f59b
  GreenHi = $7AFF74;     // #74ff7a
  GreenDim = $66A81F;    // #1fa866
  Bg = $070A04;          // #040a07  rail
  Bg1 = $0C1107;         // #07110c  window
  Bg2 = $121A0B;         // #0b1a12
  Line = $263816;        // #163826
  Line2 = $37551F;       // #1f5537
  Text1 = $ECF5E8;       // #e8f5ec
  Text2 = $B5C9A9;       // #a9c9b5
  Muted = $70825F;       // #5f8270
  Danger = $6D5FFF;      // #ff5f6d

  WinW = 760;  WinH = 470;
  RailW = 232;
  StepsTop = 238;          // make_installer_art.py RAIL_STEPS_TOP
  Pad = 30;
  HeadH = 100;
  FootH = 66;

  GWL_EXSTYLE = -20;
  WS_EX_LAYERED = $80000;
  LWA_ALPHA = 2;
  WM_NCLBUTTONDOWN = $A1;
  HTCAPTION = 2;
  BM_CLICK = $F5;
  SW_MINIMIZE = 6;

type
  TPointRec = record
    X, Y: Longint;
  end;

function SetTimer(hWnd, nIDEvent, uElapse, lpTimerFunc: Longword): Longword;
  external 'SetTimer@user32.dll stdcall';
function KillTimer(hWnd, nIDEvent: Longword): Bool;
  external 'KillTimer@user32.dll stdcall';
function CreateRoundRectRgn(X1, Y1, X2, Y2, W, H: Integer): Longword;
  external 'CreateRoundRectRgn@gdi32.dll stdcall';
function SetWindowRgn(Wnd: HWND; Rgn: Longword; Redraw: Bool): Integer;
  external 'SetWindowRgn@user32.dll stdcall';
function GetWindowLong(Wnd: HWND; Index: Integer): Longint;
  external 'GetWindowLongW@user32.dll stdcall';
function SetWindowLong(Wnd: HWND; Index: Integer; NewLong: Longint): Longint;
  external 'SetWindowLongW@user32.dll stdcall';
function SetLayeredWindowAttributes(Wnd: HWND; Key: DWORD; Alpha: Byte; Flags: DWORD): Bool;
  external 'SetLayeredWindowAttributes@user32.dll stdcall';
function DwmSetWindowAttribute(Wnd: HWND; Attr: DWORD; var Value: Integer; Size: DWORD): Integer;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall delayload';
function GetCursorPos(var P: TPointRec): Bool;
  external 'GetCursorPos@user32.dll stdcall';
function GetAsyncKeyState(Key: Integer): SmallInt;
  external 'GetAsyncKeyState@user32.dll stdcall';
function GetForegroundWindow: HWND;
  external 'GetForegroundWindow@user32.dll stdcall';
function ReleaseCapture: Bool;
  external 'ReleaseCapture@user32.dll stdcall';
function ShowWindow(Wnd: HWND; Cmd: Integer): Bool;
  external 'ShowWindow@user32.dll stdcall';

var
  PrevVersion: String;
  UpdatePage: TInputOptionWizardPage;

  TimerID: Longword;
  Ticks: Integer;
  Busy: Boolean;
  Alpha: Integer;
  WasDown: Boolean;

  Rail: TPanel;
  RailImg: TBitmapImage;
  Scan, ScanTrail: TPanel;
  ScanY: Integer;
  StepLbl: array [0..3] of TLabel;
  StepDot: array [0..3] of TPanel;
  StepLink: array [0..2] of TPanel;
  ActiveStep: Integer;

  Title, Subtitle, CloseLbl, MinLbl, VerLbl: TLabel;
  TitleText: String;
  TitlePos: Integer;

  NextPill, BackPill: TPanel;
  NextHot, BackHot: Boolean;

  Track, Fill, Glint: TPanel;
  PctLbl: TLabel;
  FillW, GlintX: Integer;

  SlideOff: Integer;
  NotebookLeft: Integer;

// ------------------------------------------------------------ update logic
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
  else if (WizardForm.CurPageID <> wpReady) and (WizardForm.CurPageID <> wpFinished) then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure UpdateChoiceClick(Sender: TObject);
begin
  SetNextCaption;
end;

// ------------------------------------------------------------------ helpers
procedure Tint(Ctl: TNewStaticText; Color: TColor);
begin
  Ctl.StyleElements := Ctl.StyleElements - [seFont];
  Ctl.Font.Color := Color;
end;

procedure RoundCtl(Ctl: TWinControl; Radius: Integer);
begin
  SetWindowRgn(Ctl.Handle, CreateRoundRectRgn(0, 0, Ctl.Width + 1, Ctl.Height + 1, Radius, Radius), True);
end;

function NewLabel(Parent: TWinControl; Caption: String; FontName: String; Size: Integer; Bold: Boolean;
                  Color, Back: TColor): TLabel;
begin
  Result := TLabel.Create(WizardForm);
  Result.Parent := Parent;
  Result.StyleElements := [];
  Result.AutoSize := True;
  Result.Caption := Caption;
  Result.Font.Name := FontName;
  Result.Font.Size := Size;
  if Bold then Result.Font.Style := [fsBold];
  Result.Font.Color := Color;
  Result.Color := Back;
end;

function NewBox(Parent: TWinControl; Color: TColor): TPanel;
begin
  Result := TPanel.Create(WizardForm);
  Result.Parent := Parent;
  Result.BevelOuter := bvNone;
  Result.ParentBackground := False;
  Result.StyleElements := [];
  Result.Caption := '';
  Result.Color := Color;
end;

function NoAmp(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '&', '', True);
end;

function Inside(const P: TPointRec; L, T, W, H: Integer): Boolean;
begin
  Result := (P.X >= WizardForm.Left + L) and (P.X < WizardForm.Left + L + W) and
            (P.Y >= WizardForm.Top + T) and (P.Y < WizardForm.Top + T + H);
end;

// ----------------------------------------------------------------- headline
procedure SetHeadline(const Text, Sub: String);
begin
  if Text <> TitleText then
  begin
    TitleText := Text;
    TitlePos := 0;
  end;
  Subtitle.Caption := Sub;
end;

procedure SetStep(Step: Integer);
var
  I: Integer;
begin
  ActiveStep := Step;
  for I := 0 to 3 do
  begin
    if I < Step then
    begin
      StepLbl[I].Font.Color := Text2;
      StepDot[I].Color := GreenDim;
    end
    else if I = Step then
    begin
      StepLbl[I].Font.Color := Green;
      StepDot[I].Color := Green;
    end
    else
    begin
      StepLbl[I].Font.Color := Muted;
      StepDot[I].Color := Line2;
    end;
    if I < 3 then
      if I < Step then StepLink[I].Color := GreenDim else StepLink[I].Color := Line;
  end;
end;

// -------------------------------------------------------------- pill buttons
procedure PillClick(Sender: TObject);
begin
  if (Sender = NextPill) and WizardForm.NextButton.Enabled then
    PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0)
  else if (Sender = BackPill) and WizardForm.BackButton.Enabled then
    PostMessage(WizardForm.BackButton.Handle, BM_CLICK, 0, 0);
end;

function NewPill(Primary: Boolean): TPanel;
begin
  Result := NewBox(WizardForm, Bg2);
  Result.Font.Name := 'Consolas';
  Result.Font.Size := 10;
  Result.Font.Style := [fsBold];
  Result.Cursor := crHand;
  Result.OnClick := @PillClick;
  if Primary then
  begin
    Result.Color := Green;
    Result.Font.Color := Bg;
  end
  else
    Result.Font.Color := Text2;
end;

procedure PaintPills;
var
  Show: Boolean;
begin
  Show := WizardForm.NextButton.Visible;
  NextPill.Visible := Show;
  if Show then
  begin
    NextPill.Caption := LowerCase(NoAmp(WizardForm.NextButton.Caption)) + '  ' + #$203A;
    if not WizardForm.NextButton.Enabled then
    begin
      NextPill.Color := Line2; NextPill.Font.Color := Muted;
    end
    else if NextHot then
    begin
      NextPill.Color := GreenHi; NextPill.Font.Color := Bg;
    end
    else
    begin
      NextPill.Color := Green; NextPill.Font.Color := Bg;
    end;
  end;
  Show := WizardForm.BackButton.Visible and WizardForm.BackButton.Enabled;
  BackPill.Visible := Show;
  if Show then
  begin
    BackPill.Caption := #$2039 + '  ' + LowerCase(NoAmp(WizardForm.BackButton.Caption));
    if BackHot then
    begin
      BackPill.Color := Line2; BackPill.Font.Color := Green;
    end
    else
    begin
      BackPill.Color := Bg2; BackPill.Font.Color := Text2;
    end;
  end;
end;

// ------------------------------------------------------------- window chrome
procedure CloseClick(Sender: TObject);
begin
  WizardForm.Close;
end;

procedure MinClick(Sender: TObject);
begin
  ShowWindow(WizardForm.Handle, SW_MINIMIZE);
end;

procedure RoundWindow;
var
  V: Integer;
begin
  // Windows 11: the system's own anti-aliased rounded corners and a green
  // hairline border. Windows 10: a rounded window region.
  if GetWindowsVersion >= $0A0055F0 then
  begin
    V := 2;                                  // DWMWCP_ROUND
    DwmSetWindowAttribute(WizardForm.Handle, 33, V, 4);
    V := Line2;                              // DWMWA_BORDER_COLOR (COLORREF = $00BBGGRR)
    DwmSetWindowAttribute(WizardForm.Handle, 34, V, 4);
  end
  else
    RoundCtl(WizardForm, ScaleX(22));
end;

// --------------------------------------------------------------- animation
procedure Tick(H, Msg, IdEvent, Time: Longword);
var
  P: TPointRec;
  Down, Over: Boolean;
  Target, Span: Integer;
  S: String;
begin
  if Busy or (WizardForm = nil) then exit;
  Busy := True;
  try
    Inc(Ticks);

    // fade in
    if Alpha < 255 then
    begin
      if WizardForm.Visible then
      begin
        Alpha := Alpha + 26;
        if Alpha >= 255 then
        begin
          Alpha := 255;
          SetWindowLong(WizardForm.Handle, GWL_EXSTYLE, GetWindowLong(WizardForm.Handle, GWL_EXSTYLE) and not WS_EX_LAYERED);
        end
        else
          SetLayeredWindowAttributes(WizardForm.Handle, 0, Alpha, LWA_ALPHA);
      end;
    end;

    // typed headline with a blinking block cursor
    if TitlePos < Length(TitleText) then
      TitlePos := TitlePos + 1;
    S := Copy(TitleText, 1, TitlePos);
    if (TitlePos < Length(TitleText)) or ((Ticks div 32) mod 2 = 0) then
      S := S + '_';
    if Title.Caption <> S then Title.Caption := S;

    // scanning line over the logo
    ScanY := ScanY + ScaleY(2);
    if ScanY > ScaleY(150) then ScanY := ScaleY(30);
    Scan.Top := ScanY;
    ScanTrail.Top := ScanY - ScaleY(5);

    // the current step's dot breathes
    case (Ticks div 9) mod 4 of
      0: StepDot[ActiveStep].Color := Green;
      1: StepDot[ActiveStep].Color := GreenHi;
      2: StepDot[ActiveStep].Color := Green;
      3: StepDot[ActiveStep].Color := GreenDim;
    end;

    // pages slide in from the right
    if SlideOff > 0 then
    begin
      SlideOff := (SlideOff * 7) div 10;
      if SlideOff < 2 then SlideOff := 0;
      WizardForm.OuterNotebook.Left := NotebookLeft + SlideOff;
    end;

    // progress bar: eases to the real value, a glint runs along the fill
    if WizardForm.CurPageID = wpInstalling then
    begin
      Span := WizardForm.ProgressGauge.Max - WizardForm.ProgressGauge.Min;
      if Span > 0 then
        Target := (Track.Width * (WizardForm.ProgressGauge.Position - WizardForm.ProgressGauge.Min)) div Span
      else
        Target := 0;
      FillW := FillW + (Target - FillW) div 4 + Ord(Target > FillW);
      if FillW > Track.Width then FillW := Track.Width;
      Fill.Width := FillW;
      GlintX := GlintX + ScaleX(6);
      if GlintX > FillW + ScaleX(40) then GlintX := -ScaleX(40);
      Glint.Left := GlintX;
      if Track.Width > 0 then
        PctLbl.Caption := IntToStr((FillW * 100) div Track.Width) + '%';
    end;

    // hover, and dragging the window by the rail or the header
    if GetCursorPos(P) then
    begin
      Over := NextPill.Visible and Inside(P, NextPill.Left, NextPill.Top, NextPill.Width, NextPill.Height);
      if Over <> NextHot then NextHot := Over;
      Over := BackPill.Visible and Inside(P, BackPill.Left, BackPill.Top, BackPill.Width, BackPill.Height);
      if Over <> BackHot then BackHot := Over;
      if Inside(P, CloseLbl.Left - ScaleX(6), CloseLbl.Top - ScaleY(4), CloseLbl.Width + ScaleX(12), CloseLbl.Height + ScaleY(8)) then
        CloseLbl.Font.Color := Danger
      else
        CloseLbl.Font.Color := Muted;
      if Inside(P, MinLbl.Left - ScaleX(6), MinLbl.Top - ScaleY(4), MinLbl.Width + ScaleX(12), MinLbl.Height + ScaleY(8)) then
        MinLbl.Font.Color := Green
      else
        MinLbl.Font.Color := Muted;

      Down := GetAsyncKeyState(1) < 0;
      if Down and not WasDown and (GetForegroundWindow = WizardForm.Handle) then
        if Inside(P, 0, 0, ScaleX(RailW), WizardForm.ClientHeight) or
           (Inside(P, ScaleX(RailW), 0, WizardForm.ClientWidth - ScaleX(RailW), ScaleY(HeadH - 20)) and
            not Inside(P, MinLbl.Left - ScaleX(8), 0, WizardForm.ClientWidth, ScaleY(40))) then
        begin
          ReleaseCapture;
          PostMessage(WizardForm.Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        end;
      WasDown := Down;
    end;
    PaintPills;
  finally
    Busy := False;
  end;
end;

// ------------------------------------------------------------------- build
function RailFile: String;
var
  Dpi, Best, I: Integer;
  Sizes: array of Integer;
begin
  Sizes := [100, 125, 150, 175, 200, 250];
  Dpi := ScaleX(100);
  Best := 100;
  for I := 0 to High(Sizes) do
    if Sizes[I] <= Dpi then Best := Sizes[I];
  Result := 'rail-' + IntToStr(Best) + '.png';
end;

procedure BuildSkin;
var
  I, CW, CH, X0, CWid, BodyH, Y: Integer;
  F: String;
  Names: array of String;
begin
  CW := ScaleX(WinW);
  CH := ScaleY(WinH);

  WizardForm.BorderStyle := bsNone;
  WizardForm.ClientWidth := CW;
  WizardForm.ClientHeight := CH;

  // --- rail
  Rail := NewBox(WizardForm, Bg);
  Rail.SetBounds(0, 0, ScaleX(RailW), CH);
  RailImg := TBitmapImage.Create(WizardForm);
  RailImg.Parent := Rail;
  RailImg.SetBounds(0, 0, Rail.Width, CH);
  F := RailFile;
  ExtractTemporaryFile(F);
  RailImg.PngImage.LoadFromFile(ExpandConstant('{tmp}\') + F);
  RailImg.Stretch := True;

  ScanTrail := NewBox(Rail, Line2);
  ScanTrail.SetBounds(ScaleX(58), ScaleY(40), Rail.Width - ScaleX(116), ScaleY(1));
  Scan := NewBox(Rail, Green);
  Scan.SetBounds(ScaleX(52), ScaleY(40), Rail.Width - ScaleX(104), ScaleY(2));
  ScanY := ScaleY(30);

  Names := ['welcome', 'configure', 'install', 'launch'];
  for I := 0 to 3 do
  begin
    Y := ScaleY(StepsTop + 22 + I * 36);
    StepDot[I] := NewBox(Rail, Line2);
    StepDot[I].SetBounds(ScaleX(34), Y + ScaleY(5), ScaleX(9), ScaleY(9));
    RoundCtl(StepDot[I], ScaleX(9));
    StepLbl[I] := NewLabel(Rail, Format('%.2d  %s', [I + 1, Names[I]]), 'Consolas', 10, False, Muted, Bg);
    StepLbl[I].Left := ScaleX(56);
    StepLbl[I].Top := Y;
    if I < 3 then
    begin
      StepLink[I] := NewBox(Rail, Line);
      StepLink[I].SetBounds(ScaleX(38), Y + ScaleY(17), ScaleX(1), ScaleY(36) - ScaleY(14));
    end;
  end;

  // --- header
  X0 := ScaleX(RailW + Pad);
  CWid := CW - X0 - ScaleX(Pad);
  Title := NewLabel(WizardForm, '', 'Consolas', 16, True, Green, Bg1);
  // fixed size, so every caption change repaints the whole line
  Title.AutoSize := False;
  Title.SetBounds(X0, ScaleY(28), CWid - ScaleX(60), ScaleY(32));
  Subtitle := NewLabel(WizardForm, '', 'Segoe UI', 9, False, Text2, Bg1);
  Subtitle.AutoSize := False;
  Subtitle.WordWrap := True;
  Subtitle.SetBounds(X0, ScaleY(62), CWid, ScaleY(32));
  CloseLbl := NewLabel(WizardForm, #$2715, 'Segoe UI Symbol', 11, False, Muted, Bg1);
  CloseLbl.Left := CW - ScaleX(36);
  CloseLbl.Top := ScaleY(12);
  CloseLbl.Cursor := crHand;
  CloseLbl.OnClick := @CloseClick;
  MinLbl := NewLabel(WizardForm, #$2014, 'Segoe UI', 11, False, Muted, Bg1);
  MinLbl.Left := CW - ScaleX(70);
  MinLbl.Top := ScaleY(11);
  MinLbl.Cursor := crHand;
  MinLbl.OnClick := @MinClick;
  VerLbl := NewLabel(WizardForm, 'v{#AppVersion}  ' + #$00B7 + '  stable', 'Consolas', 8, False, Muted, Bg1);
  VerLbl.Left := X0;
  VerLbl.Top := CH - ScaleY(38);

  // --- Inno's pages, re-laid out under the header
  BodyH := CH - ScaleY(HeadH) - ScaleY(FootH);
  NotebookLeft := X0;
  WizardForm.OuterNotebook.SetBounds(X0, ScaleY(HeadH), CWid, BodyH);
  WizardForm.MainPanel.Visible := False;
  WizardForm.Bevel.Visible := False;
  WizardForm.Bevel1.Visible := False;
  WizardForm.InnerNotebook.SetBounds(0, 0, CWid, BodyH);
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  WizardForm.WelcomeLabel1.Visible := False;
  WizardForm.WelcomeLabel2.SetBounds(0, 0, CWid, BodyH);
  WizardForm.FinishedHeadingLabel.Visible := False;
  WizardForm.FinishedLabel.SetBounds(0, 0, CWid, ScaleY(60));
  WizardForm.RunList.SetBounds(0, ScaleY(70), CWid, BodyH - ScaleY(70));
  Tint(WizardForm.WelcomeLabel2, Text2);
  Tint(WizardForm.FinishedLabel, Text2);

  // --- buttons: the real ones go out of sight, the pills click them
  WizardForm.NextButton.Left := -ScaleX(2000);
  WizardForm.BackButton.Left := -ScaleX(2000);
  WizardForm.CancelButton.Left := -ScaleX(2000);
  NextPill := NewPill(True);
  NextPill.SetBounds(CW - ScaleX(Pad) - ScaleX(138), CH - ScaleY(50), ScaleX(138), ScaleY(34));
  RoundCtl(NextPill, ScaleY(34));
  BackPill := NewPill(False);
  BackPill.SetBounds(NextPill.Left - ScaleX(104), NextPill.Top, ScaleX(94), ScaleY(34));
  RoundCtl(BackPill, ScaleY(34));

  // --- progress: a rounded track, a green fill and a running glint
  WizardForm.ProgressGauge.Visible := False;
  Track := NewBox(WizardForm.InstallingPage, Line);
  Track.SetBounds(0, WizardForm.ProgressGauge.Top + ScaleY(8), CWid, ScaleY(10));
  RoundCtl(Track, ScaleY(10));
  Fill := NewBox(Track, Green);
  Fill.SetBounds(0, 0, 0, Track.Height);
  Glint := NewBox(Fill, GreenHi);
  Glint.SetBounds(-ScaleX(40), 0, ScaleX(34), Track.Height);
  PctLbl := NewLabel(WizardForm.InstallingPage, '0%', 'Consolas', 22, True, Green, Bg1);
  PctLbl.Left := 0;
  PctLbl.Top := Track.Top + ScaleY(24);
  Tint(WizardForm.StatusLabel, Text1);
  Tint(WizardForm.FilenameLabel, Muted);

  RoundWindow;
  SetWindowLong(WizardForm.Handle, GWL_EXSTYLE, GetWindowLong(WizardForm.Handle, GWL_EXSTYLE) or WS_EX_LAYERED);
  SetLayeredWindowAttributes(WizardForm.Handle, 0, 0, LWA_ALPHA);
  Alpha := 0;
  SetStep(0);
  TimerID := SetTimer(0, 0, 15, CreateCallback(@Tick));
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

  BuildSkin;
end;

procedure DeinitializeSetup;
begin
  if TimerID <> 0 then
    KillTimer(0, TimerID);
  TimerID := 0;
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

  case CurPageID of
    wpWelcome:
      begin
        SetStep(0);
        if Updating then
          SetHeadline('> update prism', 'The privacy-first browser, built and maintained by Synterra.')
        else
          SetHeadline('> install prism', 'The privacy-first browser, built and maintained by Synterra.');
      end;
    wpSelectDir:
      begin
        SetStep(1);
        SetHeadline('> select target', WizardForm.PageDescriptionLabel.Caption);
      end;
    wpSelectTasks:
      begin
        SetStep(1);
        SetHeadline('> configure', 'Edition and shortcuts. Change them any time by running setup again.');
      end;
    wpReady:
      begin
        SetStep(1);
        SetHeadline('> ready to deploy', 'Check the summary, then install.');
      end;
    wpPreparing, wpInstalling:
      begin
        SetStep(2);
        if Updating then
          SetHeadline('> updating prism', 'Your settings, logins and stats stay where they are.')
        else
          SetHeadline('> deploying prism', 'Copying the browser, the blocklists and Chromium.');
      end;
    wpFinished:
      begin
        SetStep(3);
        SetHeadline('> ' + LowerCase(WizardForm.FinishedHeadingLabel.Caption),
                    'Ad, tracker and malware blocking are on. The Privacy Time Machine is one click away.');
      end;
  else
    begin
      SetStep(1);
      SetHeadline('> ' + LowerCase(WizardForm.PageNameLabel.Caption), WizardForm.PageDescriptionLabel.Caption);
    end;
  end;

  // slide the new page in
  SlideOff := ScaleX(44);
  WizardForm.OuterNotebook.Left := NotebookLeft + SlideOff;
  FillW := 0;
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
