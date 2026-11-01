"""One command for a workshop attendee: run MediaPipe on the Board, then watch the skeleton on their laptop.

    uv run python -m bench.workshop --board arduino@pose-07.local --video front           # a provided video
    uv run python -m bench.workshop --board arduino@pose-07.local --video my-dance.mp4    # their own video
    uv run python -m bench.workshop --board arduino@pose-07.local                         # the webcam

Runs on Windows, macOS and Linux, from the repo root. It needs `ssh` and `scp` (built into all three) and FFmpeg
(`ffmpeg`, plus `ffplay` for the webcam's preview window). It first checks that no Campaign, Run or Demo recording is
running on the Board, before it changes anything there, then copies this repo's `src/` to the Board, so the Board
runs the attendee's own copy of the code.

With --video, the laptop converts the video (at most --seconds long, 1280x720 at most, 30 fps, H.264), the Board
runs the chosen Model variant on every frame (as a Video phase Run does), and the laptop draws the skeleton over the
video, with the Board's speed in the caption. Nothing here is measured for the study: the Run file goes to
`report/workshop/`, never to Analysis.

Without --video, the Board makes a Demo recording with MediaPipe Lite from the webcam, with an `ffplay` window to
get into frame, and the laptop draws it as a Demo video with the face blurred.

The Board must already have the venv from `scripts/setup-board.ps1` (see WORKSHOP.md).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from bench.demo_video import LENGTH_S, video_phase, webcam
from bench.models import VARIANTS

ROOT = Path(__file__).resolve().parents[2]
PROVIDED = ROOT / "workshop-clips"
OUT = ROOT / "report" / "workshop"
DEFAULT_BOARD = os.environ.get("BOARD", "arduino@pose-unoq.local")
BUSY = r"pgrep -af 'python.*-m bench\.(campaig[n]|liv[e]|run_on[e]|demo_recor[d])'; s=$?; [ $s -le 1 ] || exit $s"
LISTING = "ls -1d ~/bench/runs-demo/*/ 2>/dev/null || true"
# The first seconds of a Demo recording are skipped in the Demo video, as Session warm-up is (docs/demo-videos.md).
SKIP_S = 5.0
# Rough Board speed per Model variant, from the Video phase (slides), only to say how long to wait.
BOARD_FPS = {"lite": 5.5, "full": 3.8, "heavy": 1.2}
INSTALL_HINT = {
    "win32": "winget install Gyan.FFmpeg",
    "darwin": "brew install ffmpeg",
}


def say(text: str) -> None:
    print(f"[workshop] {text}", flush=True)


def ssh(board: str, command: str) -> str:
    """Runs command on the Board and returns its output. Exits with the Board's message if it fails."""
    done = subprocess.run(["ssh", board, command], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"on the Board, `{command}` failed:\n{done.stderr.strip()}")
    return done.stdout


def scp(*args: str) -> None:
    if subprocess.run(["scp", "-q", "-r", *args]).returncode != 0:
        raise SystemExit(f"copying failed: scp {' '.join(args)}")


def provided_videos() -> list[str]:
    return sorted(p.stem for p in PROVIDED.glob("*.mp4"))


def find_video(choice: str) -> Path:
    """A provided video by name (`front`), or a video file on this laptop."""
    if (PROVIDED / f"{choice}.mp4").is_file():
        return PROVIDED / f"{choice}.mp4"
    path = Path(choice).expanduser()
    if path.is_file():
        return path
    raise SystemExit(f"no video '{choice}': give the path of a video file, or one of: {', '.join(provided_videos())}")


def safe_name(path: Path) -> str:
    """The file's name reduced to letters, digits and dashes, so it is safe in a path on the Board."""
    return re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower() or "video"


def new_demo_recording(before: list[str], after: list[str]) -> str:
    """The one folder in after that was not in before, without the trailing slash."""
    new = [d.strip() for d in after if d.strip() and d not in before]
    if len(new) != 1:
        raise SystemExit(f"expected one new Demo recording on the Board, found {len(new)}")
    return new[0].rstrip("/")


def open_file(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)


def check_tools(needed: list[str]) -> None:
    missing = [t for t in needed if shutil.which(t) is None]
    if missing:
        hint = INSTALL_HINT.get(sys.platform, "install FFmpeg with your package manager")
        raise SystemExit(f"missing on this laptop: {', '.join(missing)}. FFmpeg provides ffmpeg and ffplay: {hint}")


def convert(source: Path, out: Path, seconds: float) -> None:
    """Fits the video in 1280x720 without cropping (a phone's portrait video keeps the whole person), at 30 fps."""
    done = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-t", f"{seconds:g}", "-an",
         "-vf", "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out)],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"could not convert {source}: {done.stderr.strip()}")


def prepare_board(board: str) -> None:
    say(f"checking that {board} is free")
    busy = ssh(board, BUSY).strip()
    if busy:
        raise SystemExit(f"the Board is busy, so not now:\n{busy}")
    say("copying your code to the Board")
    ssh(board, "mkdir -p ~/bench && rm -rf ~/bench/src")
    scp(str(ROOT / "src"), str(ROOT / "requirements-board.txt"), f"{board}:bench/")
    ssh(board, "find ~/bench/src -name __pycache__ -prune -exec rm -rf {} +")


def run_video(board: str, choice: str, variant: str, seconds: float) -> Path:
    source = find_video(choice)
    name = safe_name(source)
    OUT.mkdir(parents=True, exist_ok=True)
    clip = OUT / f"{name}.mp4"
    say(f"converting {source.name} (first {seconds:g} s)")
    convert(source, clip, seconds)

    prepare_board(board)
    ssh(board, "mkdir -p ~/bench/workshop-clips")
    scp(str(clip), f"{board}:bench/workshop-clips/")
    wait_s = seconds * 30 / BOARD_FPS[variant]
    say(f"running {variant.capitalize()} on every frame on the Board: about {max(1, round(wait_s / 60))} min, "
        "please wait")
    done = subprocess.run(
        ["ssh", board, f"cd ~/bench && PYTHONPATH=src ~/pose-venv/bin/python -m bench.run_one --variant {variant} "
                       f"--clip workshop-clips/{name}.mp4 --out-dir workshop-runs"],
        stdout=subprocess.PIPE, text=True)
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        raise SystemExit(f"the Run failed on the Board (exit {done.returncode}); its messages are above")
    remote = lines[-1].strip()
    status = ssh(board, f"tail -n 1 ~/bench/{remote}")
    if '"status": "completed"' not in status:
        raise SystemExit(f"the Run on the Board did not complete: {status.strip()}")
    say("copying the results back")
    scp(f"{board}:bench/{remote}", str(OUT))

    out = OUT / f"{name}-{variant}.mp4"
    say("drawing the skeleton")
    video_phase(OUT / Path(remote).name, clip, out, 0.0, seconds)
    return out


def record(board: str, seconds: float, lead_in: float, preview: bool) -> str:
    """Makes the Demo recording on the Board and returns its folder there."""
    command = (f"cd ~/bench && PYTHONPATH=src ~/pose-venv/bin/python -m bench.demo_record "
               f"--seconds {seconds:g} --lead-in {lead_in:g}" + ("" if preview else " --no-preview"))
    before = ssh(board, LISTING).splitlines()
    if preview:
        remote = subprocess.Popen(["ssh", board, command], stdout=subprocess.PIPE)
        window = subprocess.Popen(["ffplay", "-loglevel", "error", "-autoexit", "-fflags", "nobuffer",
                                   "-window_title", "Demo recording preview", "-f", "mjpeg", "-i", "-"],
                                  stdin=remote.stdout)
        remote.stdout.close()
        code = remote.wait()
        window.wait()
    else:
        code = subprocess.run(["ssh", board, command]).returncode
    if code != 0:
        raise SystemExit(f"the Demo recording failed on the Board (exit {code}); its messages are above")
    folder = new_demo_recording(before, ssh(board, LISTING).splitlines())
    status = ssh(board, f"tail -n 1 {folder}/demo.jsonl")
    if '"status": "completed"' not in status:
        raise SystemExit(f"the Demo recording in {folder} did not complete: {status.strip()}")
    return folder


def run_webcam(board: str, seconds: float, lead_in: float, preview: bool) -> Path:
    prepare_board(board)
    say(f"starting the camera: {lead_in:g} s to get into frame, then {seconds:g} s of Demo recording. Keep moving!")
    folder = record(board, seconds, lead_in, preview)
    name = folder.rsplit("/", 1)[-1]
    local = ROOT / "runs-demo"
    local.mkdir(exist_ok=True)
    say("copying the Demo recording back")
    scp(f"{board}:{folder}", str(local))
    out = OUT / f"webcam-{name}.mp4"
    OUT.mkdir(parents=True, exist_ok=True)
    say("drawing your skeleton (this takes a minute)")
    webcam(local / name, out, SKIP_S, min(LENGTH_S, max(seconds - SKIP_S, 1.0)))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Run MediaPipe on the Board and watch the skeleton on your laptop.")
    p.add_argument("--board", default=DEFAULT_BOARD, help="user@address of your Board (or set BOARD)")
    p.add_argument("--video", help=f"a provided video ({', '.join(provided_videos())}) or the path of your own; "
                                   "leave out to use the webcam")
    p.add_argument("--variant", choices=VARIANTS, default="lite",
                   help="Model variant for --video (the webcam always uses Lite)")
    p.add_argument("--seconds", type=float, help="how much video to use (default 10), or the Demo recording's "
                                                 "length with the webcam (default 20)")
    p.add_argument("--lead-in", type=float, default=10.0, help="webcam: seconds of preview to get into frame first")
    p.add_argument("--no-preview", action="store_true", help="webcam: no camera window")
    a = p.parse_args()

    if a.video:
        check_tools(["ssh", "scp", "ffmpeg"])
        out = run_video(a.board, a.video, a.variant, a.seconds or 10.0)
    else:
        if a.variant != "lite":
            raise SystemExit("the webcam always uses Lite; use --variant with --video")
        check_tools(["ssh", "scp", "ffmpeg"] + ([] if a.no_preview else ["ffplay"]))
        out = run_webcam(a.board, a.seconds or 20.0, a.lead_in, not a.no_preview)
    say(f"done: {out}")
    open_file(out)


if __name__ == "__main__":
    main()
