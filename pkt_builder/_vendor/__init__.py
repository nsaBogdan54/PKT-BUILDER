"""Third-party code vendored into pkt_builder.

``pkt_core`` is bundled here so that ``pip install pkt-builder`` brings
everything needed to read and write ``.pkt`` files.  It is unmodified upstream
code and keeps its own ``pkt_core`` package name; :mod:`pkt_builder` puts this
directory on ``sys.path`` before importing anything from it.
"""
