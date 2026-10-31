# Make one Demo recording on the Board, with a live preview on the Dev machine, then copy it to runs-demo\<id>\. Examples:
#   .\scripts\record-demo.ps1                 10 s of preview to get into frame, then a 30 s Demo recording
#   .\scripts\record-demo.ps1 -NoPreview      no preview window
# A Demo recording is never a Session and never goes to Analysis (GLOSSARY.md). It refuses to start while a Campaign
# or a Run is running, because its extra work would distort that Run's numbers.
param(
    [double]$Seconds = 30,
    [double]$LeadIn = 10,
    [switch]$NoPreview
)
. "$PSScriptRoot\board.ps1"

# Checked before the code is copied, since copying replaces ~/bench/src under anything running from it. pgrep exits 1
# when nothing matches; anything above that means the check itself failed. The brackets keep pgrep from matching its
# own command line.
$busy = ssh $BoardHost "pgrep -af 'python.*-m bench\.(campaig[n]|liv[e]|run_on[e]|demo_recor[d])'; s=`$?; [ `$s -le 1 ] || exit `$s"
if ($LASTEXITCODE -ne 0) { throw "could not check the Board for running Runs" }
if ($busy) { throw "the Board is busy, so no Demo recording now:`n$busy" }

& "$PSScriptRoot\push-to-board.ps1"

$listing = "ls -1d ~/bench/runs-demo/*/ 2>/dev/null || true"
$before = @(ssh $BoardHost $listing)
$record = "cd ~/bench && PYTHONPATH=src ~/pose-venv/bin/python -m bench.demo_record --seconds $Seconds --lead-in $LeadIn"
if ($NoPreview) {
    Invoke-Native ssh $BoardHost "$record --no-preview"
} else {
    # cmd's pipe carries the JPEG stream as bytes; the recorder's messages come through on stderr. Its exit code is
    # ffplay's, so whether the Demo recording worked is read from its status line below.
    cmd /c "ssh $BoardHost `"$record`" | ffplay -loglevel error -autoexit -fflags nobuffer -window_title `"Demo recording preview`" -f mjpeg -i -"
}

$new = @(ssh $BoardHost $listing | Where-Object { $before -notcontains $_ })
if ($new.Count -ne 1) { throw "expected one new Demo recording on the Board, found $($new.Count)" }
$dir = $new[0].Trim().TrimEnd("/")
$status = ssh $BoardHost "tail -n 1 $dir/demo.jsonl"
if ($status -notmatch '"status": "completed"') { throw "the Demo recording in $dir did not complete: $status" }
New-Item -ItemType Directory -Force "$RepoRoot\runs-demo" | Out-Null
Invoke-Native scp -r "${BoardHost}:$dir" "$RepoRoot\runs-demo\"
Write-Host "copied to runs-demo\$(Split-Path $dir -Leaf)"
