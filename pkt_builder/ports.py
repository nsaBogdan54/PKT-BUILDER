#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ports.py -- port catalogue and port-name resolver for pkt_core device models.

Packet Tracer kicks a ``.pkt`` out as "Incompatible File" when a ``<LINK>``
references a port name the device does not have, so every port a config names
must be validated before the file is written.  This module reconstructs each
model's interface list from the harvested templates in
``pkt_core/data/device_templates.json``:

* copper/Gigabit/Ethernet ports come from the template's own
  ``RUNNINGCONFIG`` (``interface Fa0/1`` ...), which is the authoritative list
  of names Packet Tracer uses;
* serial ports come from the installed interface card (``HWIC-2T`` and friends)
  plus the model family's naming rule -- ISR-style boxes (18xx/19xx/28xx/29xx)
  name them ``Serial0/<bay>/<n>``, the older 26xx/36xx/37xx/38xx use
  ``Serial0/<2*bay+n>``;
* the 7960 IP phone is special: its two ports are literally ``Switch`` (uplink)
  and ``PC`` (passthrough), never ``FastEthernet0/0``.

User input is accepted in abbreviated form (``Fa0/2``, ``g0/0/0``, ``s0/0/0``)
and expanded to the canonical name; anything that cannot be resolved raises
:class:`PortError` listing the ports the device actually has.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from pkt_core.builder.lab import load_templates

__all__ = [
    "PortError",
    "DevicePorts",
    "port_catalogue",
    "resolve_port",
    "expand_port",
    "shorten_port",
]


class PortError(ValueError):
    """A port name that does not exist on the device."""


# --------------------------------------------------------------------------- #
# template introspection
# --------------------------------------------------------------------------- #
_VIRTUAL_IFACE = re.compile(
    r"^(Vlan|Loopback|Tunnel|Null|Dialer|BVI|Port-channel|Virtual|Async|BRI|"
    r"Serial.*\.\d|GigabitEthernet.*\.\d)", re.I)

_COPPER_TYPES = ("eCopperFastEthernet", "eCopperGigabitEthernet",
                 "eCopperEthernet", "eCopperCoaxial")

# type-name aliases seen in user input -> canonical IOS prefix
_ALIASES = {
    "fa": "FastEthernet", "f": "FastEthernet", "fe": "FastEthernet",
    "fast": "FastEthernet", "fastethernet": "FastEthernet",
    "g": "GigabitEthernet", "gi": "GigabitEthernet",
    "gig": "GigabitEthernet", "gigabitethernet": "GigabitEthernet",
    "te": "TenGigabitEthernet", "tengigabitethernet": "TenGigabitEthernet",
    "s": "Serial", "se": "Serial", "ser": "Serial", "serial": "Serial",
    "e": "Ethernet", "eth": "Ethernet", "ethernet": "Ethernet",
}

_SHORT = {
    "FastEthernet": "Fa", "GigabitEthernet": "Gi",
    "TenGigabitEthernet": "Te", "Ethernet": "Eth", "Serial": "Se",
}

_PHONE_PORTS = ("Switch", "PC")

# models whose serial interfaces are named Serial0/<bay>/<n> (HWIC/NIM era)
_ISR_FAMILY = re.compile(r"^(18\d\d|19\d\d|28\d\d|29\d\d|4\d\d\d|8\d\d$|"
                         r"IR\d|CGR|ISR|ASR)")


@dataclass
class DevicePorts:
    """Everything the builder needs to know about one model's interfaces."""

    model: str
    kinds: dict[str, str] = field(default_factory=dict)   # port name -> copper|serial|special
    copper: list[str] = field(default_factory=list)
    serial: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    # eInterfaceCard bays: one entry per bay, None == empty
    bays: list[str | None] = field(default_factory=list)
    naming_known: bool = True

    @property
    def all(self) -> list[str]:
        return list(self.kinds)

    def kind_of(self, port: str) -> str | None:
        return self.kinds.get(port)

    def free_ports(self, used: set[str], kind: str) -> list[str]:
        pool = self.copper if kind == "copper" else self.serial
        return [p for p in pool if p not in used]


def _motherboard(dev_el: ET.Element) -> ET.Element | None:
    """Return the MODULE element that owns the model's bays and ports."""
    eng = dev_el.find("ENGINE")
    if eng is None:
        return None
    outer = eng.find("MODULE")
    if outer is None:
        return None
    slot = outer.find("SLOT")
    board = slot.find("MODULE") if slot is not None else None
    return board if board is not None else outer


def _ifaces_from_config(dev_el: ET.Element) -> list[str]:
    out: list[str] = []
    rc = dev_el.find("ENGINE/RUNNINGCONFIG")
    if rc is None:
        return out
    for line in rc.findall("LINE"):
        text = (line.text or "").strip()
        if not text.startswith("interface "):
            continue
        name = text[len("interface "):].strip()
        if not name or _VIRTUAL_IFACE.match(name) or name.startswith("range"):
            continue
        if name not in out:
            out.append(name)
    return out


_cache: dict[str, DevicePorts] = {}


def port_catalogue(model: str) -> DevicePorts:
    """Return the interface catalogue of ``model`` (cached).

    Raises :class:`PortError` when the model is not in the template library.
    """
    if model in _cache:
        return _cache[model]

    models, _modules = load_templates()
    raw = models.get(model)
    if raw is None:
        raise PortError(
            "unknown model %r (not in pkt_core/data/device_templates.json)" % (model,))
    dev_el = ET.fromstring(raw)
    cat = DevicePorts(model=model)

    board = _motherboard(dev_el)
    if board is not None:
        for slot in board.findall("SLOT"):
            if slot.findtext("TYPE") != "eInterfaceCard":
                continue
            mod = slot.find("MODULE")
            installed = None
            if mod is not None:
                installed = (mod.findtext("MODEL") or "").strip() or ""
            cat.bays.append(installed)

    board_ports = list(board.findall("PORT")) if board is not None else []
    board_copper = [p for p in board_ports if p.findtext("TYPE") in _COPPER_TYPES]

    if model == "7960":
        for name in _PHONE_PORTS:
            cat.kinds[name] = "special"
            cat.other.append(name)
        _cache[model] = cat
        return cat

    known = _ifaces_from_config(dev_el)
    for name in known:
        if name.startswith("Serial"):
            cat.kinds[name] = "serial"
            cat.serial.append(name)
        else:
            cat.kinds[name] = "copper"
            cat.copper.append(name)

    if not known:
        if len(board_copper) == 1 and cat.bays == []:
            cat.kinds["FastEthernet0"] = "copper"
            cat.copper.append("FastEthernet0")
        else:
            # naming scheme is not reconstructible (hubs, clouds, IoT, ...):
            # accept whatever the user wrote, but say so.
            cat.naming_known = False
            for i, _p in enumerate(board_copper):
                name = "FastEthernet0" if len(board_copper) == 1 else "FastEthernet0/%d" % (i + 1)
                cat.kinds[name] = "copper"
                cat.copper.append(name)

    _cache[model] = cat
    return cat


# --------------------------------------------------------------------------- #
# module-derived serial ports
# --------------------------------------------------------------------------- #
def _module_port_count(module_model: str) -> tuple[int, int]:
    """Return (serial_ports, copper_ports) contributed by an interface card."""
    _models, modules = load_templates()
    xml = modules.get(module_model)
    if xml is None:
        raise PortError("unknown module %r (not in device_templates.json)" % (module_model,))
    serial = xml.count("<TYPE>eSmartSerial</TYPE>")
    copper = sum(xml.count("<TYPE>%s</TYPE>" % t) for t in _COPPER_TYPES)
    return serial, copper


def module_ports(model: str, module_model: str, bay: int) -> list[str]:
    """Port names added to ``model`` by ``module_model`` sitting in ``bay``."""
    serial, copper = _module_port_count(module_model)
    three_level = bool(_ISR_FAMILY.match(model))
    names: list[str] = []
    for i in range(serial):
        if three_level:
            names.append("Serial0/%d/%d" % (bay, i))
        else:
            names.append("Serial0/%d" % (2 * bay + i))
    for i in range(copper):
        names.append("FastEthernet0/%d" % (bay + 1) if not three_level
                     else "FastEthernet0/%d/%d" % (bay, i))
    return names


def with_modules(model: str, modules: list[str]) -> DevicePorts:
    """Return the catalogue of ``model`` after installing ``modules`` in order."""
    base = port_catalogue(model)
    if not modules:
        return base
    cat = DevicePorts(model=model, bays=list(base.bays),
                      naming_known=base.naming_known)
    cat.kinds.update(base.kinds)
    cat.copper = list(base.copper)
    cat.serial = list(base.serial)
    cat.other = list(base.other)

    bay = 0
    for module_model in modules:
        while bay < len(cat.bays) and cat.bays[bay] is not None:
            bay += 1
        if bay >= len(cat.bays) and not cat.bays:
            raise PortError(
                "%s has no interface-card bays; cannot install %s"
                % (model, module_model))
        for name in module_ports(model, module_model, bay):
            if name in cat.kinds:
                continue
            kind = "serial" if name.startswith("Serial") else "copper"
            cat.kinds[name] = kind
            (cat.serial if kind == "serial" else cat.copper).append(name)
        if bay < len(cat.bays):
            cat.bays[bay] = module_model
        bay += 1
    return cat


# --------------------------------------------------------------------------- #
# name resolution
# --------------------------------------------------------------------------- #
def _split_iface(name: str) -> tuple[str, str] | None:
    m = re.match(r"^([A-Za-z][A-Za-z\-]*)\s*([0-9/\.:]*)$", name.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def expand_port(query: str) -> str:
    """Expand an abbreviated interface name (``Fa0/2`` -> ``FastEthernet0/2``).

    Unknown prefixes are returned unchanged so the caller can still match them
    case-insensitively.
    """
    q = query.strip()
    parts = _split_iface(q)
    if not parts:
        return q
    prefix, nums = parts
    canon = _ALIASES.get(prefix.lower())
    if canon is None:
        return q
    return canon + nums


def shorten_port(port: str) -> str:
    parts = _split_iface(port)
    if not parts:
        return port
    return _SHORT.get(parts[0], parts[0]) + parts[1]


def resolve_port(cat: DevicePorts, query: str) -> str:
    """Return the canonical port name of ``cat`` matching ``query``.

    Exact -> case-insensitive -> abbreviated-type match -> trailing-``/0``
    tolerance.  Raises :class:`PortError` with the available port list.
    """
    q = str(query).strip()
    if q in cat.kinds:
        return q

    for name in cat.kinds:
        if name.lower() == q.lower():
            return name

    expanded = expand_port(q)
    if expanded in cat.kinds:
        return expanded
    for name in cat.kinds:
        if name.lower() == expanded.lower():
            return name

    parts = _split_iface(expanded)
    if parts:
        prefix, nums = parts
        want = prefix.lower()
        matches = [
            name for name in cat.kinds
            if (lambda p: p is not None and p[0].lower() == want and p[1] == nums)(
                _split_iface(name))
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise PortError(
                "ambiguous port %r on %s: %s" % (q, cat.model, ", ".join(matches)))
        # "FastEthernet" with no number: single-port end devices
        bare = [
            name for name in cat.kinds
            if (lambda p: p is not None and p[0].lower() == want and p[1] in ("", "0"))(
                _split_iface(name))
        ]
        if len(bare) == 1:
            return bare[0]

    raise PortError(
        "port %r does not exist on %s; available: %s"
        % (q, cat.model, ", ".join(cat.kinds) or "(none)"))
