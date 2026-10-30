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
| Run the whole Video phase unattended | `.\scripts\run-campaign.ps1` (see Campaign below) |
| Analyse | `$env:PYTHONPATH="src"; uv run python -m bench.analysis runs\board` |
| Verdicts, summary table, charts | `$env:PYTHONPATH="src"; uv run python -m bench.report runs\board\<id> runs\dev` (images in `report\`) |

Never edit code on the Board. Edit on the Dev machine and push again.

## Campaign

A Campaign runs every Model variant on every Clip, three repeats each, in shuffled order, on the Board without supervision. It runs under `nohup` on the Board, so a closed laptop or a dropped SSH session does not stop it. At the start it measures the idle CPU temperature. Before every Run it waits until the Board is back within 2 degrees C of that baseline, for at most 10 minutes. On timeout it starts the Run anyway and records that. Each Run is its own process, so a crash, an out-of-memory kill or a hang ends only that Run and leaves a failed Run file.

A trial with 2 Clips, 2 Model variants and 2 repeats (8 Runs):

```powershell
.\scripts\run-campaign.ps1 -Variants lite,full -Clips front,side -Repeats 2
```

With no arguments the script runs the real thing: all three variants, all five Clips, 3 repeats. It copies the code and clips, starts the Campaign, checks every 30 s until it finishes, then copies `~/bench/campaigns/<id>/` to `runs\board\<id>\`. If the window closes, `.\scripts\run-campaign.ps1 -Attach <id>` waits for and copies the same Campaign. `<id>` is a UTC timestamp such as `20261024T120000Z`, printed when the Campaign starts. `-Seed` fixes the shuffle seed.

`runs\board\<id>\` holds one Run file per Run, `<id>.out` (what the Campaign printed) and `campaign.json`. The log records the seed, the baseline and target temperatures, and for every Run in order its cool-down (temperature before and at start, seconds waited, whether it timed out), duration, exit code and final status. The Board's Run files stay in `~/bench/campaigns/<id>/`.

Analyse one Campaign, or reproduce its order from the seed in `campaign.json` and the same variants, Clips and repeats:

```powershell
$env:PYTHONPATH="src"; uv run python -m bench.analysis runs\board\<id>
$env:PYTHONPATH="src"; uv run python -m bench.campaign --print-plan --variants lite full --clips front side --repeats 2 --seed <seed>
```

On the Dev machine the temperature cannot be read, so `python -m bench.campaign` there runs without cool-downs and says so in the log.

Disk note: the Board's root filesystem has about 3.9 GB free, but `/home/arduino` is a separate 16 GB partition. Models, clips, Run files and the venv all live under `/home/arduino`.
