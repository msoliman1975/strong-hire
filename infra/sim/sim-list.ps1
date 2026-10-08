<#
.SYNOPSIS
  List AI candidate runs saved on the main server (P13): date, suite, sessions, pass count, size.
.EXAMPLE
  ./infra/sim/sim-list.ps1
#>
. "$PSScriptRoot/sim-common.ps1"
$py = @'
import json, os, subprocess
root = "/srv/stronghire/sim"
runs = sorted(os.listdir(root)) if os.path.isdir(root) else []
print(f"{'run id':<40} {'sessions':>8} {'errors':>6} {'all pass':>8} {'cost $':>7} {'size':>6}")
for run in runs:
    path = os.path.join(root, run, "report.json")
    try:
        s = json.load(open(path))["summary"]
    except Exception:
        s = {}
    size = subprocess.run(["du", "-sh", os.path.join(root, run)], capture_output=True, text=True).stdout.split("\t")[0]
    print(f"{run:<40} {s.get('sessions', '?'):>8} {s.get('sessions_error', '?'):>6} "
          f"{s.get('sessions_all_rules_pass', '?'):>8} {s.get('sim_cost_usd', 0):>7.2f} {size:>6}")
total = subprocess.run(["du", "-sh", root], capture_output=True, text=True).stdout.split("\t")[0] if runs else "0"
print(f"{len(runs)} runs, {total} in total (limit 10 GB, oldest deleted first).")
'@
$py | & ssh @script:SshOpts "root@$script:SimMainHost" 'python3 -'
