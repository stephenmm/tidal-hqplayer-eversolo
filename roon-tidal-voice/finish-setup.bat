@echo off
REM ============================================================
REM  roon-tidal-voice — ONE-TIME setup (run once, then done)
REM  Uses the Microsoft Store install of ngrok (no downloads).
REM  1. Verifies ngrok is installed
REM  2. Saves your ngrok authtoken (you paste it once)
REM  3. Installs auto-start at logon (Startup shortcut, no admin)
REM  4. Starts the server + tunnel right now
REM ============================================================
cd /d "%~dp0"
set "PATH=%LOCALAPPDATA%\Microsoft\WindowsApps;%PATH%"

echo.
echo [1/4] checking ngrok install...
where ngrok >nul 2>&1
if errorlevel 1 (
    echo   ERROR: ngrok not found. Install it from the Microsoft Store
    echo   ^(search "ngrok"^), then re-run this script.
    pause
    exit /b 1
)
echo   ngrok found OK

echo.
echo [2/4] ngrok authtoken...
ngrok config check >nul 2>&1
if errorlevel 1 (
    echo   Paste your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
    echo   ^(click Copy there, then right-click in this window to paste^)
    set /p NGROK_TOKEN="  Authtoken: "
    call ngrok config add-authtoken %%NGROK_TOKEN%%
) else (
    echo   authtoken already configured
)

echo.
echo [3/4] auto-start at logon...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\roon-tidal-voice.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0run-hidden.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.Description='Roon Tidal voice control server + tunnel'; $s.Save()"
echo   Startup shortcut created

echo.
echo [4/4] starting server + tunnel now...
call "%~dp0start-all.bat"

echo.
echo ============================================================
echo  Setup complete. Public URL:
echo    https://bronchially-hydrocyanic-ruthann.ngrok-free.dev
echo  Test:  https://bronchially-hydrocyanic-ruthann.ngrok-free.dev/health
echo ============================================================
pause
