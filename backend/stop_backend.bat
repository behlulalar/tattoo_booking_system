@echo off
echo ========================================
echo   Backend Kapatiliyor...
echo ========================================
echo.

REM Port 5000'i kullanan process'leri bul ve kapat
powershell -Command "$port = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($port) { Stop-Process -Id $port -Force; Write-Host 'Backend kapatildi!' } else { Write-Host 'Backend zaten kapaliydi.' }"

echo.
echo ========================================
echo   Tamamlandi!
echo ========================================
pause
