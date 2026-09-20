@echo off
setlocal
cd /d "%~dp0"
title Bob - TikTok Antibot
set "PYTHON_PAGE=https://www.python.org/downloads/"
set "SETUP_LOG=logs\setup.log"

cls
echo Bob - TikTok Antibot
echo.
echo This window sets Bob up and then starts it. Here is everything it does:
echo.
echo   1. Checks that Python 3.11 or newer is on this computer.
echo   2. Makes a private folder called .venv inside this folder. Bob's parts go there,
echo      so nothing else on your computer is changed.
echo   3. Downloads one library, curl_cffi, from pypi.org (the official Python library site).
echo      It lets Bob talk to TikTok the way a normal browser does.
echo   4. Starts Bob and opens it in your browser. The address starts with http://127.0.0.1,
echo      which means this computer. Bob is not on the internet and nobody else can open it.
echo.
echo Bob only ever connects to tiktok.com. Your login stays in this folder.
echo To remove Bob completely, delete this folder. The code is open: github.com/usebobgg/bob

echo.
echo [1 of 4] Looking for Python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 goto :python_found

echo         Python 3.11 or newer was not found.
where winget >nul 2>nul
if errorlevel 1 goto :python_page
choice /C YN /N /M "        Install it now from Microsoft's winget store? This runs: winget install Python.Python.3.12  [Y/N] "
if errorlevel 2 goto :python_page
winget install -e --id Python.Python.3.12 --scope user
echo.
echo Python is installed. Close this window and open start.bat again so Windows can find it.
pause
exit /b 0

:python_page
choice /C YN /N /M "        Open the official Python download page in your browser? [Y/N] "
if not errorlevel 2 start "" "%PYTHON_PAGE%"
echo.
echo Install Python from %PYTHON_PAGE% and tick "Add python.exe to PATH", then open this file again.
pause
exit /b 1

:python_found
for /f "delims=" %%v in ('py -3 --version') do echo         Found %%v

echo.
echo [2 of 4] Preparing Bob's private folder (.venv)
if exist ".venv\Scripts\python.exe" (
  echo         Already there from last time.
) else (
  py -3 -m venv .venv || goto :venv_failed
  echo         Created.
)

echo.
echo [3 of 4] Installing what Bob needs
if exist ".venv\.installed" (
  echo         Already installed.
) else (
  echo         Downloading from pypi.org: curl_cffi
  echo         This takes about a minute the first time.
  if not exist logs mkdir logs
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt > "%SETUP_LOG%" 2>&1 || goto :install_failed
  type nul > ".venv\.installed"
  echo         Installed.
)

echo.
echo [4 of 4] Starting Bob
echo         Your browser opens in a moment. Keep this window open while you use Bob.
echo         To stop Bob, close this window or press Ctrl+C.
echo.
".venv\Scripts\python.exe" app.py
exit /b 0

:venv_failed
echo.
echo Could not create the .venv folder here. Check that you are allowed to write to this folder.
pause
exit /b 1

:install_failed
echo.
echo The download failed. Check your internet connection and open this file again. Details are in %SETUP_LOG%.
pause
exit /b 1
