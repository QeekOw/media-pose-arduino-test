# Run the Video phase on the Board unattended, then copy the results to runs\board\<id>\. Examples:
#   .\scripts\run-campaign.ps1                                                  every variant x all five Clips x 3 repeats
#   .\scripts\run-campaign.ps1 -Variants lite,full -Clips front,side -Repeats 2    a trial
#   .\scripts\run-campaign.ps1 -Attach 20261024T120000Z                         wait for and copy an already started campaign
# The campaign runs on the Board under nohup, so closing the laptop or losing SSH does not stop it.
param(
    [ValidateSet("lite", "full", "heavy")][string[]]$Variants = @("lite", "full", "heavy"),
    [string[]]$Clips = @("front", "side", "fast", "far", "empty"),
    [int]$Repeats = 3,
    [long]$Seed,
    [string]$Id = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"),
    [string]$Attach
)
. "$PSScriptRoot\board.ps1"

if ($Attach) { $Id = $Attach }
# These words end up in a shell command on the Board.
foreach ($word in @($Id) + $Clips) {
    if ($word -notmatch '^[A-Za-z0-9_.-]+$') { throw "unsafe name: $word" }
}
$localDir = "$RepoRoot\runs\board\$Id"
if (Test-Path $localDir) { throw "$localDir already exists; move it away to copy this campaign again" }

if (-not $Attach) {
    & "$PSScriptRoot\push-to-board.ps1" -Clips
    $campaignArgs = "--clips-dir clips --out-dir ~/bench/campaigns --campaign-id $Id --variants $($Variants -join ' ') --clips $($Clips -join ' ') --repeats $Repeats"
    if ($PSBoundParameters.ContainsKey("Seed")) { $campaignArgs += " --seed $Seed" }
    Invoke-Native ssh $BoardHost "mkdir -p ~/bench/campaigns && cd ~/bench && PYTHONPATH=src nohup ~/pose-venv/bin/python -m bench.campaign $campaignArgs > ~/bench/campaigns/$Id.out 2>&1 < /dev/null &"
    Write-Host "campaign $Id started on the Board (rerun with -Attach $Id if this window closes)"
}

# Prints "finished|running <done> <planned>" or "dead <done> <planned>" when the process is gone without finishing.
$statusScript = @'
f=~/bench/campaigns/__ID__/campaign.json
state=$(~/pose-venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); t=d["totals"]; print("finished" if d["finished_at"] else "running", t["done"], t["planned"])' "$f" 2>/dev/null || echo "running 0 0")
case "$state" in finished*) echo "$state"; exit 0;; esac
if ! command -v pgrep >/dev/null || pgrep -f 'bench.campaign .*--campaign-id __ID__( |$)' >/dev/null; then echo "$state"; else echo "dead ${state#* }"; fi
'@
$statusScript = $statusScript.Replace("__ID__", $Id).Replace("`r", "")

while ($true) {
    $state = $statusScript | ssh $BoardHost "bash -s"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$(Get-Date -Format T) Board unreachable, will retry"
    } else {
        $kind, $done, $planned = ([string]$state).Trim() -split " "
        Write-Host "$(Get-Date -Format T) ${kind}: $done of $planned Runs done"
        if ($kind -ne "running") { break }
    }
    Start-Sleep -Seconds 30
}

New-Item -ItemType Directory -Force "$RepoRoot\runs\board" | Out-Null
Invoke-Native scp -r "${BoardHost}:bench/campaigns/$Id" "$RepoRoot\runs\board\"
Invoke-Native scp "${BoardHost}:bench/campaigns/$Id.out" "$localDir\"
Write-Host "copied to $localDir"
if ($kind -eq "dead") { throw "the campaign process ended before finishing; see $localDir\$Id.out" }
