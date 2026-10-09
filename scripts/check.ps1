<#
.SYNOPSIS
  Run the same checks as CI on this machine, and print a pass/fail summary.
  Use it when GitHub Actions cannot run (for example, no Actions minutes left).

.EXAMPLE
  ./scripts/check.ps1                     # python, migrations, web (with Playwright e2e)
  ./scripts/check.ps1 -SkipE2E            # without the Playwright browser tests
  ./scripts/check.ps1 -Docker             # also the Docker stack check (core profile)
  ./scripts/check.ps1 -Only python,web    # some jobs only
  ./scripts/check.ps1 -Report var/check.md  # also write the summary as Markdown for the PR

.NOTES
  Jobs, as in .github/workflows/ci.yml:
    python      ruff check, ruff format --check, mypy, pytest (MODEL_PROFILE=fake), schemas fresh
    migrations  on a new Postgres 16 container: upgrade, alembic check, downgrade base, upgrade,
                the Postgres-only tests, seed twice. The container is removed afterwards.
    web         pnpm install --frozen-lockfile, lint, typecheck, test, build, Playwright e2e
    docker      (only with -Docker) compose config, core stack up with --build, migrate, seed,
                /api/health through the web proxy. Separate project and ports, so a running
                stack is not touched.
  Like CI, the tests do not read your .env: every value from .env.example is set for them.
  The local-models and voice jobs are not here: they need model downloads and 10 to 30 minutes.
  Works in Windows PowerShell 5.1 and PowerShell 7.
#>
[CmdletBinding()]
param(
    [ValidateSet('python', 'migrations', 'web', 'docker')]
    [string[]]$Only,
    [switch]$Docker,
    [switch]$SkipE2E,
    [string]$Report
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Results = New-Object System.Collections.Generic.List[object]

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    # Native tools write progress to stderr. Windows PowerShell 5.1 would stop on it with
    # $ErrorActionPreference = 'Stop', so run with 'Continue' and check the exit code.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { "$_" } | Out-Host
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $saved }
    if ($code -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit code $code)" }
}

function Invoke-Quiet([string]$Exe, [string[]]$Arguments) {
    # For clean-up and polling: ignore output and errors; the caller checks $LASTEXITCODE.
    $ErrorActionPreference = 'SilentlyContinue'
    & $Exe @Arguments 2>&1 | Out-Null
}

function Invoke-Check([string]$Job, [string]$Name, [scriptblock]$Body) {
    Write-Step "$Job : $Name"
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $ok = $true
    $detail = ''
    try { & $Body }
    catch { $ok = $false; $detail = "$($_.Exception.Message)" }
    $watch.Stop()
    $Results.Add([pscustomobject]@{
            Job = $Job; Check = $Name; Result = $(if ($ok) { 'pass' } else { 'FAIL' })
            Seconds = [int]$watch.Elapsed.TotalSeconds; Detail = $detail
        })
    if (-not $ok) { Write-Host "    FAIL: $detail" -ForegroundColor Red }
}

function Use-CleanEnv([scriptblock]$Body, [hashtable]$Extra = @{}) {
    # Set every value from .env.example (as CI has no .env), plus $Extra, for $Body only.
    $saved = @{}
    $values = @{}
    foreach ($line in Get-Content (Join-Path $Root '.env.example')) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
    }
    foreach ($k in $Extra.Keys) { $values[$k] = $Extra[$k] }
    $values['UV_NATIVE_TLS'] = '1'
    foreach ($k in $values.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        [Environment]::SetEnvironmentVariable($k, $values[$k])
    }
    # uv cannot load some corporate CA files from SSL_CERT_FILE (see CLAUDE.md).
    $savedCert = $env:SSL_CERT_FILE
    if ($savedCert) { Remove-Item Env:SSL_CERT_FILE }
    try { & $Body }
    finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        if ($savedCert) { $env:SSL_CERT_FILE = $savedCert }
    }
}

$jobs = if ($Only) { $Only } else { @('python', 'migrations', 'web') }
if ($Docker -and -not ($jobs -contains 'docker')) { $jobs += 'docker' }

Push-Location $Root
$started = Get-Date
try {
    if ($jobs -contains 'python' -or $jobs -contains 'migrations') {
        Use-CleanEnv { Invoke-Check 'setup' 'uv sync --all-packages --frozen' { Invoke-Native 'uv' @('sync', '--all-packages', '--frozen') } }
    }

    if ($jobs -contains 'python') {
        Use-CleanEnv {
            Invoke-Check 'python' 'ruff check' { Invoke-Native 'uv' @('run', 'ruff', 'check', '.') }
            Invoke-Check 'python' 'ruff format --check' { Invoke-Native 'uv' @('run', 'ruff', 'format', '--check', '.') }
            Invoke-Check 'python' 'mypy' { Invoke-Native 'uv' @('run', 'mypy') }
            Invoke-Check 'python' 'pytest' { Invoke-Native 'uv' @('run', 'pytest', '-q') }
            Invoke-Check 'python' 'JSON Schemas are fresh' { Invoke-Native 'uv' @('run', 'python', '-m', 'strong_core.export_schemas', '--check') }
        } @{ MODEL_PROFILE = 'fake' }
    }

    if ($jobs -contains 'migrations') {
        $pgName = 'strong-hire-check-pg'
        $port = '55498'
        $url = "postgresql+psycopg://strong:strong@localhost:$port/strong"
        Invoke-Quiet 'docker' @('rm', '-f', $pgName)
        Invoke-Check 'migrations' 'start Postgres 16' {
            Invoke-Native 'docker' @('run', '-d', '--name', $pgName, '-e', 'POSTGRES_USER=strong', '-e', 'POSTGRES_PASSWORD=strong',
                '-e', 'POSTGRES_DB=strong', '-p', "${port}:5432", 'postgres:16-alpine')
            $ready = $false
            foreach ($i in 1..60) {
                Invoke-Quiet 'docker' @('exec', $pgName, 'pg_isready', '-U', 'strong')
                if ($LASTEXITCODE -eq 0) { $ready = $true; break }
                Start-Sleep -Seconds 1
            }
            if (-not $ready) { throw 'Postgres did not start in 60 seconds' }
            Start-Sleep -Seconds 2
        }
        try {
            Use-CleanEnv {
                $a = @('run', 'alembic', '-c', 'packages/core/alembic.ini')
                Invoke-Check 'migrations' 'upgrade, check, downgrade base, upgrade' {
                    Invoke-Native 'uv' ($a + @('upgrade', 'head'))
                    Invoke-Native 'uv' ($a + @('check'))
                    Invoke-Native 'uv' ($a + @('downgrade', 'base'))
                    Invoke-Native 'uv' ($a + @('upgrade', 'head'))
                }
                Invoke-Check 'migrations' 'Postgres-only tests' {
                    Invoke-Native 'uv' @('run', 'pytest', 'packages/core/tests/test_profiles.py', 'apps/api/tests/test_account.py', 'apps/api/tests/test_sessions_api.py', '-k', 'postgres', '-rs', '-q')
                }
                Invoke-Check 'migrations' 'seed is repeatable' {
                    Invoke-Native 'uv' @('run', 'python', '-m', 'strong_core.db.seed')
                    Invoke-Native 'uv' @('run', 'python', '-m', 'strong_core.db.seed')
                }
            } @{ MODEL_PROFILE = 'fake'; DATABASE_URL = $url; STRONG_TEST_POSTGRES_URL = $url }
        }
        finally { Invoke-Quiet 'docker' @('rm', '-f', $pgName) }
    }

    if ($jobs -contains 'web') {
        $savedNode = $env:NODE_OPTIONS
        $env:NODE_OPTIONS = '--use-system-ca'  # networks with TLS inspection
        Push-Location (Join-Path $Root 'apps/web')
        try {
            Invoke-Check 'web' 'pnpm install --frozen-lockfile' { Invoke-Native 'pnpm' @('install', '--frozen-lockfile') }
            Invoke-Check 'web' 'lint' { Invoke-Native 'pnpm' @('lint') }
            Invoke-Check 'web' 'typecheck' { Invoke-Native 'pnpm' @('typecheck') }
            Invoke-Check 'web' 'test' { Invoke-Native 'pnpm' @('test') }
            Invoke-Check 'web' 'build' { Invoke-Native 'pnpm' @('build') }
            if (-not $SkipE2E) {
                Invoke-Check 'web' 'Playwright e2e' {
                    Invoke-Native 'pnpm' @('exec', 'playwright', 'install', 'chromium-headless-shell')
                    Invoke-Native 'pnpm' @('test:e2e')
                }
            }
        }
        finally {
            Pop-Location
            $env:NODE_OPTIONS = $savedNode
        }
    }

    if ($jobs -contains 'docker') {
        # Own project name and ports, so a running strong-hire stack is not touched.
        $envFile = Join-Path $env:TEMP 'strong-hire-check.env'
        (Get-Content (Join-Path $Root '.env.example')) -replace '^WEB_PORT=.*', 'WEB_PORT=5181' `
            -replace '^API_PORT=.*', 'API_PORT=8701' -replace '^POSTGRES_PORT=.*', 'POSTGRES_PORT=55497' `
            -replace '^REDIS_PORT=.*', 'REDIS_PORT=56378' | Set-Content $envFile -Encoding ASCII
        $c = @('compose', '-p', 'strong-hire-check', '-f', 'infra/compose.yaml', '--env-file', $envFile, '--profile', 'core')
        try {
            Invoke-Check 'docker' 'all profiles parse' {
                Invoke-Native 'docker' @('compose', '-f', 'infra/compose.yaml', '--env-file', '.env.example', '--profile', 'core',
                    '--profile', 'models', '--profile', 'voice', 'config', '--quiet')
            }
            Invoke-Check 'docker' 'core profile up (build)' { Invoke-Native 'docker' ($c + @('up', '-d', '--build', '--wait')) }
            Invoke-Check 'docker' 'migrate and seed' {
                Invoke-Native 'docker' ($c + @('exec', '-T', 'api', 'alembic', '-c', 'packages/core/alembic.ini', 'upgrade', 'head'))
                Invoke-Native 'docker' ($c + @('exec', '-T', 'api', 'python', '-m', 'strong_core.db.seed'))
            }
            Invoke-Check 'docker' '/api/health through the web proxy' {
                $health = Invoke-RestMethod 'http://localhost:5181/api/health' -TimeoutSec 10
                if ($health.status -ne 'ok') { throw "health is $($health.status)" }
            }
        }
        finally {
            Invoke-Quiet 'docker' ($c + @('down', '-v'))
            Remove-Item $envFile -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}

$ErrorActionPreference = 'Continue'
$sha = (& git -C $Root rev-parse --short HEAD)
$branch = (& git -C $Root branch --show-current)
$failed = @($Results | Where-Object { $_.Result -ne 'pass' })
$minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
Write-Host ''
$Results | Format-Table Job, Check, Result, Seconds -AutoSize | Out-Host
$verdict = if ($failed.Count -eq 0) { 'All checks passed' } else { "$($failed.Count) check(s) failed" }
Write-Host "$verdict on $branch at $sha, in $minutes minutes." -ForegroundColor $(if ($failed.Count) { 'Red' } else { 'Green' })

if ($Report) {
    $lines = @("### Local checks (scripts/check.ps1)", '',
        "$verdict on ``$branch`` at ``$sha``, in $minutes minutes, on Windows ($($PSVersionTable.PSVersion)).", '',
        '| Job | Check | Result | Seconds |', '| --- | --- | --- | --- |')
    foreach ($r in $Results) { $lines += "| $($r.Job) | $($r.Check) | $($r.Result) | $($r.Seconds) |" }
    foreach ($r in $failed) { $lines += ''; $lines += "FAIL $($r.Job) / $($r.Check): $($r.Detail)" }
    $dir = Split-Path -Parent $Report
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    Set-Content -Path $Report -Value $lines -Encoding UTF8
    Write-Host "Report: $Report"
}
if ($failed.Count -gt 0) { exit 1 }
