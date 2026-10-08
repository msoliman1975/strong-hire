<#
.SYNOPSIS
  Run the Kokoro text-to-speech server on Windows, outside Docker. Kokoro in Docker on a laptop
  can be 5 times slower than real time, which makes the voice interview unusable.

.DESCRIPTION
  The first run downloads Kokoro-FastAPI (a pinned release), installs its Python packages with uv,
  and downloads the Kokoro-82M model (about 330 MB). Later runs only start the server. Stop it with
  Ctrl+C.

  Before the first run, install eSpeak NG (it needs administrator rights):
    https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi

  Then point the app at this server. Add this line to .env and restart the profile:
    TTS_API_BASE=http://host.rancher-desktop.internal:8881/v1
    ./scripts/profile.ps1 claude -Voice
  To go back to Kokoro in Docker, remove the line and restart the profile again.

  When Windows asks whether Python may use the network, allow private networks. Docker reaches the
  server through it.

.EXAMPLE
  ./scripts/kokoro-windows.ps1
  ./scripts/kokoro-windows.ps1 -Port 8882
#>
[CmdletBinding()]
param(
    [int]$Port = 8881,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'StrongHire\kokoro-fastapi')
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Release = 'v0.9.0'
$Repo = 'https://github.com/remsky/Kokoro-FastAPI'
$Espeak = 'C:\Program Files\eSpeak NG\libespeak-ng.dll'

# Native tools write progress to stderr; with 'Stop' that would end the script.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit code $LASTEXITCODE)" }
}

foreach ($tool in 'git', 'uv') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH." }
}
if (-not (Test-Path $Espeak)) {
    throw "eSpeak NG is missing ($Espeak). Install it first: https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi"
}

if (-not (Test-Path (Join-Path $InstallDir 'pyproject.toml'))) {
    Write-Host "==> Downloading Kokoro-FastAPI $Release to $InstallDir"
    New-Item -ItemType Directory -Force (Split-Path -Parent $InstallDir) | Out-Null
    Invoke-Native 'git' @('clone', '--depth', '1', '--branch', $Release, $Repo, $InstallDir)
}

Set-Location $InstallDir
$env:PHONEMIZER_ESPEAK_LIBRARY = $Espeak
$env:PYTHONUTF8 = '1'
$env:PROJECT_ROOT = $InstallDir
$env:USE_GPU = 'false'
$env:PYTHONPATH = "$InstallDir;$InstallDir/api"
$env:MODEL_DIR = 'src/models'
$env:VOICES_DIR = 'src/voices/v1_0'
$env:WEB_PLAYER_PATH = "$InstallDir/web"
$env:UV_NATIVE_TLS = '1'   # trust the Windows certificate store (networks with TLS inspection)

# Check for an installed package, not the folder: a stopped install leaves an empty .venv behind.
if (-not (Test-Path '.venv\Lib\site-packages	orch')) {
    Write-Host '==> Installing Python packages (first run, or the last install did not finish)'
    if (-not (Test-Path '.venv')) { Invoke-Native 'uv' @('venv', '--python', '3.12') }
    Invoke-Native 'uv' @('pip', 'install', '-e', '.[cpu]')
}

# Python's own downloads do not use the Windows store. On networks with TLS inspection, add the
# extra CA from infra/certs (see its README) to Python's list.
$extraCa = Join-Path $Root 'infra\certs\extra-ca.crt'
if (Test-Path $extraCa) {
    try {
        $certifi = (Invoke-Native 'uv' @('run', '--no-sync', 'python', '-c', 'import certifi; print(certifi.where())') | Select-Object -Last 1).Trim()
        $bundle = Join-Path $InstallDir 'ca-bundle.pem'
        (Get-Content -Raw $certifi) + "`n" + (Get-Content -Raw $extraCa) | Set-Content -Encoding ascii $bundle
        $env:SSL_CERT_FILE = $bundle
        $env:REQUESTS_CA_BUNDLE = $bundle
    } catch {
        Write-Warning "Could not add $extraCa to Python's CA list: $_"
    }
}

if (-not (Test-Path 'api\src\models\v1_0\kokoro-v1_0.pth')) {
    Write-Host '==> Downloading the Kokoro-82M model (first run only)'
    Invoke-Native 'uv' @('run', '--no-sync', 'python', 'docker/scripts/download_model.py', '--output', 'api/src/models/v1_0')
}

Write-Host "==> Kokoro on http://localhost:$Port (Docker: http://host.rancher-desktop.internal:$Port/v1). Ctrl+C stops it."
& uv run --no-sync uvicorn api.src.main:app --host 0.0.0.0 --port $Port
