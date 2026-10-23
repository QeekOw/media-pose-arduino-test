# Copy the benchmark code to the Board. Pass -Clips to copy clips/ as well.
param([switch]$Clips)
. "$PSScriptRoot\board.ps1"

Invoke-Native ssh $BoardHost "mkdir -p ~/bench && rm -rf ~/bench/src"
Invoke-Native scp -r "$RepoRoot\src" "$RepoRoot\requirements-board.txt" "${BoardHost}:bench/"
if ($Clips) {
    Invoke-Native ssh $BoardHost "mkdir -p ~/bench/clips"
    Invoke-Native scp -r "$RepoRoot\clips\." "${BoardHost}:bench/clips/"
}
Invoke-Native ssh $BoardHost "find ~/bench/src -name __pycache__ -prune -exec rm -rf {} +"
