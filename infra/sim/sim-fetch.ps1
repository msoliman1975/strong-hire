<#
.SYNOPSIS
  Copy one saved AI candidate run from the main server to this machine (P13).
.EXAMPLE
  ./infra/sim/sim-fetch.ps1 20261008-101500-text-smoke-ab12
#>
param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$OutDir = (Join-Path (Get-Location) 'sim-runs')
)
. "$PSScriptRoot/sim-common.ps1"
if ($RunId -notmatch '^[A-Za-z0-9._-]+$') { throw "Not a run id: $RunId" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
& scp @script:SshOpts -r "root@${script:SimMainHost}:/srv/stronghire/sim/$RunId" $OutDir
if ($LASTEXITCODE -ne 0) { throw "scp failed ($LASTEXITCODE)" }
Write-Host "Copied to $(Join-Path $OutDir $RunId). Open report.html there."
