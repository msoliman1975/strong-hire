<#
.SYNOPSIS
  Model helpers: pull the local Ollama models, and smoke-test all six gateway roles.

.EXAMPLE
  ./scripts/models.ps1 pull                    # pull the Ollama models named in config/litellm.local.yaml
  ./scripts/models.ps1 smoke                   # all six roles with MODEL_PROFILE=local
  ./scripts/models.ps1 smoke -Profile hosted   # same test on hosted APIs; skips when keys are missing

.NOTES
  Model names live only in config/. This script reads them from there.
  smoke starts ollama (local only), litellm, stt and tts, then runs strong_core.gateway.smoke
  on the host against http://localhost:<LITELLM_PORT>/v1.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('pull', 'smoke', 'help')]
    [string]$Command = 'help',

    [Alias('Profile')]
    [ValidateSet('local', 'hosted')]
    [string]$ModelProfile = 'local'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/stack.ps1')

function Get-OllamaModels {
    # Entries in litellm.local.yaml whose api_base is the ollama service; the tag follows "<provider>/".
    $lines = Get-Content (Join-Path $Root 'config/litellm.local.yaml')
    $tags = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*model:\s*[^/\s]+/(\S+)\s*$') {
            $tag = $Matches[1]
            $next = ($lines[($i + 1)..([Math]::Min($i + 3, $lines.Count - 1))] -join "`n")
            if ($next -match 'api_base:\s*http://ollama:11434') { $tags += $tag }
        }
    }
    return $tags
}

Push-Location $Root
try {
    switch ($Command) {
        'pull' {
            Assert-Docker
            Initialize-EnvFile
            Invoke-Compose @('--profile', 'models', 'up', '-d', '--wait', 'ollama')
            foreach ($tag in Get-OllamaModels) {
                Write-Step "Pulling $tag"
                Invoke-Compose @('--profile', 'models', 'exec', '-T', 'ollama', 'ollama', 'pull', $tag)
            }
        }
        'smoke' {
            Assert-Docker
            Initialize-EnvFile
            Import-EnvFile
            $services = @('litellm', 'stt', 'tts')
            if ($ModelProfile -eq 'local') { $services = @('ollama') + $services }
            Start-ModelServices -ModelProfile $ModelProfile -Services $services
            $exit = Invoke-HostPython -ModelProfile $ModelProfile -PythonArgs @('-m', 'strong_core.gateway.smoke', '--profile', $ModelProfile)
            if ($exit -eq 2) { Write-Host "Skipped profile $ModelProfile (see the message above)."; exit 0 }
            if ($exit -ne 0) { throw "Smoke test failed for profile $ModelProfile" }
        }
        default { Get-Help $PSCommandPath -Detailed }
    }
}
finally {
    Pop-Location
}
