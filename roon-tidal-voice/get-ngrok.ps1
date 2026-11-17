# Downloads portable ngrok.exe into this folder, trying official URLs in order.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip  = Join-Path $dir 'ngrok.zip'
$exe  = Join-Path $dir 'ngrok.exe'

if (Test-Path $exe) { Write-Host 'ngrok.exe already present'; exit 0 }

$urls = @(
  'https://dl.ngrok.com/ngrok-v3-stable-windows-amd64.zip',
  'https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip',
  'https://ngrok-agent.s3.amazonaws.com/ngrok-v3-stable-windows-amd64.zip'
)

foreach ($u in $urls) {
  try {
    Write-Host "Trying $u ..."
    Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing
    if ((Get-Item $zip).Length -gt 1MB) {
      Expand-Archive -Path $zip -DestinationPath $dir -Force
      Remove-Item $zip
      if (Test-Path $exe) { Write-Host 'ngrok.exe downloaded OK'; exit 0 }
    }
  } catch { Write-Host "  failed: $($_.Exception.Message)" }
}

# Last resort: winget (installs system-wide instead of portable)
Write-Host 'Direct downloads failed - trying winget...'
try {
  winget install --id ngrok.ngrok -e --accept-source-agreements --accept-package-agreements
  $cmd = Get-Command ngrok -ErrorAction Stop
  Copy-Item $cmd.Source $exe
  Write-Host 'ngrok installed via winget and copied locally'
  exit 0
} catch { Write-Host "winget failed: $($_.Exception.Message)" }

Write-Host 'ERROR: could not obtain ngrok by any method.'
exit 1
