# Board setup

One-time setup of the Board's Python environment (ADR 0001, ADR 0005). A fresh tester can repeat it after a reflash. It needs no `sudo`. All commands run in PowerShell on the Dev machine from the repo root. The Board is `arduino@pose-unoq.local`; set `$env:BOARD` to use another address.

Prerequisite: SSH key login to the Board works (`ssh arduino@pose-unoq.local hostname` prints `pose-unoq` with no password prompt).

## Copy the code, then build the venv

```powershell
.\scripts\push-to-board.ps1
.\scripts\setup-board.ps1
```

`setup-board.ps1` installs `uv` into `~/.local/bin`, lets it download a standalone Python 3.12, deletes any existing `~/pose-venv`, creates it again, installs `requirements-board.txt`, and prints the Python and `mediapipe` versions it ends up with. The `uv` installer is pinned to the version in the script.

`requirements-board.txt` is generated from `uv.lock`, so every package, not just `mediapipe`, matches the Dev machine. After changing dependencies, regenerate it and commit both files:

```powershell
uv lock
uv export --no-dev --no-emit-project --no-hashes -o requirements-board.txt
```

Why Python 3.12 and `mediapipe` 0.10.18 rather than the system Python 3.13 and the current release: the current wheels crash on the Board's CPU. See ADR 0005. This also means the `python3-venv` system package and its `sudo` step are not needed.

If `mediapipe` fails to install or run, stop. Record the exact error on the ticket and flag it on #1.

## Everyday commands

| Task | Command |
| --- | --- |
| Copy code to the Board | `.\scripts\push-to-board.ps1` (add `-Clips` to copy `clips/` too) |
| Run one case on the Board | `.\scripts\run-on-board.ps1 -Variant lite -Clip smoke.mp4` |
| Copy Run files back | `.\scripts\pull-runs.ps1` (lands in `runs\board\`) |
| Analyse | `$env:PYTHONPATH="src"; uv run python -m bench.analysis runs\board` |

Never edit code on the Board. Edit on the Dev machine and push again.

Disk note: the Board's root filesystem has about 3.9 GB free, but `/home/arduino` is a separate 16 GB partition. Models, clips, Run files and the venv all live under `/home/arduino`.
