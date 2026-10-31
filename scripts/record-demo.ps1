# Make one Demo recording on the Board, with a live preview on the Dev machine, then copy it to runs-demo\<id>\. Examples:
#   .\scripts\record-demo.ps1                 10 s of preview to get into frame, then 30 s recorded
#   .\scripts\record-demo.ps1 -NoPreview      no preview window
# A Demo recording is never a Session and never goes to Analysis (GLOSSARY.md). It refuses to start while a Campaign
# or a Run is running, because its extra work would distort that Run's numbers.
param(
    [double]$Seconds = 30,
    [double]$LeadIn = 10,
    [switch]$NoPreview
)
. "$PSScriptRoot\board.ps1"

& "$PSScriptRoot\push-to-board.ps1"
# The bracket keeps pgrep from matching its own command line.
$busy = ssh $BoardHost "pgrep -af 'python.*-m bench\.(campaig[n]|liv[e]|run_on[e]|demo_recor[d])' || true"
if ($LASTEXITCODE -ne 0) { throw "could not check the Board for running Runs" }
if ($busy) { throw "the Board is busy, so no Demo recording now:`n$busy" }

$record = "cd ~/bench && PYTHONPATH=src ~/pose-venv/bin/python -m bench.demo_record --seconds $Seconds --lead-in $LeadIn"
if ($NoPreview) {
    Invoke-Native ssh $BoardHost "$record --no-preview"
} else {
    # cmd's pipe carries the JPEG stream as bytes; the recorder's messages come through on stderr.
    cmd /c "ssh $BoardHost `"$record`" | ffplay -loglevel error -autoexit -fflags nobuffer -window_title `"Demo recording preview`" -f mjpeg -i -"
    if ($LASTEXITCODE -ne 0) { throw "the Demo recording or its preview failed" }
}

$latest = (ssh $BoardHost "ls -1d ~/bench/runs-demo/*/ | tail -n 1").Trim().TrimEnd("/")
$id = Split-Path $latest -Leaf
New-Item -ItemType Directory -Force "$RepoRoot\runs-demo" | Out-Null
Invoke-Native scp -r "${BoardHost}:$latest" "$RepoRoot\runs-demo\"
Write-Host "copied to runs-demo\$id"
