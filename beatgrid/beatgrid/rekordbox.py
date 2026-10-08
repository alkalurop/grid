"""Ask, then replace the beat grids rekordbox loads.

The xml sidecar is a separate write. This module sends the analyzed beats to
grid-analyse, which updates the analysis file and the collection BPM. Key is
left alone. A no answer writes nothing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from beatgrid.analyze import AnalyzeError, Grid


def prompt_overwrite(rows: list[tuple[str, str]]) -> bool:
    """Ask before replacing the grids the deck loads. EOF counts as no."""
    print(f"Overwrite the beatgrids rekordbox loads for these {len(rows)} tracks?", flush=True)
    for label, _path in rows:
        print(f"  {label}", flush=True)
    try:
        answer = input("yes/no: ").strip().lower()
    except EOFError:
        print("no", flush=True)
        return False
    return answer in {"y", "yes"}


def commit_rekordbox(engine: Path, tracks: list[tuple[Path, Grid]]) -> dict[str, int]:
    """Write analyzed grids into the analysis files rekordbox loads."""
    _require_commit_engine(engine)
    payload = {
        "tracks": [
            {
                "path": str(path),
                "beats": [{"n": beat.n, "ms": beat.ms, "bpm": beat.bpm} for beat in grid.beats],
            }
            for path, grid in tracks
        ]
    }
    try:
        result = subprocess.run(
            [str(engine), "--commit-rekordbox"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AnalyzeError(str(exc)) from exc
    if result.stderr.strip():
        print(result.stderr.rstrip(), flush=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "grid-analyse failed").strip()
        first = detail.splitlines()[-1] if detail else "grid-analyse failed"
        raise AnalyzeError(first)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AnalyzeError(f"grid-analyse did not print JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise AnalyzeError("grid-analyse JSON must be an object")
    try:
        return {
            "wrote": int(report["wrote"]),
            "missing": int(report.get("missing", 0)),
            "skipped": int(report.get("skipped", 0)),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalyzeError("grid-analyse JSON is missing wrote") from exc


def _require_commit_engine(engine: Path) -> None:
    """Refuse when grid-analyse was built before the rekordbox commit path existed."""
    try:
        probe = subprocess.run(
            [str(engine), "--commit-rekordbox"],
            input='{"tracks":[]}',
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AnalyzeError(str(exc)) from exc
    combined = f"{probe.stderr}\n{probe.stdout}"
    if "unknown argument --commit-rekordbox" in combined:
        raise AnalyzeError(
            "grid-analyse is too old for rekordbox grid writes. From the grid repo:\n"
            "  cargo build --release --manifest-path beatgrid/engine/Cargo.toml"
        )
