@echo off
REM Starts the roon-tidal-voice server AND the ngrok tunnel (static domain).
REM Safe to re-run: kills any previous instances first.
cd /d "%~dp0"
set "PATH=C:\Users\PC\node\node-v24.18.0-win-x64;%LOCALAPPDATA%\Microsoft\WindowsApps;%PATH%"

REM -- stop anything already on port 8791 (old or new server) --
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
taskkill /im ngrok.exe /f >nul 2>&1
timeout /t 2 >nul

REM -- start the Roon voice server (minimized) --
start "roon-tidal-voice server" /min cmd /c "node "%~dp0app.js" >> "%~dp0server-log.txt" 2>&1"

REM -- start the ngrok tunnel on the permanent domain (minimized) --
start "ngrok tunnel" /min cmd /c "ngrok http --url=bronchially-hydrocyanic-ruthann.ngrok-free.dev 8791 --log stdout > "%~dp0ngrok-log.txt" 2>&1"

echo Started server (port 8791) and tunnel:
echo   https://bronchially-hydrocyanic-ruthann.ngrok-free.dev
