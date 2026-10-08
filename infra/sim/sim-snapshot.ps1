<#
.SYNOPSIS
  Build the sim server snapshot (P13): Ubuntu 24.04, Docker, and the sim, LiteLLM and Kokoro images.

.DESCRIPTION
  Creates a temporary cx33 in nbg1, installs Docker, copies the committed code (git HEAD), builds
  the images, powers off, saves a snapshot labelled stronghire-sim=snapshot, deletes older sim
  snapshots and deletes the server. Run it once, and again after the sim code or its
  dependencies change a lot (sim-run.ps1 rebuilds changed layers on each run anyway).
  Cost: the server for about 15 minutes (cx33, $0.016 per hour) and the snapshot (about $0.02 per
  GB per month).

.EXAMPLE
  ./infra/sim/sim-snapshot.ps1
#>
param(
    [string]$TokenFile
)
. "$PSScriptRoot/sim-common.ps1"
$script:HcloudToken = Get-HcloudToken $TokenFile
$repo = (Resolve-Path "$PSScriptRoot/../..").Path

$cloudInit = @'
#cloud-config
package_update: true
packages: [docker.io, docker-compose-v2, docker-buildx, rsync]
runcmd:
  - systemctl enable --now docker
  - mkdir -p /opt/sim/runs /opt/sim/keys
  - touch /var/lib/cloud/sim-ready
'@

$name = "stronghire-sim-build-$(Get-Date -Format 'yyyyMMdd-HHmm')"
Write-Host "Creating $name ($script:SimServerType, $script:SimLocation) from ubuntu-24.04..."
$server = New-SimServer $name 'ubuntu-24.04' $cloudInit
try {
    $ip = $server.public_net.ipv4.ip
    Wait-Ssh $ip
    Write-Host 'Waiting for cloud-init (Docker install)...'
    Invoke-Remote $ip 'cloud-init status --wait >/dev/null; test -f /var/lib/cloud/sim-ready'
    Send-RepoArchive $ip $repo
    Write-Host 'Building the sim image and pulling LiteLLM and Kokoro...'
    $compose = "cd $script:SimRemoteDir/strong-hire && SIM_TOKEN=x LITELLM_MASTER_KEY=x GEMINI_API_KEY=x ANTHROPIC_API_KEY=x docker compose -f infra/sim/compose.sim.yaml"
    Invoke-Remote $ip "$compose build sim && $compose pull litellm tts"
    Invoke-Remote $ip 'docker image ls --format "{{.Repository}}:{{.Tag}} {{.Size}}"'

    Write-Host 'Powering off and saving the snapshot...'
    Wait-HcloudAction (Invoke-Hcloud POST "/servers/$($server.id)/actions/shutdown").action 300
    $old = (Invoke-Hcloud GET "/images?type=snapshot&label_selector=$script:SimLabel%3Dsnapshot").images
    $body = @{ type = 'snapshot'; description = "stronghire sim $(Get-Date -Format 'yyyy-MM-dd HH:mm')"; labels = @{ $script:SimLabel = 'snapshot' } }
    $image = Invoke-Hcloud POST "/servers/$($server.id)/actions/create_image" $body
    Wait-HcloudAction $image.action 1800
    $img = (Invoke-Hcloud GET "/images/$($image.image.id)").image
    Write-Host ("Snapshot {0} saved: {1:N1} GB." -f $img.id, $img.image_size)
    foreach ($o in $old) {
        Invoke-Hcloud DELETE "/images/$($o.id)" | Out-Null
        Write-Host "Deleted the older snapshot $($o.id)."
    }
} finally {
    Remove-SimServer $server
}
