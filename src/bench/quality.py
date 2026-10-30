"""Quality metrics over the landmarks of one Run: PCK@0.2, detection rate, false detections, jitter.

Landmarks are in the Run file's normalised x and y, so distances are taken in pixels (frame width and height)
and divided by torso length, the distance from the shoulder midpoint to the hip midpoint.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bench.runfile import LANDMARK_COUNT, Frame

SHOULDERS = (11, 12)
HIPS = (23, 24)
PCK_THRESHOLD = 0.2
EMPTY_CLIP = "empty"
JITTER_CLIP = "front"


@dataclass(frozen=True)
class Quality:
    pck: float | None
    detection_rate: float | None
    false_detection_rate: float | None
    jitter: float | None


def clip_stem(clip: str) -> str:
    return Path(clip).stem


def _pixels(frame: Frame, width: int, height: int) -> np.ndarray | None:
    if frame.landmarks is None:
        return None
    return np.array(frame.landmarks, dtype=float)[:, :2] * (width, height)


def torso_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(points[list(SHOULDERS)].mean(axis=0) - points[list(HIPS)].mean(axis=0)))


def pck(frames: list[Frame], reference: list[Frame], width: int, height: int) -> float | None:
    """Percent of landmarks within PCK_THRESHOLD torso lengths of the reference, over frames where both found a pose."""
    by_index = {f.index: f for f in reference}
    correct = total = 0
    for frame in frames:
        ref_frame = by_index.get(frame.index)
        if ref_frame is None:
            continue
        run_xy, ref_xy = _pixels(frame, width, height), _pixels(ref_frame, width, height)
        if run_xy is None or ref_xy is None:
            continue
        torso = torso_length(ref_xy)
        if torso == 0:
            continue
        correct += int((np.linalg.norm(run_xy - ref_xy, axis=1) <= PCK_THRESHOLD * torso).sum())
        total += LANDMARK_COUNT
    return 100.0 * correct / total if total else None


def detection_rate(frames: list[Frame]) -> float | None:
    """Percent of frames in which a pose was found."""
    if not frames:
        return None
    return 100.0 * sum(f.landmarks is not None for f in frames) / len(frames)


def jitter(frames: list[Frame], width: int, height: int) -> float | None:
    """Mean landmark movement between consecutive frames, in torso lengths."""
    moves = []
    for prev, cur in zip(frames, frames[1:]):
        if cur.index != prev.index + 1:
            continue
        a, b = _pixels(prev, width, height), _pixels(cur, width, height)
        if a is None or b is None:
            continue
        torso = torso_length(a)
        if torso == 0:
            continue
        moves.append(float(np.linalg.norm(b - a, axis=1).mean()) / torso)
    return float(np.mean(moves)) if moves else None


def measure(
    clip: str, frames: list[Frame], reference: list[Frame] | None, width: int | None, height: int | None
) -> Quality:
    """Quality of one Run's frames, which the caller has already trimmed of warm-up.

    Detection rate applies to Clips with a person and false detections to the empty-room Clip, so each is None on the other.
    PCK needs the reference frames and jitter needs the front-view Clip; both need the frame size.
    """
    empty = clip_stem(clip) == EMPTY_CLIP
    has_size = bool(width and height)
    rate = detection_rate(frames)
    return Quality(
        pck=pck(frames, reference, width, height) if reference is not None and has_size else None,
        detection_rate=None if empty else rate,
        false_detection_rate=rate if empty else None,
        jitter=jitter(frames, width, height) if clip_stem(clip) == JITTER_CLIP and has_size else None,
    )
