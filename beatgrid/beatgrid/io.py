"""Replace a library file in one step.

Write a sibling temp file, then rename it over the destination so a quit
mid-write leaves the previous document in place.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path


def write_tree(tree: ET.ElementTree, path: Path) -> None:
    dest = Path(path)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tree.write(tmp, encoding="UTF-8", xml_declaration=True)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
