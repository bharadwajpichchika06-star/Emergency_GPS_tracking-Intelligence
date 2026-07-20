@echo off
title GPS Emergency Tracker
color 0A
cls

echo.
echo  ============================================================
echo    GPS Emergency Tracker  ^|  Starting up...
echo  ============================================================
echo.

:: ── Step 1: Check Python ────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python is NOT installed or not in PATH.
    echo.
    echo  Please install Python 3.10 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, tick the box:
    echo    "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] %PYVER% found.

:: ── Step 2: Install / upgrade required packages ──────────────────────────────
echo  [..] Installing required packages (first run may take ~1 minute)...
echo.
pip install --quiet --upgrade pip
pip install --quiet -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Try running this manually:  pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo  [OK] All packages installed.

:: ── Step 3: Migrate database (adds new columns if needed) ────────────────────
echo  [..] Checking database...
python "%~dp0migrate_db.py" >nul 2>&1
echo  [OK] Database ready.

:: ── Step 4: Show access info ─────────────────────────────────────────────────
echo.
echo  ============================================================
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set _IP=%%a
    goto :got_ip
)
:got_ip
set _IP=%_IP: =%

echo.
echo    Browser (this PC)  :  http://localhost:5000
echo    Mobile / LAN       :  http://%_IP%:5000
echo.
echo    Admin email        :  admin@gpstracker.com
echo    Admin password     :  admin123
echo.
echo    Press CTRL+C to stop the server at any time.
echo  ============================================================
echo.

:: ── Step 5: Launch Flask ──────────────────────────────────────────────────────
python "%~dp0app.py"

:: If app exits / crashes, keep the window open so user can read the error
echo.
echo  [!] The server has stopped.  See any error messages above.
echo.
pause
