@echo off
REM Installs dependencies for roon-tidal-voice and logs the result.
cd /d "%~dp0"
set "PATH=C:\Users\PC\node\node-v24.18.0-win-x64;%PATH%"
(
  echo === node version ===
  node -v
  echo === npm version ===
  npm -v
  echo === npm install ===
  call npm install
  echo === EXIT CODE %ERRORLEVEL% ===
) > setup-log.txt 2>&1
echo Setup finished. Results written to setup-log.txt
pause
