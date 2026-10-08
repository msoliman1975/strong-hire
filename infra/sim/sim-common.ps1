# Shared helpers for the sim scripts (P13). Dot-source it: . "$PSScriptRoot/sim-common.ps1"
# Works in Windows PowerShell 5.1 and PowerShell 7.

# 'Continue', not 'Stop': in Windows PowerShell 5.1 a native command (ssh, scp, git) that writes to
# stderr would otherwise stop the script. Native failures are checked with $LASTEXITCODE, and
# every cmdlet that must stop the script uses -ErrorAction Stop.
$ErrorActionPreference = 'Continue'

$script:SimMainHost = if ($env:STRONGHIRE_MAIN_HOST) { $env:STRONGHIRE_MAIN_HOST } else { '188.245.31.58' }
$script:SimServerType = 'cx33'          # 4 shared cores, 8 GB, nbg1 list price $0.016 per hour
$script:SimLocation = 'nbg1'            # same region as stronghire-test
$script:SimSshKeyName = 'stronghire-admin'
$script:SimFirewall = 'stronghire-sim-fw'
$script:SimLabel = 'stronghire-sim'
$script:SimRemoteDir = '/opt/sim'
$script:SshOpts = @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15')

function Get-UserSecret([string]$Name, [string]$Hint) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not $value) { $value = [Environment]::GetEnvironmentVariable($Name, 'User') }
    if (-not $value) { throw "Set the user environment variable $Name. $Hint" }
    return $value
}

function Get-HcloudToken([string]$TokenFile) {
    if ($TokenFile) { return (Get-Content -Raw $TokenFile).Trim() }
    return Get-UserSecret 'HCLOUD_TOKEN' 'It is the Hetzner Cloud API token of the StrongHire project.'
}

function Invoke-Hcloud([string]$Method, [string]$Path, $Body = $null) {
    $headers = @{ Authorization = "Bearer $script:HcloudToken" }
    $uri = "https://api.hetzner.cloud/v1$Path"
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -ErrorAction Stop -Method $Method -Uri $uri -Headers $headers -ContentType 'application/json' -Body $json
    }
    return Invoke-RestMethod -ErrorAction Stop -Method $Method -Uri $uri -Headers $headers
}

function Wait-HcloudAction($Action, [int]$TimeoutS = 900) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    while ($Action.status -eq 'running') {
        if ((Get-Date) -gt $deadline) { throw "Hetzner action $($Action.id) timed out" }
        Start-Sleep -Seconds 3
        $Action = (Invoke-Hcloud GET "/actions/$($Action.id)").action
    }
    if ($Action.status -ne 'success') { throw "Hetzner action $($Action.command) failed: $($Action.error.message)" }
}

function Get-SimFirewallId {
    # Inbound SSH only. The sim server makes outbound calls; nothing needs to reach it.
    $found = (Invoke-Hcloud GET "/firewalls?name=$script:SimFirewall").firewalls
    if ($found) { return $found[0].id }
    $body = @{
        name   = $script:SimFirewall
        labels = @{ $script:SimLabel = 'firewall' }
        rules  = @(@{ direction = 'in'; protocol = 'tcp'; port = '22'; source_ips = @('0.0.0.0/0', '::/0'); description = 'ssh' })
    }
    return (Invoke-Hcloud POST '/firewalls' $body).firewall.id
}

function New-SimServer([string]$Name, $Image, [string]$UserData = $null) {
    $body = @{
        name        = $Name
        server_type = $script:SimServerType
        location    = $script:SimLocation
        image       = $Image
        ssh_keys    = @($script:SimSshKeyName)
        firewalls   = @(@{ firewall = (Get-SimFirewallId) })
        labels      = @{ $script:SimLabel = 'server' }
        public_net  = @{ enable_ipv4 = $true; enable_ipv6 = $false }
    }
    if ($UserData) { $body.user_data = $UserData }
    $created = Invoke-Hcloud POST '/servers' $body
    Wait-HcloudAction $created.action
    $server = (Invoke-Hcloud GET "/servers/$($created.server.id)").server
    return $server
}

function Remove-SimServer($Server) {
    if (-not $Server) { return }
    try {
        $deleted = Invoke-Hcloud DELETE "/servers/$($Server.id)"
        Wait-HcloudAction $deleted.action 300
        Write-Host "Deleted sim server $($Server.name) (id $($Server.id))."
    } catch {
        Write-Warning "Could not delete sim server $($Server.name) (id $($Server.id)): $_. Delete it in the Hetzner console; it costs money while it exists."
    }
}

function Wait-Ssh([string]$Ip, [int]$TimeoutS = 300) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $deadline) {
        & ssh @script:SshOpts "root@$Ip" 'true' 2>$null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 5
    }
    throw "SSH to $Ip did not come up in $TimeoutS s"
}

function Invoke-Remote([string]$Ip, [string]$Command) {
    & ssh @script:SshOpts "root@$Ip" $Command
    if ($LASTEXITCODE -ne 0) { throw "Remote command failed ($LASTEXITCODE): $Command" }
}

function Send-RepoArchive([string]$Ip, [string]$RepoRoot) {
    # The committed code at HEAD, plus nothing from the working tree, so a run is reproducible.
    $tar = Join-Path ([IO.Path]::GetTempPath()) "strong-sim-$([guid]::NewGuid().ToString('N')).tar"
    try {
        & git -C $RepoRoot archive --format=tar -o $tar HEAD
        if ($LASTEXITCODE -ne 0) { throw 'git archive failed' }
        & scp @script:SshOpts $tar "root@${Ip}:$script:SimRemoteDir/code.tar"
        if ($LASTEXITCODE -ne 0) { throw 'scp of the code archive failed' }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tar
    }
    Invoke-Remote $Ip "rm -rf $script:SimRemoteDir/strong-hire && mkdir -p $script:SimRemoteDir/strong-hire && tar -xf $script:SimRemoteDir/code.tar -C $script:SimRemoteDir/strong-hire && rm $script:SimRemoteDir/code.tar"
}
