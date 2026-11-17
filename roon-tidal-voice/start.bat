@echo off
REM Starts the roon-tidal-voice server. Leave this window open while using voice control.
cd /d "%~dp0"
set "PATH=C:\Users\PC\node\node-v24.18.0-win-x64;%PATH%"
node app.js > "%~dp0server-log.txt" 2>&1
pause
