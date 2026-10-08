"""Whether a deck app has the library open.

rekordboxAgent stays up after quit, and its path contains the rekordbox
binary as a prefix. Match the main app binary only. AppleScript is the
wrong check for that process.
"""

from __future__ import annotations

import subprocess

REKORDBOX_BINARY = "/rekordbox.app/Contents/MacOS/rekordbox"
TRAKTOR_BINARY = "/Traktor.app/Contents/MacOS/Traktor"


def _comms() -> list[str]:
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "comm="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def rekordbox_is_running() -> bool:
    return any(comm.endswith(REKORDBOX_BINARY) for comm in _comms())


def traktor_is_running() -> bool:
    return any(comm.endswith(TRAKTOR_BINARY) for comm in _comms())
