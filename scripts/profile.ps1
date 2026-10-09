<#
.SYNOPSIS
  Switch the model profile and restart the services that use it. Also shows the current profile
  and, for the claude profile, today's spend against the daily budget.

.EXAMPLE
  ./scripts/profile.ps1 status          # current profile, and claude spend today
  ./scripts/profile.ps1 hosted          # Groq (needs HOSTED_API_KEY in .env)
  ./scripts/profile.ps1 claude          # Anthropic for text, local speech (needs ANTHROPIC_API_KEY)
  ./scripts/profile.ps1 local           # Ollama in Docker, CPU
  ./scripts/profile.ps1 tiny            # one small model, CPU
  ./scripts/profile.ps1 fake            # recorded fixtures, no model
  ./scripts/profile.ps1 claude -Voice   # also (re)start the voice services

.NOTES
  The script edits MODEL_PROFILE and LITELLM_PROFILE in .env, then recreates api, worker, web and
  litellm so they read the new values, and applies database migrations. Works in Windows
  PowerShell 5.1 and PowerShell 7.

  claude profile: the Anthropic key is read from your environment (process, user or machine
  variable) and passed to LiteLLM only; it is never written to a file. The app gets a LiteLLM key
  in the LiteLLM team "strong-hire". Limits, from .env:
    CLAUDE_DAILY_BUDGET_USD    the key's budget per day (resets 00:00 UTC)
    CLAUDE_MONTHLY_BUDGET_USD  the team's budget per month (resets on the 1st, UTC)
    CLAUDE_RPM_LIMIT           requests per minute
  Once a budget is used, model calls fail until it resets. Set a monthly limit in the Anthropic
  Console as well: it is the hard limit.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('status', 'fake', 'tiny', 'local', 'hosted', 'claude')]
    [string]$Name,
    [switch]$Voice
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$AppKeyAlias = 'strong-hire-app'
$TeamAlias = 'strong-hire'

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

# ------------------------------------------------------------------ .env

function Get-EnvValues {
    $values = @{}
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
                $values[$Matches[1]] = $Matches[2].Trim().Trim('"')
            }
        }
    }
    return $values
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = @(Get-Content $EnvFile)
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$Key\s*=") { $lines[$i] = "$Key=$Value"; $found = $true }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    Set-Content -Path $EnvFile -Value $lines -Encoding ASCII
}

# ------------------------------------------------------------------ docker

function Invoke-Docker([string[]]$Arguments) {
    # Docker writes progress to stderr. Windows PowerShell 5.1 would stop on it with
    # $ErrorActionPreference = 'Stop', so check the exit code instead.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @Arguments 2>&1 | ForEach-Object { "$_" } | Out-Host
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $saved }
    if ($code -ne 0) { throw "docker $($Arguments -join ' ') failed (exit code $code)" }
}

function Get-ComposeArgs([string]$ModelProfile, [bool]$WithVoice) {
    $files = @('compose', '-f', (Join-Path $Root 'infra/compose.yaml'))
    if ($ModelProfile -eq 'claude') { $files += @('-f', (Join-Path $Root 'infra/compose.claude.yaml')) }
    if (Test-Server) { $files += @('-f', (Join-Path $Root 'infra/compose.server.yaml')) }
    $files += @('--env-file', $EnvFile, '--profile', 'core', '--profile', 'models')
    if ($WithVoice) { $files += @('--profile', 'voice') }
    return $files
}

# The test server (docs/hosting.md) sets STACK_TARGET=server in .env.
function Test-Server { return (Get-EnvValues)['STACK_TARGET'] -eq 'server' }

function Test-VoiceRunning {
    $names = & docker ps --format '{{.Names}}' 2>$null
    return [bool]($names | Where-Object { $_ -match 'strong-hire-voice-1' })
}

# ------------------------------------------------------------------ LiteLLM app key (claude)

function Invoke-LiteLLM([string]$Method, [string]$Path, $Body, [hashtable]$Env) {
    $port = if ($Env['LITELLM_PORT']) { $Env['LITELLM_PORT'] } else { '4000' }
    $master = if ($Env['LITELLM_MASTER_KEY']) { $Env['LITELLM_MASTER_KEY'] } else { 'sk-local-dev-only' }
    $params = @{
        Method  = $Method
        Uri     = "http://localhost:$port$Path"
        Headers = @{ Authorization = "Bearer $master" }
    }
    if ($null -ne $Body) {
        $params['Body'] = ($Body | ConvertTo-Json -Compress)
        $params['ContentType'] = 'application/json'
    }
    return Invoke-RestMethod @params
}

function Set-Team([hashtable]$Env) {
    $monthly = if ($Env['CLAUDE_MONTHLY_BUDGET_USD']) { [double]$Env['CLAUDE_MONTHLY_BUDGET_USD'] } else { 30.0 }
    $limits = @{ max_budget = $monthly; budget_duration = '30d' }
    $team = $Env['LITELLM_TEAM_ID']
    if ($team) {
        try {
            $null = Invoke-LiteLLM 'GET' "/team/info?team_id=$team" $null $Env
            $null = Invoke-LiteLLM 'POST' '/team/update' (@{ team_id = $team } + $limits) $Env
            Write-Step "Team budget updated: `$$monthly per month"
            return $team
        }
        catch { Write-Host 'The saved team is unknown to LiteLLM; creating a new one.' }
    }
    $created = Invoke-LiteLLM 'POST' '/team/new' (@{ team_alias = $TeamAlias } + $limits) $Env
    Set-EnvValue 'LITELLM_TEAM_ID' $created.team_id
    Write-Step "Team created: `$$monthly per month"
    return $created.team_id
}

function Set-AppKey([hashtable]$Env, [string]$Team) {
    $budget = if ($Env['CLAUDE_DAILY_BUDGET_USD']) { [double]$Env['CLAUDE_DAILY_BUDGET_USD'] } else { 5.0 }
    $rpm = if ($Env['CLAUDE_RPM_LIMIT']) { [int]$Env['CLAUDE_RPM_LIMIT'] } else { 60 }
    $limits = @{ max_budget = $budget; budget_duration = '1d'; rpm_limit = $rpm }
    $key = $Env['LITELLM_APP_KEY']
    if ($key) {
        try {
            $info = (Invoke-LiteLLM 'GET' "/key/info?key=$key" $null $Env).info
            if ($info.team_id -eq $Team) {
                $null = Invoke-LiteLLM 'POST' '/key/update' (@{ key = $key } + $limits) $Env
                Write-Step "App key updated: `$$budget per day, $rpm requests per minute"
                return $key
            }
            # A key from before the team existed: replace it, so the monthly budget applies.
            $null = Invoke-LiteLLM 'POST' '/key/delete' @{ keys = @($key) } $Env
        }
        catch { Write-Host 'The saved app key is unknown to LiteLLM; creating a new one.' }
    }
    $body = @{ key_alias = $AppKeyAlias; team_id = $Team } + $limits
    $created = Invoke-LiteLLM 'POST' '/key/generate' $body $Env
    Set-EnvValue 'LITELLM_APP_KEY' $created.key
    Write-Step "App key created: `$$budget per day, $rpm requests per minute"
    return $created.key
}

function Show-Spend([hashtable]$Env) {
    $key = $Env['LITELLM_APP_KEY']
    if (-not $key) { Write-Host 'No app key yet. Run: ./scripts/profile.ps1 claude'; return }
    try {
        $info = (Invoke-LiteLLM 'GET' "/key/info?key=$key" $null $Env).info
        $spend = [math]::Round([double]$info.spend, 4)
        Write-Host ("Claude spend today: `${0} of `${1} (resets {2}); limit {3} requests per minute" -f `
                $spend, $info.max_budget, $info.budget_reset_at, $info.rpm_limit)
        if ($info.team_id) {
            $team = (Invoke-LiteLLM 'GET' "/team/info?team_id=$($info.team_id)" $null $Env).team_info
            Write-Host ("Claude spend this month: `${0} of `${1} (resets {2})" -f `
                    [math]::Round([double]$team.spend, 4), $team.max_budget, $team.budget_reset_at)
        }
    }
    catch { Write-Host 'LiteLLM is not running, or it does not know the app key.' }
}

# ------------------------------------------------------------------ main

Push-Location $Root
try {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item (Join-Path $Root '.env.example') $EnvFile
        Write-Step 'Created .env from .env.example'
    }
    $env_ = Get-EnvValues

    if ($Name -eq 'status') {
        Write-Host "MODEL_PROFILE=$($env_['MODEL_PROFILE'])  LITELLM_PROFILE=$($env_['LITELLM_PROFILE'])"
        if ($env_['MODEL_PROFILE'] -eq 'claude') { Show-Spend $env_ }
        return
    }

    # Requirements before anything changes.
    if ($Name -eq 'hosted' -and -not $env_['HOSTED_API_KEY']) {
        throw 'The hosted profile needs HOSTED_API_KEY in .env.'
    }
    if ($Name -eq 'claude') {
        $anthropic = $env:ANTHROPIC_API_KEY
        if (-not $anthropic) { $anthropic = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User') }
        if (-not $anthropic) { $anthropic = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'Machine') }
        if (-not $anthropic) { throw 'The claude profile needs ANTHROPIC_API_KEY as an environment variable.' }
        $env:ANTHROPIC_API_KEY = $anthropic  # for docker compose in this process only
    }

    Write-Step "Switching to MODEL_PROFILE=$Name"
    Set-EnvValue 'MODEL_PROFILE' $Name
    Set-EnvValue 'LITELLM_PROFILE' $(if ($Name -eq 'fake') { 'local' } else { $Name })
    if ($Name -ne 'claude') { Set-EnvValue 'LITELLM_APP_KEY' '' }  # other profiles use the master key
    # Values from the shell would win over .env in docker compose; clear them for this process.
    Remove-Item Env:MODEL_PROFILE, Env:LITELLM_PROFILE, Env:LITELLM_APP_KEY -ErrorAction SilentlyContinue

    $withVoice = $Voice -or (Test-VoiceRunning)
    $compose = Get-ComposeArgs $Name $withVoice

    Invoke-Docker ($compose + @('up', '-d', '--wait', 'postgres', 'redis'))
    if ($Name -eq 'claude') {
        Write-Step 'Making sure LiteLLM has its own database (for spend tracking)'
        $user = if ($env_['POSTGRES_USER']) { $env_['POSTGRES_USER'] } else { 'strong' }
        $db = if ($env_['POSTGRES_DB']) { $env_['POSTGRES_DB'] } else { 'strong' }
        $exists = & docker exec strong-hire-postgres-1 psql -U $user -d $db -tAc "select 1 from pg_database where datname = 'litellm'" 2>$null
        if ("$exists".Trim() -ne '1') {
            Invoke-Docker @('exec', 'strong-hire-postgres-1', 'psql', '-U', $user, '-d', $db, '-c', 'create database litellm')
        }
    }

    $services = @()
    if ($Name -ne 'fake') { $services += 'litellm' }
    if ($Name -in @('tiny', 'local')) { $services += 'ollama' }
    if ($services.Count -gt 0) {
        Write-Step "Starting $($services -join ', ')"
        Invoke-Docker ($compose + @('up', '-d', '--wait', '--force-recreate') + $services)
    }
    if ($Name -eq 'claude') {
        $team = Set-Team (Get-EnvValues)
        $null = Set-AppKey (Get-EnvValues) $team
    }

    # On the test server Caddy serves the built web app in place of the Vite dev server.
    $app = @('api', 'worker', $(if (Test-Server) { 'caddy' } else { 'web' }))
    if ($withVoice) { $app += @('livekit', 'stt', 'tts', 'voice') }
    Write-Step "Rebuilding if needed and restarting $($app -join ', ')"
    # No --wait: the worker's health check can be slower than its limit (#17). Poll /health instead.
    Invoke-Docker ($compose + @('up', '-d', '--build', '--force-recreate') + $app)

    $port = if ($env_['API_PORT']) { $env_['API_PORT'] } else { '8700' }
    $health = $null
    foreach ($i in 1..90) {
        try { $health = Invoke-RestMethod "http://localhost:$port/health" -TimeoutSec 3; break }
        catch { Start-Sleep -Seconds 2 }
    }
    if ($null -eq $health) { throw "The API did not answer on port $port within 3 minutes." }
    # New code can bring new database migrations; apply them, as ./scripts/dev.ps1 up does.
    Write-Step 'Applying database migrations'
    Invoke-Docker ($compose + @('exec', '-T', 'api', 'alembic', '-c', 'packages/core/alembic.ini', 'upgrade', 'head'))
    Write-Step "API is up with model_profile=$($health.model_profile)"
    if ($Name -eq 'claude') { Show-Spend (Get-EnvValues) }
    if ($Name -in @('tiny', 'local')) {
        Write-Host 'Local models must be pulled once: ./scripts/models.ps1 pull (-Profile tiny).'
    }
}
finally {
    Pop-Location
}
