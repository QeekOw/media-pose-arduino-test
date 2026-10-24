import json
from dataclasses import dataclass, field, fields
from pathlib import Path


def run_file_name(variant: str, clip_stem: str, repeat: int, machine: str, phase: str = "video") -> str:
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


@dataclass(frozen=True)
class RunFile:
    path: Path
    header: Header | None
    frames: list[Frame]
    samples: list[Sample]
    status: str | None
    problem: str | None


def read_run(path: str | Path) -> RunFile:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    header = None
    frames: list[Frame] = []
    samples: list[Sample] = []
    status = None
    problem = None
    for pos, (number, line) in enumerate(lines):
        try:
            record = json.loads(line)
            kind = record.get("type")
            if kind == "header" and pos == 0:
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
                        landmarks=record.get("landmarks"),
                    )
                )
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
    return RunFile(path=path, header=header, frames=frames, samples=samples, status=status, problem=problem)
