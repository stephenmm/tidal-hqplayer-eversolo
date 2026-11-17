@echo off
REM Stops any running server on port 8791 and starts the (updated) server.
cd /d "%~dp0"
set "PATH=C:\Users\PC\node\node-v24.18.0-win-x64;%PATH%"
echo Stopping any existing server on port 8791...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 2 >nul
echo Starting server (leave this window open)...
node app.js > server-log.txt 2>&1
echo.
echo Server stopped. Press any key to close.
pause
