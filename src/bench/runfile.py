import json
from dataclasses import dataclass, field, fields
from pathlib import Path

LANDMARK_COUNT = 33
VIDEO, WEBCAM = "video", "webcam"
PHASES = (VIDEO, WEBCAM)
# The clip slot of a Webcam phase session, in the header and the file name.
LIVE = "live"


def run_file_name(variant: str, clip_stem: str, repeat: int, machine: str, phase: str = VIDEO) -> str:
    return f"{phase}__{variant}__{clip_stem}__r{repeat}__{machine}.jsonl"


@dataclass(frozen=True)
class Header:
    format_version: int
    phase: str
    variant: str
    clip: str
    repeat: int
    started_at: str
    machine: dict = field(default_factory=dict)
    software: dict = field(default_factory=dict)
    model: dict = field(default_factory=dict)
    clip_info: dict = field(default_factory=dict)
    sample_interval_s: float | None = None

    @property
    def machine_name(self) -> str:
        return self.machine.get("name", "")


@dataclass(frozen=True)
class Frame:
    index: int
    video_ms: float
    model_ms: float
    landmarks: list[list[float]] | None

    @property
    def frame_ms(self) -> float:
        return self.video_ms + self.model_ms


@dataclass(frozen=True)
class LiveFrame:
    """One camera frame in the Webcam phase. It was dropped when no result ever came back for it."""

    index: int
    capture_ms: float
    read_ms: float
    result_ms: float | None
    landmarks: list[list[float]] | None

    @property
    def dropped(self) -> bool:
        return self.result_ms is None

    @property
    def delay_ms(self) -> float | None:
        return None if self.result_ms is None else self.result_ms - self.capture_ms


def live_frame_record(frame: LiveFrame) -> dict:
    return {
        "type": "live_frame",
        "index": frame.index,
        "capture_ms": frame.capture_ms,
        "read_ms": frame.read_ms,
        "result_ms": frame.result_ms,
        "dropped": frame.dropped,
        "landmarks": frame.landmarks,
    }


@dataclass(frozen=True)
class Sample:
    t_ms: int
    cpu_pct: float | None
    ram_used_mb: int | None
    rss_mb: int | None
    rss_peak_mb: int | None
    temp_c: float | None
    cpu_mhz: int | None


READINGS = tuple(f.name for f in fields(Sample) if f.name != "t_ms")


def _sample(record: dict) -> Sample:
    # bool is an int subclass, so true/false would otherwise pass as readings.
    t_ms = record["t_ms"]
    if type(t_ms) is not int:
        raise TypeError(f"t_ms is not an integer: {t_ms!r}")
    readings = {name: record.get(name) for name in READINGS}
    for name, value in readings.items():
        if value is not None and type(value) not in (int, float):
            raise TypeError(f"{name} is not a number: {value!r}")
    return Sample(t_ms=t_ms, **readings)


def _landmarks(value: list | None) -> list[list[float]] | None:
    if value is None:
        return None
    if len(value) != LANDMARK_COUNT or any(
        len(point) != 4 or any(type(c) not in (int, float) for c in point) for point in value
    ):
        raise TypeError(f"landmarks are not {LANDMARK_COUNT} [x, y, z, visibility] entries")
    return value


def _number(record: dict, name: str) -> float:
    value = record[name]
    if type(value) not in (int, float):
        raise TypeError(f"{name} is not a number: {value!r}")
    return value


def _live_frame(record: dict) -> LiveFrame:
    index = record["index"]
    if type(index) is not int:
        raise TypeError(f"index is not an integer: {index!r}")
    result_ms = None if record["result_ms"] is None else _number(record, "result_ms")
    frame = LiveFrame(
        index=index,
        capture_ms=_number(record, "capture_ms"),
        read_ms=_number(record, "read_ms"),
        result_ms=result_ms,
        landmarks=_landmarks(record.get("landmarks")),
    )
    if record["dropped"] is not frame.dropped:
        raise TypeError(f"dropped is {record['dropped']!r} but result_ms is {result_ms!r}")
    if frame.dropped and frame.landmarks is not None:
        raise TypeError("a dropped frame has landmarks")
    if frame.delay_ms is not None and frame.delay_ms < 0:
        raise TypeError("result_ms is before capture_ms")
    return frame


def read_phase(path: str | Path) -> str | None:
    """The phase in the header, read from the first line alone. None when that line is not a header with a known phase."""
    with Path(path).open(encoding="utf-8", errors="replace") as f:
        first = next((line for line in f if line.strip()), "")
    try:
        record = json.loads(first)
    except json.JSONDecodeError:
        return None
    if isinstance(record, dict) and record.get("type") == "header" and record.get("phase") in PHASES:
        return record["phase"]
    return None


@dataclass(frozen=True)
class RunFile:
    path: Path
    header: Header | None
    frames: list[Frame]
    live_frames: list[LiveFrame]
    samples: list[Sample]
    status: str | None
    problem: str | None


def read_run(path: str | Path) -> RunFile:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    header = None
    frames: list[Frame] = []
    live_frames: list[LiveFrame] = []
    samples: list[Sample] = []
    status = None
    problem = None
    for pos, (number, line) in enumerate(lines):
        try:
            record = json.loads(line)
            kind = record.get("type")
            if kind == "header" and pos == 0:
                if record["phase"] not in PHASES:
                    raise TypeError(f"phase is not one of {PHASES}: {record['phase']!r}")
                header = Header(
                    format_version=record["format_version"],
                    phase=record["phase"],
                    variant=record["variant"],
                    clip=record["clip"],
                    repeat=record["repeat"],
                    started_at=record["started_at"],
                    machine=record.get("machine", {}),
                    software=record.get("software", {}),
                    model=record.get("model", {}),
                    clip_info=record.get("clip_info", {}),
                    sample_interval_s=record.get("sample_interval_s"),
                )
            elif kind == "frame":
                frames.append(
                    Frame(
                        index=record["index"],
                        video_ms=record["video_ms"],
                        model_ms=record["model_ms"],
                        landmarks=_landmarks(record.get("landmarks")),
                    )
                )
            elif kind == "live_frame":
                live_frames.append(_live_frame(record))
            elif kind == "sample":
                samples.append(_sample(record))
            elif kind == "status":
                status = record["status"]
        except json.JSONDecodeError:
            # A crash mid-write leaves a partial last line, which is not corruption.
            if pos != len(lines) - 1:
                problem = f"corrupt line {number}"
            break
        except (AttributeError, KeyError, TypeError):
            problem = f"corrupt line {number}"
            break
    if header is None and problem is None:
        problem = "no header line"
    return RunFile(
        path=path, header=header, frames=frames, live_frames=live_frames, samples=samples, status=status, problem=problem
    )
