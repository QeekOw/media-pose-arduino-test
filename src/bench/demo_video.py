"""Draw the Demo videos on the Dev machine: the pose skeleton over a Clip or over a Demo recording, as an MP4.

    python -m bench.demo_video video --run runs/board/video-20261031/video__lite__front__r1__board.jsonl
        --clip clips/front.mp4 --out report/demo/video-phase.mp4
    python -m bench.demo_video webcam --demo-recording runs-demo/<id> --out report/demo/webcam.mp4 --start 5

Each MP4 is H.264 at the source's size, written by ffmpeg, with a PNG still from its middle. See docs/demo-videos.md.
"""
import argparse
import subprocess
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from bench.analysis import summarize
from bench.demo_recording import read_demo_recording
from bench.runfile import LiveFrame, read_run

Landmarks = list[list[float]]
# MediaPipe's 33-landmark pose connections (mp.solutions.pose.POSE_CONNECTIONS), written out so drawing needs no
# MediaPipe import.
CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10), (11, 12), (11, 13), (13, 15), (15, 17),
    (15, 19), (15, 21), (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20), (11, 23), (12, 24),
    (23, 24), (23, 25), (24, 26), (25, 27), (26, 28), (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
)
MIN_VISIBILITY = 0.5
LENGTH_S = 15.0
WEBCAM_CAPTION = "Lite (as-is) on the Board | live from the Brio 105 | skeleton shown as it arrived"


def live_view(frames: list[LiveFrame]) -> list[Landmarks | None]:
    """For each frame, the landmarks of the latest result that had arrived by the time it was read.

    This is what someone watching live would have seen: the skeleton updates when a result comes back and trails the
    movement by the delay. A result with no pose clears the skeleton.
    """
    arrived = sorted((f.result_ms, f.index, f.landmarks) for f in frames if f.result_ms is not None)
    shown, latest, i = [], None, 0
    for f in sorted(frames, key=lambda f: f.index):
        while i < len(arrived) and arrived[i][0] <= f.read_ms:
            latest = arrived[i][2]
            i += 1
        shown.append(latest)
    return shown


FACE = range(11)  # nose, eyes, ears and mouth
FACE_REACH_MS = 500.0
Box = tuple[int, int, int, int]


def _face_box(landmarks: Landmarks, width: int, height: int) -> tuple[float, float, float, float]:
    """A square around the face landmarks, twice as wide as their larger span, in pixels."""
    xs = [landmarks[i][0] * width for i in FACE]
    ys = [landmarks[i][1] * height for i in FACE]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys))
    return cx - half, cy - half, cx + half, cy + half


def face_boxes(frames: list[LiveFrame], width: int, height: int) -> list[Box | None]:
    """For each frame, the box to blur over the face, or None to blur the whole frame.

    The face is placed where it was when the frame was captured, between the poses found on frames captured before
    and after it, so the blur keeps up with the face even though the skeleton trails it. With a pose on one side only
    within FACE_REACH_MS, that pose is used. With none, the whole frame is blurred, so a missed pose never shows a face.
    """
    poses = sorted((f.capture_ms, _face_box(f.landmarks, width, height)) for f in frames if f.landmarks is not None)
    boxes = []
    for f in sorted(frames, key=lambda f: f.index):
        t = f.capture_ms
        before = next((p for p in reversed(poses) if p[0] <= t and t - p[0] <= FACE_REACH_MS), None)
        after = next((p for p in poses if p[0] >= t and p[0] - t <= FACE_REACH_MS), None)
        if before and after and after[0] > before[0]:
            w = (t - before[0]) / (after[0] - before[0])
            box = tuple(b + (a - b) * w for b, a in zip(before[1], after[1]))
        elif before or after:
            box = (before or after)[1]
        else:
            boxes.append(None)
            continue
        x0, y0, x1, y1 = box
        boxes.append((max(0, round(x0)), max(0, round(y0)), min(width, round(x1)), min(height, round(y1))))
    return boxes


def window(times_ms: list[float], start_s: float, length_s: float) -> range:
    """The positions of the frames from start_s to start_s + length_s, counted from the first frame's time."""
    if not times_ms:
        return range(0)
    t0 = times_ms[0]
    inside = [i for i, t in enumerate(times_ms) if start_s * 1000 <= t - t0 < (start_s + length_s) * 1000]
    return range(inside[0], inside[-1] + 1) if inside else range(0)


def draw_skeleton(img: np.ndarray, landmarks: Landmarks | None) -> None:
    if landmarks is None:
        return
    h, w = img.shape[:2]
    points = [(round(x * w), round(y * h)) if v >= MIN_VISIBILITY else None for x, y, _, v in landmarks]
    thick = max(2, w // 320)
    for a, b in CONNECTIONS:
        if points[a] and points[b]:
            cv2.line(img, points[a], points[b], (255, 255, 255), thick + 2, cv2.LINE_AA)
            cv2.line(img, points[a], points[b], (0, 200, 0), thick, cv2.LINE_AA)
    for p in points:
        if p:
            cv2.circle(img, p, thick + 2, (0, 0, 255), -1, cv2.LINE_AA)


def blur(img: np.ndarray, box: Box | None) -> None:
    """Blur the box in place, or the whole frame when box is None."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box if box is not None else (0, 0, w, h)
    if x1 <= x0 or y1 <= y0:
        return
    region = img[y0:y1, x0:x1]
    k = max(31, (max(x1 - x0, y1 - y0) // 4) | 1)
    img[y0:y1, x0:x1] = cv2.GaussianBlur(region, (k, k), 0)


def draw_caption(img: np.ndarray, text: str) -> None:
    h, w = img.shape[:2]
    scale, thick = w / 1600, max(1, w // 640)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    pad = th // 2
    cv2.rectangle(img, (0, h - th - base - 2 * pad), (min(w, tw + 2 * pad), h), (0, 0, 0), -1)
    cv2.putText(img, text, (pad, h - base - pad), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)


def encode(frames: Iterator[np.ndarray], fps: float, out: Path, count: int) -> None:
    """Pipe BGR frames to ffmpeg for an H.264 MP4 that PowerPoint plays, and save the middle frame as a PNG."""
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = None
    for i, img in enumerate(frames):
        if proc is None:
            h, w = img.shape[:2]
            proc = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                 "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                 "-movflags", "+faststart", str(out)],
                stdin=subprocess.PIPE,
            )
        if i == count // 2:
            cv2.imwrite(str(out.with_suffix(".png")), img)
        proc.stdin.write(img.tobytes())
    if proc is None:
        raise SystemExit("no frames in the chosen window")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit(f"ffmpeg failed writing {out}")


def video_phase(run_path: Path, clip: Path, out: Path, start_s: float, length_s: float) -> None:
    """Each Clip frame with the landmarks the Board found on that same frame."""
    run = read_run(run_path)
    fps_board = summarize(run).fps
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS)
    keep = window([i * 1000 / fps for i in range(len(run.frames))], start_s, length_s)
    caption = (f"{run.header.variant.capitalize()} on the Board | every frame processed | "
               f"the Board ran at {fps_board:.1f} FPS, shown at the Clip's speed")

    def frames() -> Iterator[np.ndarray]:
        for i, f in enumerate(run.frames):
            ok, img = cap.read()
            if not ok:
                raise SystemExit(f"{clip} ended at frame {i}, but the Run file has {len(run.frames)}")
            if i in keep:
                draw_skeleton(img, f.landmarks)
                draw_caption(img, caption)
                yield img
            elif i >= keep.stop:
                return

    encode(frames(), fps, out, len(keep))
    cap.release()


def webcam(demo_recording: Path, out: Path, start_s: float, length_s: float) -> None:
    """The live view of a Demo recording, with the face blurred."""
    rec = read_demo_recording(demo_recording)
    size = rec.header["clip_info"]
    shown = live_view(rec.frames)
    boxes = face_boxes(rec.frames, size["width"], size["height"])
    keep = window([f.capture_ms for f in rec.frames], start_s, length_s)
    span_s = (rec.frames[keep.stop - 1].capture_ms - rec.frames[keep.start].capture_ms) / 1000 if keep else 0
    fps = (len(keep) - 1) / span_s if span_s > 0 else size["fps"]

    def frames() -> Iterator[np.ndarray]:
        for i in keep:
            img = cv2.imdecode(np.frombuffer(rec.jpeg(rec.frames[i].index), np.uint8), cv2.IMREAD_COLOR)
            blur(img, boxes[i])
            draw_skeleton(img, shown[i])
            draw_caption(img, WEBCAM_CAPTION)
            yield img

    encode(frames(), fps, out, len(keep))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="part", required=True)
    v = sub.add_parser("video", help="Part 1: a Video phase Run drawn over its Clip")
    v.add_argument("--run", type=Path, required=True)
    v.add_argument("--clip", type=Path, required=True)
    w = sub.add_parser("webcam", help="Part 2: a Demo recording in live view, face blurred")
    w.add_argument("--demo-recording", type=Path, required=True)
    for s in (v, w):
        s.add_argument("--out", type=Path, required=True)
        s.add_argument("--start", type=float, default=0.0, help="seconds from the first frame")
        s.add_argument("--length", type=float, default=LENGTH_S)
    a = p.parse_args()
    if a.part == "video":
        video_phase(a.run, a.clip, a.out, a.start, a.length)
    else:
        webcam(a.demo_recording, a.out, a.start, a.length)
    print(a.out)


if __name__ == "__main__":
    main()
