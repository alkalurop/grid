"""Run grid-analyse and read the beat list it prints.

grid-analyse is the small binding over rbl-analysis. This module does not
decode audio and does not write a library.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AnalyzeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Beat:
    n: int
    ms: int
    bpm: float


@dataclass(frozen=True)
class Grid:
    bpm: float
    beats: tuple[Beat, ...]


def engine_path() -> Path:
    """Release binary next to this package, else `grid-analyse` on PATH."""
    built = Path(__file__).resolve().parents[1] / "engine" / "target" / "release" / "grid-analyse"
    if built.is_file():
        return built
    found = shutil.which("grid-analyse")
    if found:
        return Path(found)
    raise AnalyzeError(
        "grid-analyse is not built. From the grid repo:\n"
        "  cargo build --release --manifest-path beatgrid/engine/Cargo.toml\n"
        "Rust 1.89 or newer. That binary calls rbl-analysis; this command only reads its JSON."
    )


def parse_grid(payload: str) -> Grid:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AnalyzeError(f"grid-analyse did not print JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalyzeError("grid-analyse JSON must be an object")
    try:
        bpm = float(data["bpm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalyzeError("grid-analyse JSON is missing bpm") from exc
    raw_beats = data.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise AnalyzeError("grid-analyse returned no beats")
    beats: list[Beat] = []
    for item in raw_beats:
        if not isinstance(item, dict):
            raise AnalyzeError("a beat must be an object")
        try:
            number = int(item["n"])
            ms = int(item["ms"])
            beat_bpm = float(item["bpm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalyzeError("a beat is missing n, ms, or bpm") from exc
        if number < 1 or number > 4 or ms < 0 or beat_bpm <= 0:
            raise AnalyzeError(f"beat out of range: n={number} ms={ms} bpm={beat_bpm}")
        beats.append(Beat(n=number, ms=ms, bpm=beat_bpm))
    beats.sort(key=lambda beat: beat.ms)
    if bpm <= 0:
        bpm = beats[0].bpm
    return Grid(bpm=bpm, beats=tuple(beats))


def analyze_file(
    path: Path,
    *,
    engine: Path,
    min_bpm: float,
    max_bpm: float,
) -> Grid:
    try:
        result = subprocess.run(
            [
                str(engine),
                "--min-bpm",
                str(min_bpm),
                "--max-bpm",
                str(max_bpm),
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AnalyzeError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "grid-analyse failed").strip()
        first = detail.splitlines()[0] if detail else "grid-analyse failed"
        raise AnalyzeError(first)
    return parse_grid(result.stdout)
