@echo off
REM ============================================================
REM  Converts ATS-Scorer-Interview-Prep.html into a real PDF
REM  using the copy of Edge or Chrome already on this machine.
REM  Just double-click this file.
REM ============================================================

setlocal
set "SRC=%~dp0ATS-Scorer-Interview-Prep.html"
set "OUT=%~dp0ATS-Scorer-Interview-Prep.pdf"

set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if not defined BROWSER (
  echo Could not find Edge or Chrome in the usual locations.
  echo.
  echo Open ATS-Scorer-Interview-Prep.html in any browser instead,
  echo press Ctrl+P, choose "Save as PDF", and tick "Background graphics".
  pause
  exit /b 1
)

echo Using: %BROWSER%
echo Rendering PDF, please wait...
"%BROWSER%" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="%OUT%" "%SRC%"

if exist "%OUT%" (
  echo.
  echo Done: %OUT%
  start "" "%OUT%"
) else (
  echo.
  echo Headless rendering did not produce a file.
  echo Open the HTML in your browser and use Ctrl+P instead.
)
pause
endlocal
