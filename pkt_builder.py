#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility launcher: ``python pkt_builder.py`` == ``pkt-builder``.

The real code lives in the ``pkt_builder`` package next to this file; use that
package when importing from Python::

    from pkt_builder.config import parse_spec

After ``pip install pkt-builder`` the console script ``pkt-builder`` is the
preferred entry point; this file is only for source checkouts.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pkt_builder.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
