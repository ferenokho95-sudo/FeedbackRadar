@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or 3.12 from python.org first.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Open http://127.0.0.1:8011 in your browser.
.venv\Scripts\python.exe app.py serve
if errorlevel 1 goto fail
pause
exit /b 0
:fail
echo Startup failed. See the error above.
pause
exit /b 1
