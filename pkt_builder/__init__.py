"""pkt_builder -- build Packet Tracer .pkt files from a YAML description.

Modules
-------
``miniyaml``  dependency-free YAML subset parser (no ``pip install`` needed)
``config``    the YAML schema: normalisation and validation
``ports``     per-model port catalogues, abbreviated-name resolution
``builder``   LabSpec -> .pkt (the verified add/link/power/config order)
``verify``    structural checks that predict "Incompatible File"
``exporter``  .pkt -> YAML
``cli``       command line interface (``python -m pkt_builder``)
"""
import pathlib
import sys

# The repository root holds the vendored ``pkt_core`` package, and is also the
# directory that makes ``pkt_builder`` itself importable.  Keeping it on the
# path here means every submodule can just ``import pkt_core`` regardless of
# where the interpreter was started.
_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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
