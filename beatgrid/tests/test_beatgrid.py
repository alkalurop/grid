"""Playlist read, dry-run, and grid write. The engine is a stand-in script."""

from __future__ import annotations

import json
import stat
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote

from beatgrid.__main__ import main
from beatgrid.analyze import AnalyzeError, parse_grid
from beatgrid.library import load_nml, load_xml, select_playlist


def _engine(path: Path, *, code: int = 0, bpm: float = 128.0) -> None:
    body = json.dumps(
        {
            "bpm": bpm,
            "beats": [
                {"n": 1, "ms": 0, "bpm": bpm},
                {"n": 2, "ms": 468, "bpm": bpm},
            ],
        }
    )
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stderr.write('min=' + sys.argv[sys.argv.index('--min-bpm') + 1] + '\\n')\n"
        f"code = {code}\n"
        "if code:\n"
        "    raise SystemExit(code)\n"
        f"print({body!r})\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _rb_location(path: Path) -> str:
    return "file://localhost" + quote(str(path))


def _xml(path: Path, tracks: str, nodes: str) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<DJ_PLAYLISTS>\n"
        "<COLLECTION>\n"
        f"{tracks}\n"
        "</COLLECTION>\n"
        "<PLAYLISTS>\n"
        '<NODE Type="0" Name="ROOT">\n'
        f"{nodes}\n"
        "</NODE>\n"
        "</PLAYLISTS>\n"
        "</DJ_PLAYLISTS>\n"
    )


def _nml_dir(path: Path) -> tuple[str, str, str]:
    parts = [part for part in path.parent.parts if part != "/"]
    directory = "/:" + "/:".join(parts) + "/:"
    key = f"Macintosh HD{directory}{path.name}"
    return directory, path.name, key


class LibraryTests(unittest.TestCase):
    def test_xml_playlist_and_encoded_location(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "Lion Steps.wav"
            audio.write_bytes(b"RIFFmix")
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                (
                    f'<TRACK TrackID="7" Name="Lion Steps" Artist="The Timewriter" '
                    f'Location="{_rb_location(audio)}"/>'
                ),
                (
                    '<NODE Type="0" Name="House">'
                    '<NODE Type="1" Name="Deep"><TRACK Key="7"/></NODE>'
                    "</NODE>"
                ),
            )
            chosen = select_playlist(load_xml(xml), "House/Deep")
            self.assertEqual(chosen.tracks[0].path, audio)
            self.assertEqual(chosen.tracks[0].label, "The Timewriter — Lion Steps")

    def test_shared_playlist_name_needs_the_folder(self) -> None:
        with TemporaryDirectory() as tmp:
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                "",
                (
                    '<NODE Type="1" Name="Deep"/>'
                    '<NODE Type="0" Name="House"><NODE Type="1" Name="Deep"/></NODE>'
                ),
            )
            with self.assertRaises(Exception) as raised:
                select_playlist(load_xml(xml), "Deep")
            self.assertIn("more than one", str(raised.exception))

    def test_nml_playlist_path(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            directory, file_attr, key = _nml_dir(audio)
            nml = Path(tmp) / "collection.nml"
            nml.write_text(
                "<NML>"
                "<COLLECTION>"
                '<ENTRY TITLE="Lion" ARTIST="A">'
                f'<LOCATION DIR="{directory}" FILE="{file_attr}" VOLUME="Macintosh HD"/>'
                "</ENTRY>"
                "</COLLECTION>"
                "<PLAYLISTS>"
                '<NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="1">'
                '<NODE TYPE="PLAYLIST" NAME="Deep"><PLAYLIST>'
                f'<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="{key}"/></ENTRY>'
                "</PLAYLIST></NODE>"
                "</SUBNODES></NODE>"
                "</PLAYLISTS></NML>"
            )
            chosen = select_playlist(load_nml(nml), "Deep")
            self.assertEqual(chosen.tracks[0].path, audio)


class CommandTests(unittest.TestCase):
    def test_dry_run_leaves_the_grid(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                (
                    f'<TRACK TrackID="7" Name="Lion" Artist="A" AverageBpm="100.00" '
                    f'Location="{_rb_location(audio)}">'
                    '<TEMPO Inizio="0" Bpm="100.00" Metro="4/4" Battito="1"/>'
                    "</TRACK>"
                ),
                '<NODE Type="1" Name="Deep"><TRACK Key="7"/></NODE>',
            )
            before = xml.read_text()
            code = main(["Deep", "--xml", str(xml)])
            self.assertEqual(code, 0)
            self.assertEqual(xml.read_text(), before)
            self.assertFalse(Path(str(xml) + ".beatgrid.bak").exists())

    def test_execute_writes_xml_beats_and_keeps_cues(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            engine = Path(tmp) / "engine"
            _engine(engine, bpm=128.0)
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                (
                    f'<TRACK TrackID="7" Name="Lion" Artist="A" AverageBpm="100.00" '
                    f'Location="{_rb_location(audio)}">'
                    '<POSITION_MARK Name="hot" Type="0" Start="4" Num="0"/>'
                    '<TEMPO Inizio="0" Bpm="100.00" Metro="4/4" Battito="1"/>'
                    "</TRACK>"
                ),
                '<NODE Type="1" Name="Deep"><TRACK Key="7"/></NODE>',
            )
            with (
                patch("beatgrid.__main__.rekordbox_is_running", return_value=False),
                patch(
                    "beatgrid.__main__.commit_rekordbox",
                    return_value={"wrote": 1, "missing": 0, "skipped": 0},
                ),
            ):
                code = main(
                    ["Deep", "--xml", str(xml), "--execute", "--min-bpm", "98", "--max-bpm", "195", "--engine", str(engine)],
                    confirm=lambda rows: True,
                )
            self.assertEqual(code, 0)
            track = ET.parse(xml).find("./COLLECTION/TRACK")
            assert track is not None
            self.assertEqual(track.get("AverageBpm"), "128.00")
            tempos = track.findall("TEMPO")
            self.assertEqual([item.get("Battito") for item in tempos], ["1", "2"])
            self.assertEqual(tempos[1].get("Inizio"), "0.468")
            self.assertEqual(track.find("POSITION_MARK").get("Name"), "hot")
            self.assertTrue(Path(str(xml) + ".beatgrid.bak").is_file())

    def test_declining_leaves_the_rekordbox_grids_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                (
                    f'<TRACK TrackID="7" Name="Lion" Artist="A" AverageBpm="100.00" '
                    f'Location="{_rb_location(audio)}">'
                    '<TEMPO Inizio="0" Bpm="100.00" Metro="4/4" Battito="1"/>'
                    "</TRACK>"
                ),
                '<NODE Type="1" Name="Deep"><TRACK Key="7"/></NODE>',
            )
            before = xml.read_text()
            with (
                patch("beatgrid.__main__.rekordbox_is_running", return_value=False),
                patch("beatgrid.__main__.commit_rekordbox") as commit,
            ):
                code = main(
                    ["Deep", "--xml", str(xml), "--execute"],
                    confirm=lambda rows: False,
                )
            self.assertEqual(code, 0)
            self.assertEqual(xml.read_text(), before)
            commit.assert_not_called()

    def test_yes_commits_the_rekordbox_grids(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            engine = Path(tmp) / "engine"
            _engine(engine)
            xml = Path(tmp) / "rekordbox.xml"
            _xml(
                xml,
                (
                    f'<TRACK TrackID="7" Name="Lion" Artist="A" AverageBpm="100.00" '
                    f'Location="{_rb_location(audio)}">'
                    '<TEMPO Inizio="0" Bpm="100.00" Metro="4/4" Battito="1"/>'
                    "</TRACK>"
                ),
                '<NODE Type="1" Name="Deep"><TRACK Key="7"/></NODE>',
            )
            with (
                patch("beatgrid.__main__.rekordbox_is_running", return_value=False),
                patch(
                    "beatgrid.__main__.commit_rekordbox",
                    return_value={"wrote": 1, "missing": 0, "skipped": 0},
                ) as commit,
            ):
                code = main(["Deep", "--xml", str(xml), "--execute", "--yes", "--engine", str(engine)])
            self.assertEqual(code, 0)
            commit.assert_called_once()
            sent = commit.call_args.args[1]
            self.assertEqual(sent[0][0], audio)
            self.assertEqual(sent[0][1].bpm, 128.0)

    def test_execute_writes_nml_anchor_and_keeps_hot_cue(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "lion.wav"
            audio.write_bytes(b"RIFFmix")
            engine = Path(tmp) / "engine"
            _engine(engine)
            directory, file_attr, key = _nml_dir(audio)
            nml = Path(tmp) / "collection.nml"
            nml.write_text(
                "<NML><COLLECTION>"
                '<ENTRY TITLE="Lion" ARTIST="A">'
                f'<LOCATION DIR="{directory}" FILE="{file_attr}" VOLUME="Macintosh HD"/>'
                '<CUE_V2 NAME="old" TYPE="0" START="1000.000000" LEN="0.000000" REPEATS="-1" HOTCUE="0"/>'
                '<CUE_V2 NAME="AutoGrid" TYPE="4" START="9.200000" LEN="0.000000" REPEATS="-1" HOTCUE="-1"/>'
                '<TEMPO BPM="100.000000"/>'
                "</ENTRY></COLLECTION>"
                "<PLAYLISTS>"
                '<NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="1">'
                '<NODE TYPE="PLAYLIST" NAME="Deep"><PLAYLIST>'
                f'<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="{key}"/></ENTRY>'
                "</PLAYLIST></NODE></SUBNODES></NODE>"
                "</PLAYLISTS></NML>"
            )
            with patch("beatgrid.__main__.traktor_is_running", return_value=False):
                code = main(["Deep", "--nml", str(nml), "--execute", "--engine", str(engine)])
            self.assertEqual(code, 0)
            entry = ET.parse(nml).find("./COLLECTION/ENTRY")
            assert entry is not None
            self.assertEqual(entry.find("TEMPO").get("BPM"), "128.000000")
            hot = [cue for cue in entry.findall("CUE_V2") if cue.get("HOTCUE") != "-1"]
            grid = [cue for cue in entry.findall("CUE_V2") if cue.get("TYPE") == "4"]
            self.assertEqual(hot[0].get("NAME"), "old")
            self.assertEqual(len(grid), 1)
            self.assertEqual(grid[0].get("START"), "0.000000")

    def test_open_rekordbox_refuses_the_write(self) -> None:
        with TemporaryDirectory() as tmp:
            xml = Path(tmp) / "rekordbox.xml"
            _xml(xml, "", '<NODE Type="1" Name="Deep"/>')
            before = xml.read_text()
            with patch("beatgrid.__main__.rekordbox_is_running", return_value=True):
                code = main(["Deep", "--xml", str(xml), "--execute", "--engine", str(Path(tmp) / "missing")])
            self.assertEqual(code, 2)
            self.assertEqual(xml.read_text(), before)

    def test_bad_engine_json(self) -> None:
        with self.assertRaises(AnalyzeError):
            parse_grid('{"bpm": 1}')


if __name__ == "__main__":
    unittest.main()
