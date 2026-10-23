# Shared settings for the Board scripts. Override the target with $env:BOARD.
$BoardHost = if ($env:BOARD) { $env:BOARD } else { "arduino@pose-unoq.local" }
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ErrorActionPreference = "Stop"

function Invoke-Native {
    & $args[0] @($args | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { throw "failed: $($args -join ' ')" }
}
