@echo off
echo ========================================
echo   Backend Baslatiliyor...
echo ========================================
echo.

REM Eski backend process'lerini kapat
echo [1/3] Eski backend kapatiliyor...
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like '*sefa_randevu*backend*'} | Stop-Process -Force"
timeout /t 2 /nobreak > nul

REM Backend'i baslat
echo [2/3] Backend baslatiliyor...
cd /d "%~dp0"
start "Backend Server" cmd /k ".\venv_new\Scripts\activate && python app.py"

echo [3/3] Tamamlandi!
echo.
echo ========================================
echo   Backend baslatildi!
echo   Port: 5000
echo ========================================
echo.
pause
