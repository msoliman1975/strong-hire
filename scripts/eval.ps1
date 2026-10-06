<#
.SYNOPSIS
  Runs an eval suite (evals/suites/<name>.yaml) and writes an HTML report to evals/reports/.

.EXAMPLE
  ./scripts/eval.ps1                                  # smoke suite, fake model, no Docker
  ./scripts/eval.ps1 -Suite full                      # everything, fake model
  ./scripts/eval.ps1 -Suite goldset -Profile local    # scorer calibration on local models
  ./scripts/eval.ps1 -Suite full -Profile local -Record -Gate

.NOTES
  -Profile fake needs no Docker and no model. It checks that the harness runs end to end.
  -Profile local starts the ollama and litellm containers (models profile) and calls them from
  the host. -Profile hosted starts litellm only and needs HOSTED_API_KEY in .env.
  -Record saves every model call as a fixture the fake model can replay.
  -Gate exits with code 1 when a metric fails its threshold (spec: 85% within one band).
  -NoStart skips starting containers, for when the models stack is already up.
#>
[CmdletBinding()]
param(
    [string]$Suite = 'smoke',
    [Alias('Profile')]
    [ValidateSet('fake', 'local', 'hosted')]
    [string]$ModelProfile = 'fake',
    [switch]$Record,
    [string]$RecordDir = '',
    [switch]$Gate,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/stack.ps1')

$runArgs = @('-m', 'strong_evals', 'run', '--suite', $Suite, '--profile', $ModelProfile)
if ($Record) { $runArgs += '--record' }
if ($RecordDir) { $runArgs += @('--record-dir', $RecordDir) }
if ($Gate) { $runArgs += '--gate' }

Push-Location $Root
try {
    if ($ModelProfile -ne 'fake') {
        Initialize-EnvFile
        Import-EnvFile
        if ($ModelProfile -eq 'hosted' -and -not $env:HOSTED_API_KEY) {
            throw 'The hosted profile needs HOSTED_API_KEY in .env.'
        }
        if (-not $NoStart) {
            Assert-Docker
            $services = if ($ModelProfile -eq 'local') { @('ollama', 'litellm') } else { @('litellm') }
            Start-ModelServices -ModelProfile $ModelProfile -Services $services
        }
    }
    Write-Step "Eval suite $Suite on profile $ModelProfile"
    $exit = Invoke-HostPython -ModelProfile $ModelProfile -PythonArgs $runArgs
    if ($exit -ne 0) { throw "Eval run failed (exit code $exit)" }
}
finally {
    Pop-Location
}
