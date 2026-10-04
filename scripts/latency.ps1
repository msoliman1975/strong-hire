<#
.SYNOPSIS
  Voice latency spike: runs the simulated candidate against the voice agent with
  MODEL_PROFILE=local and MODEL_PROFILE=hosted, then prints p50 and p95 per step for both.

.EXAMPLE
  ./scripts/models.ps1 pull            # once, for the local profile
  ./scripts/latency.ps1                # 5 sessions (10 turns) per profile
  ./scripts/latency.ps1 -Sessions 10 -Profiles hosted

.NOTES
  Each session is a new room with the two-question spike interview. One warm-up session per
  profile runs first and is not counted. The voice agent writes one CSV row per turn to
  var/latency/<profile>.csv. The hosted profile is skipped when HOSTED_API_KEY is not set.
  Phase 1 gate: hosted p50 of end of speech to first audio out under 1000 ms.
#>
[CmdletBinding()]
param(
    [int]$Sessions = 5,
    [ValidateSet('local', 'hosted')]
    [string[]]$Profiles = @('local', 'hosted'),
    # Seconds the simulated candidate waits for each reply. Raise it on slow CPUs.
    [int]$ReplyTimeout = 60
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/stack.ps1')

Push-Location $Root
try {
    Assert-Docker
    Initialize-EnvFile
    Import-EnvFile
    $latencyDir = Join-Path $Root 'var/latency'
    New-Item -ItemType Directory -Force $latencyDir | Out-Null
    $csvs = @()

    foreach ($p in $Profiles) {
        if ($p -eq 'hosted' -and -not $env:HOSTED_API_KEY) {
            Write-Host "Skipping profile hosted: HOSTED_API_KEY is not set in .env" -ForegroundColor Yellow
            continue
        }
        $services = @('litellm', 'stt', 'tts', 'livekit', 'voice')
        if ($p -eq 'local') { $services = @('ollama') + $services }
        Start-ModelServices -ModelProfile $p -Services $services
        if ($p -eq 'local') {
            # Unload models left in memory by other runs (for example the smoke test), so only the
            # interviewer's model loads. Private-repo CI runners have 7.9 GB of RAM.
            Write-Step 'Restarting ollama to free memory'
            Invoke-Compose @('restart', 'ollama')
        }
        # The voice worker warms up its models at start; restart it so the warm-up is current.
        Write-Step 'Restarting the voice worker (it warms up its models before taking rooms)'
        Invoke-Compose @('restart', 'voice')
        Invoke-Compose (@('up', '-d', '--wait') + $services)

        $csv = Join-Path $latencyDir "$p.csv"
        Write-Step "Warm-up session for $p (not counted)"
        Remove-Item $csv -ErrorAction SilentlyContinue
        Invoke-Compose @('exec', '-T', 'voice', 'python', '-m', 'strong_voice.caller', '--sessions', '1', '--timeout', "$ReplyTimeout", '--warmup')

        Write-Step "Measuring $Sessions sessions for $p"
        Invoke-Compose @('exec', '-T', 'voice', 'python', '-m', 'strong_voice.caller', '--sessions', "$Sessions", '--timeout', "$ReplyTimeout")
        Start-Sleep -Seconds 3
        $csvs += $csv
    }

    if ($csvs.Count -eq 0) { throw 'No profile was measured.' }
    Write-Step 'Latency report (milliseconds)'
    $exit = Invoke-HostPython -ModelProfile 'fake' -PythonArgs (@('-m', 'strong_voice.latency', 'report') + $csvs)
    if ($exit -ne 0) { throw 'Latency report failed' }
}
finally {
    Pop-Location
}
