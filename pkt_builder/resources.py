# SPDX-License-Identifier: GPL-3.0-or-later
"""Access to the files shipped inside :mod:`pkt_builder`.

The donor ``.pkt`` files and the Packet Tracer acceptance script live inside
the package (``pkt_builder/data/``) so they travel with ``pip install``.  They
are read through :mod:`importlib.resources`, which works for a plain install,
an editable install and a zip import alike.

The functions return real filesystem paths where one exists, because the
rest of the tool hands them to other programs (Packet Tracer, PowerShell).
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from importlib import resources
from pathlib import Path

__all__ = ["data_dir", "donor_path", "available_donors", "pt_accept_path"]

DEFAULT_DONOR = "lab3_donor.pkt"

_TEMP: Path | None = None


def _traversable(name: str):
    return resources.files(__package__).joinpath(f"data/{name}")


def data_dir() -> Path:
    """Directory holding the packaged data files.

    For a normal or editable install this is a real directory; for a zip import
    the files are extracted once into a temporary directory that is removed at
    interpreter exit.
    """
    global _TEMP
    node = resources.files(__package__).joinpath("data")
    path = Path(str(node))
    if path.is_dir():
        return path
    if _TEMP is None:
        _TEMP = Path(tempfile.mkdtemp(prefix="pkt-builder-data-"))
        atexit.register(shutil.rmtree, _TEMP, True)
    for child in node.iterdir():
        target = _TEMP / child.name
        if not target.exists():
            target.write_bytes(child.read_bytes())
    return _TEMP


def donor_path(name: str = DEFAULT_DONOR) -> Path:
    """Path of a bundled donor ``.pkt``.

    Relative names are looked up in the package data directory; absolute paths
    are returned unchanged so ``-s /path/to/own.pkt`` keeps working.
    """
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate
    return data_dir() / candidate.name


def available_donors() -> list[str]:
    """Names of every donor ``.pkt`` shipped with the package."""
    return sorted(p.name for p in data_dir().glob("*.pkt"))


def pt_accept_path() -> Path:
    """Path of ``pt_accept.ps1`` (the ``--accept`` harness)."""
    return data_dir() / "pt_accept.ps1"
