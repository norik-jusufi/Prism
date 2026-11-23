@echo off
rem Build PRISM for Windows:
rem   dist\PRISM\PRISM.exe                 the browser executable (folder app)
rem   dist\PRISM-Setup-<version>.exe       the installer
rem
rem Needs: Python 3.14 x64 (python.org, with the "py" launcher) and Inno Setup 6.7+
rem        (https://jrsoftware.org/isdl.php, or: winget install JRSoftware.InnoSetup)
rem Usage: packaging\build_windows.bat     (from anywhere)
rem   set SKIP_BLOCKLISTS=1   to skip downloading fresh blocklists before bundling
setlocal EnableExtensions
cd /d "%~dp0.."

set "VENV=build\venv"
set "PY=%VENV%\Scripts\python.exe"

echo ==^> Build environment (%VENV%)
if not exist "%PY%" (
  py -3.14 -m venv "%VENV%" 2>nul || py -3 -m venv "%VENV%" || goto :fail
)
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt -r packaging\requirements-build.txt || goto :fail
"%PY%" packaging\make_icon.py || goto :fail
"%PY%" packaging\make_installer_art.py || goto :fail

if not "%SKIP_BLOCKLISTS%"=="1" (
  echo ==^> Fresh blocklists ^(bundled into the build^)
  "%PY%" update_blocklists.py || echo     some lists failed; building with what is there
)

echo ==^> PyInstaller
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller packaging\prism.spec || goto :fail

for /f "usebackq delims=" %%v in (`call "%PY%" -c "from version import VERSION; print(VERSION)"`) do set "VERSION=%%v"
for /f "usebackq delims=" %%v in (`call "%PY%" -c "import re; from version import VERSION as v; n=(re.findall(r'\d+', v)+['0']*4)[:4]; print('.'.join(n))"`) do set "NUMVERSION=%%v"

echo ==^> Installer
set "ISCC="
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%p set "ISCC=%%~p"
)
if not defined ISCC for /f "delims=" %%p in ('where iscc 2^>nul') do if not defined ISCC set "ISCC=%%p"
if not defined ISCC (
  echo Inno Setup 6 not found. Install it ^(winget install JRSoftware.InnoSetup^) and run this again.
  echo The executable is already built: dist\PRISM\PRISM.exe
  exit /b 1
)
"%ISCC%" /Q /DAppVersion=%VERSION% /DAppNumVersion=%NUMVERSION% packaging\windows\prism.iss || goto :fail

echo.
echo Done.
echo   executable: dist\PRISM\PRISM.exe
echo   installer:  dist\PRISM-Setup-%VERSION%.exe
exit /b 0

:fail
echo.
echo Build failed (see the messages above).
exit /b 1
