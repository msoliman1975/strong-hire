<#
.SYNOPSIS
  Strong Hire developer commands for Windows PowerShell.

.EXAMPLE
  ./scripts/dev.ps1 up                  # core profile: postgres, redis, api, worker, web
  ./scripts/dev.ps1 up -Profile all     # core + models + voice
  ./scripts/dev.ps1 logs -Service api
  ./scripts/dev.ps1 test
  ./scripts/dev.ps1 down -Volumes       # also delete the database and model volumes
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'logs', 'ps', 'test', 'lint', 'migrate', 'seed', 'schemas', 'help')]
    [string]$Command = 'help',

    [Alias('Profile')]
    [ValidateSet('core', 'models', 'voice', 'all')]
    [string]$StackProfile = 'core',

    [string]$Service = '',

    [switch]$Volumes
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root 'infra/compose.yaml'
$EnvFile = Join-Path $Root '.env'
$AllProfiles = @('core', 'models', 'voice')

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Assert-LastExit([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Initialize-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item (Join-Path $Root '.env.example') $EnvFile
        Write-Step 'Created .env from .env.example'
    }
}

function Initialize-ExtraCerts {
    # Networks with TLS inspection need their root CA inside the images (see infra/certs/README.md).
    $certDir = Join-Path $Root 'infra/certs'
    $haveCrt = @(Get-ChildItem -Path $certDir -Filter '*.crt' -ErrorAction SilentlyContinue).Count -gt 0
    if (-not $haveCrt -and $env:SSL_CERT_FILE -and (Test-Path $env:SSL_CERT_FILE)) {
        Copy-Item $env:SSL_CERT_FILE (Join-Path $certDir 'extra-ca.crt')
        Write-Step "Copied SSL_CERT_FILE into infra/certs/extra-ca.crt for Docker builds"
    }
}

function Get-ProfileArgs([string]$Name) {
    $names = if ($Name -eq 'all') { $AllProfiles } else { @($Name) }
    $result = @()
    foreach ($n in $names) { $result += @('--profile', $n) }
    return $result
}

function Invoke-Compose([string[]]$ComposeArgs) {
    $base = @('compose', '-f', $ComposeFile)
    if (Test-Path $EnvFile) { $base += @('--env-file', $EnvFile) }
    & docker @($base + $ComposeArgs)
    Assert-LastExit "docker compose $($ComposeArgs -join ' ')"
}

function Invoke-Uv([string[]]$UvArgs) {
    # uv rejects some corporate CA bundles named in SSL_CERT_FILE; use the OS store instead.
    $saved = $env:SSL_CERT_FILE
    try {
        if ($saved) { Remove-Item Env:SSL_CERT_FILE; $env:UV_NATIVE_TLS = '1' }
        & uv @UvArgs
        Assert-LastExit "uv $($UvArgs -join ' ')"
    }
    finally {
        if ($saved) { $env:SSL_CERT_FILE = $saved }
    }
}

function Invoke-Pnpm([string[]]$PnpmArgs) {
    & pnpm --dir (Join-Path $Root 'apps/web') @PnpmArgs
    Assert-LastExit "pnpm $($PnpmArgs -join ' ')"
}

function Invoke-Migrate {
    Write-Step 'Applying database migrations'
    Invoke-Compose @('exec', '-T', 'api', 'alembic', '-c', 'packages/core/alembic.ini', 'upgrade', 'head')
}

Push-Location $Root
try {
    switch ($Command) {
        'up' {
            & docker info --format '{{.ServerVersion}}' *> $null
            if ($LASTEXITCODE -ne 0) {
                throw 'Docker is not running. Start Docker Desktop (WSL2 backend) and try again.'
            }
            Initialize-EnvFile
            Initialize-ExtraCerts
            Write-Step "Starting profile '$StackProfile' (first build takes a few minutes)"
            Invoke-Compose ((Get-ProfileArgs $StackProfile) + @('up', '-d', '--build', '--wait'))
            if ($StackProfile -in @('core', 'all')) {
                Invoke-Migrate
                Write-Host ''
                Write-Host 'Web:    http://localhost:5180  (shows API health)'
                Write-Host 'API:    http://localhost:8700/health'
            }
            if ($StackProfile -in @('models', 'all')) { Write-Host 'LiteLLM: http://localhost:4000' }
            if ($StackProfile -in @('voice', 'all')) { Write-Host 'LiveKit: ws://localhost:7880' }
        }
        'down' {
            $downArgs = @('down', '--remove-orphans')
            if ($Volumes) { $downArgs += '--volumes' }
            Invoke-Compose ((Get-ProfileArgs 'all') + $downArgs)
        }
        'logs' {
            $logArgs = (Get-ProfileArgs 'all') + @('logs', '-f', '--tail', '200')
            if ($Service) { $logArgs += $Service }
            Invoke-Compose $logArgs
        }
        'ps' { Invoke-Compose ((Get-ProfileArgs 'all') + @('ps')) }
        'test' {
            $savedProfile = $env:MODEL_PROFILE
            try {
                $env:MODEL_PROFILE = 'fake'
                Write-Step 'Python tests (MODEL_PROFILE=fake)'
                Invoke-Uv @('run', 'pytest')
            }
            finally { $env:MODEL_PROFILE = $savedProfile }
            Write-Step 'Web tests'
            Invoke-Pnpm @('test')
        }
        'lint' {
            Write-Step 'ruff'
            Invoke-Uv @('run', 'ruff', 'check', '.')
            Invoke-Uv @('run', 'ruff', 'format', '--check', '.')
            Write-Step 'mypy'
            Invoke-Uv @('run', 'mypy')
            Write-Step 'JSON Schema freshness'
            Invoke-Uv @('run', 'python', '-m', 'strong_core.export_schemas', '--check')
            Write-Step 'Web lint and typecheck'
            Invoke-Pnpm @('lint')
            Invoke-Pnpm @('typecheck')
        }
        'migrate' { Invoke-Migrate }
        'seed' {
            Write-Step 'Seeding reference data'
            Invoke-Compose @('exec', '-T', 'api', 'python', '-m', 'strong_core.db.seed')
        }
        'schemas' {
            Write-Step 'Regenerating schemas/ from the Pydantic models'
            Invoke-Uv @('run', 'python', '-m', 'strong_core.export_schemas')
        }
        default { Get-Help $PSCommandPath -Detailed }
    }
}
finally {
    Pop-Location
}
