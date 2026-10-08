<#
.SYNOPSIS
  Run an AI candidate suite against https://getstronghire.com on a short-lived sim server (P13).

.DESCRIPTION
  1. Shows the scenarios and the cost estimate, and asks before it starts (skip with -Yes).
  2. Creates a cx33 in nbg1 from the latest sim snapshot (sim-snapshot.ps1).
  3. Copies the committed code (git HEAD) and the secrets, and runs the suite.
     Each finished session is uploaded to stronghire-test:/srv/stronghire/sim/<run-id>/ at once.
  4. Copies the run folder to .\sim-runs\<run-id>\ on this machine.
  5. Deletes the server, also when the run fails. Prints the run time and the server cost.

  Secrets come from user environment variables: HCLOUD_TOKEN (or -TokenFile), GEMINI_KEY,
  ANTHROPIC_API_KEY and STRONGHIRE_SIM_TOKEN. The upload key is ~/.ssh/stronghire_simup.

.EXAMPLE
  ./infra/sim/sim-run.ps1 -Suite text-smoke
  ./infra/sim/sim-run.ps1 -Suite text-behaviors -Scenario tb-03,tb-07 -LimitUsd 2
#>
param(
    [Parameter(Mandatory = $true)][string]$Suite,
    [string[]]$Scenario,
    [double]$LimitUsd = 5,
    [switch]$Yes,
    [switch]$KeepServer,
    [string]$TokenFile,
    [string]$OutDir = (Join-Path (Get-Location) 'sim-runs')
)
. "$PSScriptRoot/sim-common.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path
$script:HcloudToken = Get-HcloudToken $TokenFile
$gemini = Get-UserSecret 'GEMINI_KEY' 'It is the Google Gemini API key for the candidate.'
$anthropic = Get-UserSecret 'ANTHROPIC_API_KEY' 'It is the Anthropic key for the judge.'
$simToken = Get-UserSecret 'STRONGHIRE_SIM_TOKEN' 'It must match SIM_TOKEN in the main server .env.'
$uploadKey = Join-Path $HOME '.ssh/stronghire_simup'
if (-not (Test-Path $uploadKey)) { throw "Missing $uploadKey (the upload key for user simup on the main server)." }

$scenarioArgs = @()
foreach ($s in ($Scenario | Where-Object { $_ })) { foreach ($id in $s.Split(',')) { $scenarioArgs += @('--scenario', $id.Trim()) } }

# 1. Plan and estimate, from the local checkout (no network, no models).
Push-Location $repo
try {
    $env:UV_NATIVE_TLS = '1'
    Remove-Item Env:SSL_CERT_FILE -ErrorAction SilentlyContinue
    & uv run --quiet --package strong-sim strong-sim plan --suite $Suite @scenarioArgs
    if ($LASTEXITCODE -ne 0) { throw 'strong-sim plan failed' }
} finally { Pop-Location }
Write-Host ("Sim server: {0} in {1}, `$0.016 per hour while it exists. Model cost stops at `${2:N2} on the sim side." -f $script:SimServerType, $script:SimLocation, $LimitUsd)
if (-not $Yes) {
    $answer = Read-Host 'Create the sim server and start the run? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Not started.'; return }
}

$snap = (Invoke-Hcloud GET "/images?type=snapshot&label_selector=$script:SimLabel%3Dsnapshot&sort=created:desc").images
if (-not $snap) { throw 'No sim snapshot. Run ./infra/sim/sim-snapshot.ps1 first.' }
$runId = "{0}-{1}-{2}" -f (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss'), $Suite, ([guid]::NewGuid().ToString('N').Substring(0, 4))
$started = Get-Date
$server = $null
try {
    Write-Host "Creating the sim server from snapshot $($snap[0].id)..."
    $server = New-SimServer "stronghire-sim-$($runId.Substring(0, 15).ToLower())" $snap[0].id
    $ip = $server.public_net.ipv4.ip
    Wait-Ssh $ip
    Send-RepoArchive $ip $repo

    # Secrets go in files copied with scp, never on a command line.
    $envFile = [IO.Path]::GetTempFileName()
    $master = 'sk-' + [guid]::NewGuid().ToString('N')
    @(
        "LITELLM_MASTER_KEY=$master",
        "GEMINI_API_KEY=$gemini",
        "ANTHROPIC_API_KEY=$anthropic",
        "SIM_TOKEN=$simToken",
        "SIM_UPLOAD_TARGET=simup@${script:SimMainHost}:",
        "SIM_COST_LIMIT_USD=$LimitUsd"
    ) | Set-Content -Encoding ascii $envFile
    try {
        & scp @script:SimSshOpts $envFile "root@${ip}:$script:SimRemoteDir/strong-hire/infra/sim/.env"
        & scp @script:SimSshOpts $uploadKey "root@${ip}:$script:SimRemoteDir/keys/upload_key"
        if ($LASTEXITCODE -ne 0) { throw 'copying secrets failed' }
    } finally { Remove-Item -Force $envFile }
    Invoke-Remote $ip "chmod 600 $script:SimRemoteDir/keys/upload_key $script:SimRemoteDir/strong-hire/infra/sim/.env"

    $compose = "cd $script:SimRemoteDir/strong-hire/infra/sim && docker compose -f compose.sim.yaml"
    Write-Host 'Building changed layers of the sim image...'
    Invoke-Remote $ip "$compose build -q sim"
    Write-Host "Running suite $Suite as run $runId..."
    $runArgs = @('run', '--suite', $Suite, '--yes', '--limit-usd', $LimitUsd, '--run-id', $runId) + $scenarioArgs
    & ssh @script:SimSshOpts "root@$ip" "$compose run --rm -T sim $($runArgs -join ' ')"
    $runExit = $LASTEXITCODE

    New-Item -ItemType Directory -Force $OutDir | Out-Null
    & scp @script:SimSshOpts -r "root@${ip}:$script:SimRemoteDir/runs/$runId" $OutDir
    if ($LASTEXITCODE -eq 0) { Write-Host "Copied the run to $(Join-Path $OutDir $runId)." }
    if ($runExit -ne 0) { Write-Warning "The run ended with exit code $runExit." }
} finally {
    if ($KeepServer -and $server) {
        Write-Warning "Keeping sim server $($server.name) at $($server.public_net.ipv4.ip). Delete it when done."
    } else {
        Remove-SimServer $server
    }
    $hours = [math]::Ceiling(((Get-Date) - $started).TotalHours)
    Write-Host ("Run time {0:N0} min. Sim server cost about `${1:N3} ({2} started hour(s) at `$0.016)." -f ((Get-Date) - $started).TotalMinutes, ($hours * 0.016), $hours)
}
Write-Host "Saved on the main server: /srv/stronghire/sim/$runId/ (list with ./infra/sim/sim-list.ps1)."
