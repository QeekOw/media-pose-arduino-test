"""The files a Demo recording leaves: the camera's raw JPEGs back to back, and a JSON Lines log of each frame.

    <dir>/frames.mjpeg   every JPEG the camera gave, as it gave it, not re-encoded
    <dir>/demo.jsonl     a header (phase "demo"), one live_frame line per frame with its offset and length in
                         frames.mjpeg, then a status line

A Demo recording is not a Run file and never goes to Analysis (see GLOSSARY.md). See docs/demo-videos.md.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from bench.runfile import LiveFrame, live_frame_record

DEMO = "demo"
FRAMES, LOG = "frames.mjpeg", "demo.jsonl"


class DemoRecordingWriter:
    """Writes one Demo recording. Frames are stored as read; their lines are written once the gate settles them."""

    def __init__(self, directory: Path, header: dict) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._frames = (directory / FRAMES).open("wb")
        self._log = (directory / LOG).open("w", encoding="utf-8")
        self._where: dict[int, tuple[int, int]] = {}
        self._write({"type": "header", **header, "phase": DEMO})

    def _write(self, obj: dict) -> None:
        self._log.write(json.dumps(obj) + "\n")
        self._log.flush()

    def add_jpeg(self, index: int, jpeg: bytes) -> None:
        self._where[index] = (self._frames.tell(), len(jpeg))
        self._frames.write(jpeg)

    def settle(self, frames: list[LiveFrame]) -> None:
        self._frames.flush()
        for f in frames:
            offset, length = self._where.pop(f.index)
            self._write({**live_frame_record(f), "offset": offset, "length": length})

    def finish(self, status: str, detail: str) -> None:
        self._write({"type": "status", "status": status, "detail": detail})

    def close(self) -> None:
        self._frames.close()
        self._log.close()

    def __enter__(self) -> "DemoRecordingWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class DemoRecording:
    directory: Path
    header: dict
    frames: list[LiveFrame]
    status: str | None
    where: dict[int, tuple[int, int]]

    def jpeg(self, index: int) -> bytes:
        offset, length = self.where[index]
        with (self.directory / FRAMES).open("rb") as f:
            f.seek(offset)
            return f.read(length)


def read_demo_recording(directory: Path) -> DemoRecording:
    header, frames, where, status = {}, [], {}, None
    lines = [line for line in (directory / LOG).read_text(encoding="utf-8").splitlines() if line.strip()]
    for n, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if n == len(lines):
                break  # cut off by a crash mid-write
            raise
        if record["type"] == "header":
            header = record
        elif record["type"] == "live_frame":
            frames.append(LiveFrame(
                record["index"], record["capture_ms"], record["read_ms"], record["result_ms"], record["landmarks"]
            ))
            where[record["index"]] = (record["offset"], record["length"])
        elif record["type"] == "status":
            status = record["status"]
    frames.sort(key=lambda f: f.index)
    return DemoRecording(directory, header, frames, status, where)
