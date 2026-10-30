# Run every Model variant on every Clip on the Dev machine: the Laptop baseline.
# Writes runs/dev/ and skips Runs that already completed, so a rerun resumes. Heavy's Runs are the Reference landmarks.
param(
    [int]$Repeats = 3
)
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ErrorActionPreference = "Stop"

$OutDir = "$RepoRoot\runs\dev"
$Clips = "front", "side", "fast", "far", "empty"

Push-Location $RepoRoot
try {
    foreach ($repeat in 1..$Repeats) {
        foreach ($variant in "lite", "full", "heavy") {
            foreach ($clip in $Clips) {
                $existing = "$OutDir\video__${variant}__${clip}__r${repeat}__dev.jsonl"
                if ((Test-Path $existing) -and (Select-String -Path $existing -Pattern '"status": "completed"' -Quiet)) { continue }
                uv run python -m bench.run_one --variant $variant --clip "clips/$clip.mp4" --repeat $repeat --machine dev --out-dir $OutDir
                if ($LASTEXITCODE -ne 0) { throw "failed: $variant $clip r$repeat" }
            }
        }
    }
}
finally {
    Pop-Location
}
