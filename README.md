# MediaPipe pose on the Arduino UNO Q

Run Google's MediaPipe pose model on an Arduino UNO Q and watch it draw a skeleton on a person: in one of our videos, in a video you film on your phone, or live from a webcam.

You type commands on your laptop. The work happens on the UNO Q (we call it the **Board**), and the finished video opens on your laptop.

## What you need

- A **Windows or macOS laptop** on the same Wi-Fi as the Board
- Your Board's **name and password**, from the card on your table (for example `pose-07`)
- A **terminal**: on Windows open **PowerShell**, on macOS open **Terminal**

## Setup (once)

### Step 1: Install the tools

Windows:

```powershell
winget install Git.Git astral-sh.uv Gyan.FFmpeg
```

macOS (needs [Homebrew](https://brew.sh)):

```bash
brew install git uv ffmpeg
```

Then **close the terminal and open a new one**, so it finds the new tools.

### Step 2: Get the code

1. At the top of this page on GitHub, click **Fork**, then **Create fork**. You now have your own copy.
2. Copy it to your laptop. Replace `<your-user>` with your GitHub username:

   ```bash
   git clone https://github.com/<your-user>/media-pose-arduino-test.git
   cd media-pose-arduino-test
   uv sync
   ```

`uv sync` downloads Python and the packages it needs (a few hundred MB, a few minutes).

### Step 3: Connect to your Board

This lets your laptop log in to the Board without typing the password every time. Replace `pose-07` with your Board's name in all commands below.

Windows:

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh arduino@pose-07.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

macOS:

```bash
ssh-keygen -t ed25519
ssh-copy-id arduino@pose-07.local
```

- `ssh-keygen` asks three questions: press **Enter** for each. If it asks to overwrite an existing key, type **n**, you already have one.
- The second command asks for the **Board's password** once. If it asks `Are you sure you want to continue connecting?`, type **yes**.

Check it worked:

```bash
ssh arduino@pose-07.local hostname
```

It should print your Board's name (`pose-07`) **without** asking for a password.

### Step 4: Tell the commands which Board to use

Windows:

```powershell
$env:BOARD = "arduino@pose-07.local"
```

macOS:

```bash
export BOARD=arduino@pose-07.local
```

This lasts until you close the terminal. In a new terminal, run it again (or add `--board arduino@pose-07.local` to each command).

## Run it

Run these in the `media-pose-arduino-test` folder.

### On one of our videos

```bash
uv run python -m bench.workshop --video front
```

What happens: your laptop sends 10 s of the video to the Board, the Board finds the person's 33 body points in every frame (about 1 minute), and the video opens on your laptop with the skeleton drawn. The caption shows how many frames per second the Board managed.

There are two videos: `front` (a person standing) and `fast` (a person jumping on a trampoline).

### On your own video

1. Film yourself on your phone for about **10 seconds**, with your **whole body** in view and the phone held still.
2. Copy the video to your laptop (AirDrop, cable or a cloud drive).
3. Run it with the video's location:

   Windows:

   ```powershell
   uv run python -m bench.workshop --video "C:\Users\<you>\Downloads\IMG_1234.MOV"
   ```

   macOS:

   ```bash
   uv run python -m bench.workshop --video ~/Downloads/IMG_1234.MOV
   ```

**Tip:** type `uv run python -m bench.workshop --video ` (with a space at the end), then drag the video file from Explorer or Finder into the terminal. That pastes its location for you.

Any phone video works, upright or sideways.

### Compare the three models

MediaPipe comes in three sizes: **Lite** (the default), **Full** and **Heavy**. Bigger is more accurate but slower. Run the same video with each, then compare the speed in the caption and how steady the skeleton is:

```bash
uv run python -m bench.workshop --video fast --variant lite
uv run python -m bench.workshop --video fast --variant full
uv run python -m bench.workshop --video fast --variant heavy
```

| Model | Waiting time for 10 s of video |
| --- | --- |
| Lite | about 1 minute |
| Full | about 1.5 minutes |
| Heavy | about 4–5 minutes |

### Live from a webcam (only if your Board has one)

```bash
uv run python -m bench.workshop
```

1. A window opens showing the camera. You have **10 seconds** to step into view.
2. It records for **20 seconds**. Keep moving: wave, turn, step sideways. Don't close the window, it closes by itself.
3. About a minute later, the video opens with your skeleton drawn and your face blurred.

The webcam always uses Lite.

### Where are my videos?

In the `report/workshop/` folder, inside `media-pose-arduino-test`. For example `front-lite.mp4`, or `my-dance-full.mp4` for your own video with Full.

## Options

Add these to the end of a command:

| Option | What it does | Default |
| --- | --- | --- |
| `--video front` | Use one of our videos (`front` or `fast`) or your own (its location) | Webcam |
| `--variant full` | Model to use with a video: `lite`, `full` or `heavy` | `lite` |
| `--seconds 15` | How many seconds of the video to use, or how long to record from the webcam | 10 (video), 20 (webcam) |
| `--lead-in 15` | Webcam: seconds to step into view before recording | 10 |
| `--board arduino@pose-07.local` | Which Board, if you skipped step 4 | from step 4 |

## Something went wrong?

| You see | Do this |
| --- | --- |
| `Could not resolve hostname` | Check the Board's name and that your laptop is on the workshop Wi-Fi. |
| `Permission denied` | Redo step 3. |
| `missing on this laptop: ffmpeg` | Redo step 1, then open a new terminal. |
| `no video '...'` | Check the video's location. On Windows, keep the quotes around it. |
| `the Board is busy` | Someone else is using your Board. Wait a minute and try again. |
| `expected one camera ... found 0` | No webcam is plugged in. Use `--video` instead. |

Still stuck? Ask a helper. Organisers preparing the Boards: see [WORKSHOP.md](WORKSHOP.md).

## Why not Arduino App Lab?

App Lab is Arduino's usual way to run code on the UNO Q, but MediaPipe cannot run inside it. App Lab only runs Python 3.13, the MediaPipe version that works on the UNO Q's processor (0.10.18) only supports Python 3.12, and newer MediaPipe versions crash on this processor. Running over SSH from your laptop avoids all three problems.

## About this repo

This repo started as a study of how fast and how accurately the three MediaPipe pose models run on the UNO Q's processor, first on five recorded videos and then live from a webcam. The workshop reuses its code.

| Where | What |
| --- | --- |
| `src/bench/workshop.py` | The workshop command |
| `src/bench/` | The rest: the benchmark, analysis and drawing the skeleton videos |
| `scripts/` | PowerShell scripts used during the study to drive the Board |
| `docs/board-setup.md` | Setting up a Board's Python environment |
| `docs/adr/` | Why things are done this way (for example SSH instead of App Lab) |
| `GLOSSARY.md` | The project's terms |
