# Workshop: organiser guide

How to prepare the Boards, run the session and clean up afterwards. Attendees follow the [README](README.md); this page is for the people running the workshop.

Attendees run MediaPipe on a Board from their own laptop over SSH, with `uv run python -m bench.workshop`: on one of the two videos in `workshop-clips/`, on a video they filmed, or live from a webcam. Nothing they do is measured for the study.

## Before the session

Prepare every Board the day before. Installing in the room, with every Board on one Wi-Fi, takes too long.

### For each Board

1. **Power.** For videos only, the UNO Q's own power supply is enough. For a webcam, use a USB-C hub with Power Delivery (5 V, 3 A) into the UNO Q, with the power supply and the webcam plugged into the hub. Without PD the Board does not boot. Any USB (UVC) webcam works: the Logitech Brio 105 is used exactly as in the Webcam phase, others in whatever mode they offer.
2. **Network and name.** Connect the Board to the venue Wi-Fi and give it a unique name:

   ```bash
   sudo hostnamectl set-hostname pose-07
   ```

   Check from a laptop that `ssh arduino@pose-07.local hostname` answers. If `.local` names do not work on the venue network, note each Board's IP address instead.
3. **Python environment.** From a Windows Dev machine with this repo (see `docs/board-setup.md`):

   ```powershell
   $env:BOARD = "arduino@pose-07.local"
   .\scripts\push-to-board.ps1
   .\scripts\setup-board.ps1
   ```

   It ends by printing `python 3.12.x mediapipe 0.10.18`.
4. **Models.** Run each Model variant once, so the Board downloads all three (Heavy is about 30 MB) before the session:

   ```bash
   uv run python -m bench.workshop --video front --seconds 2 --variant lite
   uv run python -m bench.workshop --video front --seconds 2 --variant full
   uv run python -m bench.workshop --video front --seconds 2 --variant heavy
   ```

5. **Webcam test** (if the Board has one): `uv run python -m bench.workshop`, step into view, and check the video at the end.
6. **Clean up your tests** on the Board:

   ```bash
   rm -r ~/bench/runs-demo ~/bench/workshop-clips ~/bench/workshop-runs
   ```

### For each table

A card with the Board's name (`pose-07`), the user (`arduino`) and its password.

### Tell attendees in advance

Ask them to do README steps 1 and 2 (install the tools, fork and clone, `uv sync`) before the session. Together they download a few hundred MB, which is slow on a shared Wi-Fi.

## During the session

| Problem | Fix |
| --- | --- |
| `winget` or `brew` not found | Windows: update "App Installer" from the Microsoft Store. macOS: install Homebrew from brew.sh first. |
| A tool still "not found" after installing | Close the terminal and open a new one. |
| `uv sync` is very slow | The Wi-Fi is busy. Let it run, and start with the next step on a neighbour's laptop. |
| `Could not resolve hostname pose-07.local` | Wrong Board name, laptop on another Wi-Fi, or `.local` names blocked: use the Board's IP address (`arduino@192.168.x.y`). |
| `Permission denied` | The key was not added. Redo README step 3, typing the Board's password when asked. |
| Every command still asks for the password | Same as above. On Windows, check that `ssh-keygen` made `id_ed25519.pub` in `%USERPROFILE%\.ssh`. |
| `the Board is busy` | Two attendees share a Board. One waits until the other's command finishes. |
| `expected one camera ... found 0` | The webcam is not in the hub, or the hub has no power. Replug, or use `--video`. |
| `No such file or directory: .../pose-venv/bin/python` | The Board was not prepared: run step 3 of "For each Board". |
| Heavy takes very long | Expected: about 4–5 minutes for 10 s of video. Start it, then keep talking. |

## After the session

On every Board, delete everything attendees left there, and their keys:

```bash
rm -r ~/bench/runs-demo ~/bench/workshop-clips ~/bench/workshop-runs
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
nano ~/.ssh/authorized_keys     # keep only your own key(s)
```

The Demo recordings in `~/bench/runs-demo` contain attendees' faces unblurred, so do not skip this.
