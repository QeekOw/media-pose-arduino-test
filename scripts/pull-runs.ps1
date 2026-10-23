# Copy every Run file from the Board into runs/board/.
. "$PSScriptRoot\board.ps1"

New-Item -ItemType Directory -Force "$RepoRoot\runs\board" | Out-Null
Invoke-Native scp "${BoardHost}:bench/runs/*.jsonl" "$RepoRoot\runs\board\"
