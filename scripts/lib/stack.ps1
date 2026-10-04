# Shared helpers for scripts/models.ps1 and scripts/latency.ps1. Dot-source it; $Root must be set.

$ComposeFile = Join-Path $Root 'infra/compose.yaml'
$EnvFile = Join-Path $Root '.env'

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Assert-Docker {
    & docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop (WSL2 backend) and try again.' }
}

function Initialize-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item (Join-Path $Root '.env.example') $EnvFile
        Write-Step 'Created .env from .env.example'
    }
}

function Import-EnvFile {
    # Load .env into this process (values already set in the shell win).
    if (-not (Test-Path $EnvFile)) { return }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $name = $Matches[1]
            $value = $Matches[2].Trim().Trim('"')
            if (-not [Environment]::GetEnvironmentVariable($name)) {
                [Environment]::SetEnvironmentVariable($name, $value)
            }
        }
    }
}

function Invoke-Compose([string[]]$ComposeArgs) {
    $base = @('compose', '-f', $ComposeFile, '--profile', 'models', '--profile', 'voice')
    if (Test-Path $EnvFile) { $base += @('--env-file', $EnvFile) }
    & docker @($base + $ComposeArgs)
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($ComposeArgs -join ' ') failed (exit code $LASTEXITCODE)" }
}

function Start-ModelServices([string]$ModelProfile, [string[]]$Services) {
    # Shell variables override .env in docker compose, so this picks the profile for this run.
    $env:MODEL_PROFILE = $ModelProfile
    $env:LITELLM_PROFILE = $ModelProfile
    Write-Step "Starting $($Services -join ', ') with MODEL_PROFILE=$ModelProfile"
    Invoke-Compose (@('up', '-d', '--build', '--wait') + $Services)
}

function Invoke-HostPython([string]$ModelProfile, [string[]]$PythonArgs) {
    # Runs `uv run python ...` on the host against the LiteLLM port. Returns the exit code.
    $port = if ($env:LITELLM_PORT) { $env:LITELLM_PORT } else { '4000' }
    $saved = $env:SSL_CERT_FILE
    try {
        if ($saved) { Remove-Item Env:SSL_CERT_FILE; $env:UV_NATIVE_TLS = '1' }
        $env:MODEL_PROFILE = $ModelProfile
        $env:MODEL_GATEWAY_URL = "http://localhost:$port/v1"
        $env:MODEL_GATEWAY_API_KEY = $env:LITELLM_MASTER_KEY
        & uv run python @PythonArgs | Out-Host
        return $LASTEXITCODE
    }
    finally {
        if ($saved) { $env:SSL_CERT_FILE = $saved }
        Remove-Item Env:MODEL_GATEWAY_URL, Env:MODEL_GATEWAY_API_KEY -ErrorAction SilentlyContinue
    }
}
