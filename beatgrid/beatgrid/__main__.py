"""Analyze one rekordbox or Traktor playlist and write the beat grid.

Dry-run is the default. --execute analyzes each audio file and writes the
grid back into that library. On rekordbox xml it asks before replacing the
grids the deck loads. Rekordbox must be quit for XML. Traktor must be quit
for NML.

    PYTHONPATH=beatgrid python3 -m beatgrid "Deep House" --xml
    PYTHONPATH=beatgrid python3 -m beatgrid "Deep House" --nml --execute
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from beatgrid.analyze import AnalyzeError, Grid, analyze_file, engine_path
from beatgrid.grids import backup_library, write_nml_grids, write_xml_grids
from beatgrid.library import LibraryError, load_nml, load_xml, select_playlist
from beatgrid.rekordbox import commit_rekordbox, prompt_overwrite
from beatgrid.running import rekordbox_is_running, traktor_is_running

Confirm = Callable[[list[tuple[str, str]]], bool]

DEFAULT_XML = Path.home() / "Music" / "PioneerDJ" / "rekordbox.xml"
DEFAULT_NML = (
    Path.home() / "Documents" / "Native Instruments" / "Traktor 4.5.1" / "collection.nml"
)


def main(argv: list[str] | None = None, confirm: Confirm | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playlist", help="Playlist name, or Folder/Name when the name is shared.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--xml",
        nargs="?",
        const=DEFAULT_XML,
        type=Path,
        help=f"rekordbox.xml (default {DEFAULT_XML})",
    )
    source.add_argument(
        "--nml",
        nargs="?",
        const=DEFAULT_NML,
        type=Path,
        help=f"Traktor collection.nml (default {DEFAULT_NML})",
    )
    parser.add_argument("--execute", action="store_true", help="Analyze and write. Default is dry-run.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Overwrite the rekordbox grids without asking.",
    )
    parser.add_argument("--min-bpm", type=float, default=70.0, help="Tempo search floor. Default 70.")
    parser.add_argument("--max-bpm", type=float, default=180.0, help="Tempo search ceiling. Default 180.")
    parser.add_argument("--engine", type=Path, default=None, help="grid-analyse binary. Default: the release build.")
    args = parser.parse_args(argv)

    if args.min_bpm <= 0 or args.max_bpm <= args.min_bpm:
        print("BPM range must be a positive span, low then high.", file=sys.stderr)
        return 2

    library = args.xml if args.xml is not None else args.nml
    kind = "xml" if args.xml is not None else "nml"
    assert library is not None
    try:
        playlists = load_xml(library) if kind == "xml" else load_nml(library)
        playlist = select_playlist(playlists, args.playlist)
    except LibraryError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"playlist  {playlist.full_name}", flush=True)
    print(f"library   {library}", flush=True)
    print(f"tracks    {len(playlist.tracks)}", flush=True)
    for track in playlist.tracks:
        if track.path is not None and track.path.is_file():
            print(f"  {track.label}  {track.path}", flush=True)
        else:
            where = track.path if track.path is not None else track.key
            print(f"  missing  {track.label}  {where}", flush=True)

    if not args.execute:
        print("dry-run. pass --execute to analyze and write grids.", flush=True)
        return 0

    if kind == "xml" and rekordbox_is_running():
        print("Rekordbox is open. Quit it before --execute writes rekordbox.xml.", file=sys.stderr)
        return 2
    if kind == "nml" and traktor_is_running():
        print("Traktor is open. Quit it before --execute writes collection.nml.", file=sys.stderr)
        return 2

    rows = [
        (track.label, str(track.path))
        for track in playlist.tracks
        if track.path is not None and track.path.is_file()
    ]
    if kind == "xml" and rows:
        ask = confirm
        if ask is None:
            ask = (lambda _rows: True) if args.yes else prompt_overwrite
        if not ask(rows):
            print("left the rekordbox grids alone", flush=True)
            return 0

    try:
        engine = args.engine if args.engine is not None else engine_path()
    except AnalyzeError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not engine.is_file():
        print(f"grid-analyse not found: {engine}", file=sys.stderr)
        return 2

    grids: dict[str, Grid] = {}
    failed = 0
    present = [track for track in playlist.tracks if track.path is not None and track.path.is_file()]
    seen: set[str] = set()
    for track in present:
        assert track.path is not None
        if track.key in seen:
            continue
        seen.add(track.key)
        if track.path.suffix.lower() == ".m4p":
            print(f"  skip  {track.label}  apple drm", flush=True)
            failed += 1
            continue
        try:
            grid = analyze_file(
                track.path,
                engine=engine,
                min_bpm=args.min_bpm,
                max_bpm=args.max_bpm,
            )
        except AnalyzeError as exc:
            failed += 1
            print(f"  failed  {track.label}  {exc}", flush=True)
            continue
        grids[track.key] = grid
        print(f"  analyzed  {track.label}  {grid.bpm:.2f}", flush=True)

    if not grids:
        print("nothing analyzed.", file=sys.stderr)
        return 1

    if kind == "xml":
        chosen = []
        sent: set[str] = set()
        for track in playlist.tracks:
            if track.path is None or track.key not in grids or track.key in sent:
                continue
            sent.add(track.key)
            chosen.append((track.path, grids[track.key]))
        try:
            report = commit_rekordbox(engine, chosen)
        except AnalyzeError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"rekordbox  {report['wrote']}", flush=True)
        if report["missing"]:
            print(f"unmatched  {report['missing']}", flush=True)
        if report["skipped"]:
            print(f"no file    {report['skipped']}", flush=True)

    bak = backup_library(library)
    written = write_xml_grids(library, grids) if kind == "xml" else write_nml_grids(library, grids)
    print(f"analyzed  {len(grids)}", flush=True)
    print(f"failed    {failed}", flush=True)
    print(f"missing   {len(playlist.tracks) - len(present)}", flush=True)
    print(f"wrote     {library}", flush=True)
    print(f"backup    {bak}", flush=True)
    if kind == "xml":
        print("Open rekordbox and load the track. That loads this grid.", flush=True)
        print("If a tag dialog appears: Don't ask again + No.", flush=True)
    else:
        print("Reopen Traktor.", flush=True)
    if failed or not written:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
