@echo off
echo ========================================
echo   Frontend Baslatiliyor...
echo ========================================
echo.

REM Eski frontend process'lerini kapat
echo [1/2] Eski frontend kapatiliyor...
powershell -Command "Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }"
timeout /t 2 /nobreak > nul

REM Frontend'i baslat
echo [2/2] Frontend baslatiliyor...
cd /d "%~dp0"
start "Frontend Server" cmd /k "C:\Users\Administrator\AppData\Local\Programs\Python\Python39\python.exe -m http.server 3000 --bind 0.0.0.0"

echo.
echo ========================================
echo   Frontend baslatildi!
echo   Port: 3000
echo   URL: http://45.141.150.48:3000
echo ========================================
echo.
pause
