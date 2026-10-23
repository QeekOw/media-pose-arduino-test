# Run one Model variant on one Clip on the Board, e.g.
#   .\scripts\run-on-board.ps1 -Variant lite -Clip smoke.mp4
param(
    [Parameter(Mandatory)][ValidateSet("lite", "full", "heavy")][string]$Variant,
    [Parameter(Mandatory)][string]$Clip,
    [int]$Repeat = 1
)
. "$PSScriptRoot\board.ps1"

Invoke-Native ssh $BoardHost "cd ~/bench && PYTHONPATH=src ~/pose-venv/bin/python -m bench.run_one --variant $Variant --clip clips/$Clip --repeat $Repeat"
