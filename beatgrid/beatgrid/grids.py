"""Write a beat grid onto one collection row.

Rekordbox XML gets one TEMPO marker per beat, so a tempo change survives.
Hot cues and memory cues stay. Traktor gets the opening BPM plus one
AutoGrid anchor at the first downbeat. Hot cues stay. Traktor's NML has
no per-beat grid, so a mid-track tempo change is not written there.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from beatgrid.analyze import Grid
from beatgrid.io import write_tree
from beatgrid.library import LibraryError


def backup_library(path: Path) -> Path:
    dest = path.with_name(path.name + ".beatgrid.bak")
    shutil.copy2(path, dest)
    return dest


def write_xml_grids(path: Path, grids: dict[str, Grid]) -> int:
    tree = ET.parse(path)
    collection = tree.getroot().find("COLLECTION")
    if collection is None:
        raise LibraryError(f"{path.name} has no COLLECTION")
    written = 0
    for track in collection.findall("TRACK"):
        grid = grids.get(track.get("TrackID") or "")
        if grid is None:
            continue
        for tempo in list(track.findall("TEMPO")):
            track.remove(tempo)
        for beat in grid.beats:
            ET.SubElement(
                track,
                "TEMPO",
                Inizio=f"{beat.ms / 1000:.3f}",
                Bpm=f"{beat.bpm:.2f}",
                Metro="4/4",
                Battito=str(beat.n),
            )
        track.set("AverageBpm", f"{grid.bpm:.2f}")
        written += 1
    if written:
        write_tree(tree, path)
    return written


def write_nml_grids(path: Path, grids: dict[str, Grid]) -> int:
    tree = ET.parse(path)
    collection = tree.getroot().find("COLLECTION")
    if collection is None:
        raise LibraryError(f"{path.name} has no COLLECTION")
    by_key = _nml_keys(collection)
    written = 0
    for key, grid in grids.items():
        entry = by_key.get(key)
        if entry is None:
            continue
        _set_tempo(entry, grid.bpm)
        _replace_grid_anchor(entry, _anchor_ms(grid))
        written += 1
    if written:
        write_tree(tree, path)
    return written


def _nml_keys(collection: ET.Element) -> dict[str, ET.Element]:
    found: dict[str, ET.Element] = {}
    for entry in collection.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is None:
            continue
        directory = location.get("DIR") or ""
        file_attr = location.get("FILE") or ""
        volume = location.get("VOLUME") or "Macintosh HD"
        found[f"{volume}{directory}{file_attr}"] = entry
    return found


def _set_tempo(entry: ET.Element, bpm: float) -> None:
    tempo = entry.find("TEMPO")
    if tempo is None:
        tempo = ET.SubElement(entry, "TEMPO")
    tempo.set("BPM", f"{bpm:.6f}")
    tempo.set("BPM_QUALITY", "100.000000")


def _replace_grid_anchor(entry: ET.Element, start_ms: int) -> None:
    for cue in list(entry.findall("CUE_V2")):
        if cue.get("TYPE") == "4" or cue.get("NAME") == "AutoGrid":
            entry.remove(cue)
    ET.SubElement(
        entry,
        "CUE_V2",
        NAME="AutoGrid",
        DISPL_ORDER="0",
        TYPE="4",
        START=f"{start_ms:.6f}",
        LEN="0.000000",
        REPEATS="-1",
        HOTCUE="-1",
    )


def _anchor_ms(grid: Grid) -> int:
    for beat in grid.beats:
        if beat.n == 1:
            return beat.ms
    return grid.beats[0].ms
