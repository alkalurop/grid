"""Playlists in rekordbox.xml and Traktor collection.nml.

Membership and file location only. Beat markers are written elsewhere.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


class LibraryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    path: Path | None
    key: str

    @property
    def label(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} — {self.title}"
        return self.title or self.artist or self.key or "(untitled)"


@dataclass(frozen=True)
class Playlist:
    name: str
    folder: tuple[str, ...]
    tracks: tuple[Track, ...]

    @property
    def full_name(self) -> str:
        parts = self.folder + (self.name,)
        return "/".join(part for part in parts if part)


def parse_rb_location(raw: str) -> Path | None:
    text = unquote((raw or "").replace("file://localhost", "").replace("file://", ""))
    if not text:
        return None
    return Path(text)


def nml_path(directory: str, file_attr: str) -> Path | None:
    name = unquote(file_attr or "")
    if not name:
        return None
    path = Path("/")
    for part in (directory or "").split("/:"):
        if part:
            path = path / part
    return path / name


def load_xml(path: Path) -> list[Playlist]:
    root = _parse(path)
    by_id: dict[str, Track] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for track in collection.findall("TRACK"):
            tid = track.get("TrackID") or ""
            if not tid:
                continue
            by_id[tid] = Track(
                title=track.get("Name") or "",
                artist=track.get("Artist") or "",
                path=parse_rb_location(track.get("Location") or ""),
                key=tid,
            )
    playlists = root.find("PLAYLISTS")
    if playlists is None:
        return []
    found: list[Playlist] = []
    for node in playlists.findall("NODE"):
        found.extend(_walk_xml(node, (), by_id))
    return found


def load_nml(path: Path) -> list[Playlist]:
    root = _parse(path)
    by_key: dict[str, Track] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for entry in collection.findall("ENTRY"):
            location = entry.find("LOCATION")
            if location is None:
                continue
            directory = location.get("DIR") or ""
            file_attr = location.get("FILE") or ""
            volume = location.get("VOLUME") or "Macintosh HD"
            key = f"{volume}{directory}{file_attr}"
            by_key[key] = Track(
                title=entry.get("TITLE") or "",
                artist=entry.get("ARTIST") or "",
                path=nml_path(directory, file_attr),
                key=key,
            )
    playlists = root.find("PLAYLISTS")
    if playlists is None:
        return []
    found: list[Playlist] = []
    for node in playlists.findall("NODE"):
        found.extend(_walk_nml(node, (), by_key))
    return found


def select_playlist(playlists: list[Playlist], name: str) -> Playlist:
    needle = name.strip().strip("/")
    if not needle:
        raise LibraryError("playlist name is empty")
    if "/" in needle:
        matches = [item for item in playlists if item.full_name == needle]
    else:
        matches = [item for item in playlists if item.name == needle]
    if not matches:
        raise LibraryError(f"playlist not found: {needle}")
    if len(matches) > 1:
        names = "\n".join(f"  {item.full_name}" for item in matches)
        raise LibraryError(f"more than one playlist named {needle}:\n{names}")
    return matches[0]


def _parse(path: Path) -> ET.Element:
    if not path.is_file():
        raise LibraryError(f"library not found: {path}")
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise LibraryError(f"could not read {path.name}: {exc}") from exc


def _walk_xml(
    node: ET.Element,
    folder: tuple[str, ...],
    by_id: dict[str, Track],
) -> list[Playlist]:
    name = node.get("Name") or ""
    if node.get("Type") == "1":
        tracks: list[Track] = []
        for child in node.findall("TRACK"):
            tid = child.get("Key") or ""
            tracks.append(by_id.get(tid) or Track("", "", None, tid))
        return [Playlist(name=name, folder=folder, tracks=tuple(tracks))]
    next_folder = folder + ((name,) if name and name != "ROOT" else ())
    found: list[Playlist] = []
    for child in node.findall("NODE"):
        found.extend(_walk_xml(child, next_folder, by_id))
    return found


def _walk_nml(
    node: ET.Element,
    folder: tuple[str, ...],
    by_key: dict[str, Track],
) -> list[Playlist]:
    name = node.get("NAME") or ""
    if (node.get("TYPE") or "").upper() == "PLAYLIST":
        tracks: list[Track] = []
        playlist = node.find("PLAYLIST")
        if playlist is not None:
            for entry in playlist.findall("ENTRY"):
                primary = entry.find("PRIMARYKEY")
                if primary is None:
                    continue
                key = primary.get("KEY") or ""
                tracks.append(by_key.get(key) or Track("", "", None, key))
        return [Playlist(name=name, folder=folder, tracks=tuple(tracks))]
    next_folder = folder + ((name,) if name and name not in {"", "$ROOT"} else ())
    container = node.find("SUBNODES")
    children = container.findall("NODE") if container is not None else []
    found: list[Playlist] = []
    for child in children:
        found.extend(_walk_nml(child, next_folder, by_key))
    return found
