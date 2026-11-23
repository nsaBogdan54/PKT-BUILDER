# SPDX-License-Identifier: GPL-3.0-or-later
"""pkt_builder -- build Packet Tracer .pkt files from a YAML description.

Modules
-------
``miniyaml``  dependency-free YAML subset parser (no ``pip install`` needed)
``config``    the YAML schema: normalisation and validation
``ports``     per-model port catalogues, abbreviated-name resolution
``builder``   LabSpec -> .pkt (the verified add/link/power/config order)
``verify``    structural checks that predict "Incompatible File"
``exporter``  .pkt -> YAML
``resources`` access to the bundled donors and the acceptance harness
``cli``       command line interface (the ``pkt-builder`` script)

The vendored ``pkt_core`` library lives in ``pkt_builder/_vendor/pkt_core/``
(GPL-3.0-or-later, unmodified upstream); this module puts
``pkt_builder/_vendor`` on ``sys.path`` so the rest of the package can simply
``import pkt_core``.  ``pkt_core`` uses absolute imports internally
(``from pkt_core.x import y``), so keeping the upstream package name is the
smallest possible shim.
"""
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent

_candidate = _HERE / "_vendor"
if (_candidate / "pkt_core" / "__init__.py").is_file():
    _path = str(_candidate)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from pkt_builder.config import ConfigError, DeviceSpec, LabSpec, LinkSpec, parse_spec
from pkt_builder.ports import PortError, port_catalogue, resolve_port

__all__ = [
    "ConfigError",
    "DeviceSpec",
    "LabSpec",
    "LinkSpec",
    "PortError",
    "parse_spec",
    "port_catalogue",
    "resolve_port",
]

__version__ = "0.1.3"
