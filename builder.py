#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""builder.py -- turn a :class:`~pkt_builder.config.LabSpec` into a .pkt file.

The order of operations is not arbitrary; it is the one verified against Packet
Tracer 9.0.0 (see ``pkt_builder.md`` sections 5-8):

1. ``Lab(seed=...)`` + ``prune_seed_devices()``
2. ``add_device()`` for every device (modules installed right after)
3. every ``link()`` -- serial links write ``clock rate`` into the DCE config
4. ``force_copper_power()`` on every device
5. read the generated MACs out of the XML and expand ``{{mac:NAME}}`` /
   ``{{client_id:NAME}}`` placeholders in the configs
6. ``set_cfg()`` -- replace RUNNINGCONFIG wholesale (must be after linking)
7. ``lab.save()``
"""
from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from pkt_core.builder import Lab, Layout
from pkt_core.codec.container import decode

from pkt_builder.config import ConfigError, DeviceSpec, LabSpec, LinkSpec
from pkt_builder.ports import (
    DevicePorts,
    PortError,
    port_catalogue,
    resolve_port,
    with_modules,
)

__all__ = ["BuildResult", "build_lab", "copper_power", "set_cfg", "mac_of", "client_id"]

# Copper port element types whose <POWER> must be true for the cable to come up.
_COPPER_PORT_TYPES = (
    "eCopperFastEthernet",
    "eCopperGigabitEthernet",
    "eCopperEthernet",
)

_PLACEHOLDER = re.compile(r"\{\{\s*(mac|client_id)\s*:\s*([^{}]+?)\s*\}\}")
_PLACEHOLDER_NAME = re.compile(r"\{\{\s*name\s*\}\}")


@dataclass
class BuildResult:
    path: pathlib.Path
    size: int
    devices: list[DeviceSpec] = field(default_factory=list)
    links: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    macs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# config surgery helpers (kept identical in behaviour to build_8lab.py)
# --------------------------------------------------------------------------- #
def copper_power(lab: Lab, dev_id: str) -> int:
    """Set ``<PORT><POWER>true`` on every copper port of a device.

    Harvested templates sometimes ship with a powered-down copper port (the
    2620XM arrives with Fa0/0 off), which renders the cable red even though the
    IOS config is correct.  Serial ports are deliberately left alone -- their
    power state belongs to ``link()``.
    """
    touched = 0
    for port in lab._els[dev_id].iter("PORT"):
        if port.findtext("TYPE") not in _COPPER_PORT_TYPES:
            continue
        node = port.find("POWER")
        if node is None:
            node = ET.SubElement(port, "POWER")
        node.text = "true"
        touched += 1
    return touched


def set_cfg(lab: Lab, dev_id: str, lines: list[str]) -> None:
    """Replace a device's RUNNINGCONFIG with ``lines``.

    Must run after ``link()``: a serial link appends ``clock rate`` to the DCE
    config, and writing the config first would clobber it.
    """
    engine = lab._els[dev_id].find("ENGINE")
    for old in list(engine.findall("RUNNINGCONFIG")):
        engine.remove(old)
    rc = ET.SubElement(engine, "RUNNINGCONFIG")
    for line in lines:
        ET.SubElement(rc, "LINE").text = line


def mac_of(lab: Lab, dev_id: str) -> str | None:
    """MAC of the device's first copper port (what ephone/DHCP need)."""
    for port in lab._els[dev_id].iter("PORT"):
        if port.findtext("TYPE") in _COPPER_PORT_TYPES:
            return port.findtext("MACADDRESS")
    return None


def client_id(mac: str) -> str:
    """DHCP client-identifier for an IP phone: ``01`` + dotted-hex MAC."""
    hexed = mac.replace(".", "").upper()
    return "01" + ".".join(hexed[i:i + 4] for i in range(0, 12, 4))


# --------------------------------------------------------------------------- #
# port assignment
# --------------------------------------------------------------------------- #
def _auto_ports(spec: LinkSpec, cats: dict[str, DevicePorts],
                used: dict[str, set[str]]) -> tuple[str, str, str]:
    """Choose free ports and a cable kind for an ``auto`` link.

    Serial is chosen when both ends have a free serial port *and* the link asked
    for it (dce/clock/kind hints); otherwise the first free copper pair wins.
    """
    a_cat, b_cat = cats[spec.a], cats[spec.b]
    a_used, b_used = used[spec.a], used[spec.b]

    wants_serial = spec.kind == "serial" or spec.dce is not None or spec.clock != 64000

    def pick(kind: str):
        for pa in a_cat.free_ports(a_used, kind):
            for pb in b_cat.free_ports(b_used, kind):
                return pa, pb
        return None

    if wants_serial:
        pair = pick("serial")
        if pair is None:
            raise PortError(
                "auto link %s <-> %s: no free serial port pair left "
                "(%s serial: %s; %s serial: %s)"
                % (spec.a, spec.b, spec.a,
                   ", ".join(a_cat.serial) or "none",
                   spec.b, ", ".join(b_cat.serial) or "none"))
        return pair[0], pair[1], "serial"

    pair = pick("copper")
    if pair is None:
        raise PortError(
            "auto link %s <-> %s: no free copper port pair left "
            "(%s copper: %s; %s copper: %s)"
            % (spec.a, spec.b, spec.a,
               ", ".join(a_cat.copper) or "none",
               spec.b, ", ".join(b_cat.copper) or "none"))
    return pair[0], pair[1], "copper"


def _kind_from_ports(link: LinkSpec, cats: dict[str, DevicePorts],
                     a_port: str, b_port: str) -> str:
    kind = None
    for cat, port in ((cats[link.a], a_port), (cats[link.b], b_port)):
        k = cat.kind_of(port)
        if k == "serial":
            kind = "serial"
        elif k == "copper" and kind is None:
            kind = "copper"
    if kind is None:
        kind = "copper"
    if kind == "serial":
        for cat, port in ((cats[link.a], a_port), (cats[link.b], b_port)):
            if cat.kind_of(port) == "copper":
                raise PortError(
                    "link %s:%s <-> %s:%s mixes a copper and a serial port"
                    % (link.a, a_port, link.b, b_port))
    return kind


# --------------------------------------------------------------------------- #
# config placeholder expansion
# --------------------------------------------------------------------------- #
def _expand_cfg(lines: list[str], machine: DeviceSpec, macs: dict[str, str]) -> list[str]:
    def repl(match: re.Match) -> str:
        field_name, target = match.group(1), match.group(2)
        if target not in macs:
            raise ConfigError(
                "devices[%d] (%s): placeholder {{%s:%s}} refers to an unknown "
                "device or a device without a copper port"
                % (machine.index, machine.name, field_name, target))
        mac = macs[target]
        return client_id(mac) if field_name == "client_id" else mac

    out = []
    for line in lines:
        line = _PLACEHOLDER.sub(repl, line)
        out.append(_PLACEHOLDER_NAME.sub(machine.name, line))
    return out


# --------------------------------------------------------------------------- #
# seed / version
# --------------------------------------------------------------------------- #
def seed_version(path: pathlib.Path) -> str | None:
    try:
        root = ET.fromstring(decode(str(path), None).xml)
    except Exception:
        return None
    return root.findtext("VERSION")


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text) or [0])


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def build_lab(spec: LabSpec, out_path: pathlib.Path, seed: pathlib.Path,
              models: dict | None = None) -> BuildResult:
    """Build the lab described by ``spec`` and save it to ``out_path``."""
    warnings: list[str] = []
    result = BuildResult(path=out_path, size=0, devices=list(spec.devices))

    # --- 0. seed sanity --------------------------------------------------- #
    if not seed.exists():
        raise ConfigError("seed file not found: %s" % seed)
    version = seed_version(seed)
    if version:
        nums = _version_tuple(version)
        if nums[:3] > (9, 0, 0):
            warnings.append(
                "seed %s has VERSION %s; Packet Tracer refuses files newer than "
                "itself (9.0.0 = 9.0.0.0810). Use a .pkt your PT opens." %
                (seed.name, version))
        result.warnings.append("seed VERSION %s" % version)

    # --- 1. catalogues (needs install list before linking) ---------------- #
    cats: dict[str, DevicePorts] = {}
    for dev in spec.devices:
        try:
            cats[dev.name] = with_modules(dev.model, dev.install)
        except PortError as exc:
            raise ConfigError("devices[%d] (%s): %s" % (dev.index, dev.name, exc))
        if not cats[dev.name].naming_known and dev.install:
            warnings.append(
                "%s: interface naming of model %r is not in the template "
                "config; install/module ports were inferred" % (dev.name, dev.model))

    # --- 2. resolve explicit link ports up front (fail before writing) ----- #
    used: dict[str, set[str]] = {d.name: set() for d in spec.devices}
    plan: list[tuple[LinkSpec, str, str, str]] = []
    for link in spec.links:
        if link.auto:
            a_port, b_port, kind = _auto_ports(link, cats, used)
        else:
            cat_a, cat_b = cats[link.a], cats[link.b]
            if not cat_a.naming_known or not cat_b.naming_known:
                a_port = str(link.a_port)
                b_port = str(link.b_port)
            else:
                try:
                    a_port = resolve_port(cat_a, link.a_port)
                except PortError as exc:
                    raise ConfigError("links[%d]: %s (%s)" % (link.index, exc, link.a))
                try:
                    b_port = resolve_port(cat_b, link.b_port)
                except PortError as exc:
                    raise ConfigError("links[%d]: %s (%s)" % (link.index, exc, link.b))
            kind = link.kind or _kind_from_ports(link, cats, a_port, b_port)
            if kind == "serial":
                for cat, port in ((cat_a, a_port), (cat_b, b_port)):
                    if cat.naming_known and cat.kind_of(port) != "serial":
                        raise ConfigError(
                            "links[%d]: kind serial, but %s is not a serial port "
                            "on %s (serial ports: %s)"
                            % (link.index, port, cat.model,
                               ", ".join(cat.serial) or "none"))

        for dev_name, port in ((link.a, a_port), (link.b, b_port)):
            if port in used[dev_name]:
                warnings.append("%s: port %s is cabled twice" % (dev_name, port))
            used[dev_name].add(port)

        if kind == "serial" and link.dce is None:
            link.dce = link.a
        plan.append((link, a_port, b_port, kind))

    # --- 3. layout -------------------------------------------------------- #
    layout = Layout()
    for dev in spec.devices:
        if dev.x is not None and dev.y is not None:
            layout.reserve(dev.name, dev.model, dev.x, dev.y)
    for dev in spec.devices:
        if dev.x is None or dev.y is None:
            placement = layout.place(dev.name, dev.model)
            dev.x, dev.y = placement.x, placement.y

    # --- 4. build --------------------------------------------------------- #
    lab = Lab(seed=str(seed))
    lab.prune_seed_devices()

    ids: dict[str, str] = {}
    for dev in spec.devices:
        try:
            dev_id = lab.add_device(
                dev.model, dev.name, dev.x, dev.y,
                power=dev.power,
                pc_ip=tuple(dev.pc_ip) if dev.pc_ip else None,
            )
        except ValueError as exc:
            raise ConfigError("devices[%d] (%s): %s" % (dev.index, dev.name, exc))

        for module in dev.install:
            try:
                lab.install_module(dev_id, module)
            except KeyError:
                raise ConfigError(
                    "devices[%d] (%s): module %r is not in the template library"
                    % (dev.index, dev.name, module))
            except ValueError as exc:
                raise ConfigError(
                    "devices[%d] (%s): cannot install %r: %s"
                    % (dev.index, dev.name, module, exc))

        if dev.description:
            engine = lab._els[dev_id].find("ENGINE")
            node = engine.find("DESCRIPTION")
            if node is None:
                node = ET.SubElement(engine, "DESCRIPTION")
            node.text = dev.description

        if dev.dhcp is not None:
            port = lab._els[dev_id].find(".//PORT")
            if port is not None:
                node = port.find("PORT_DHCP_ENABLE")
                if node is None:
                    node = ET.SubElement(port, "PORT_DHCP_ENABLE")
                node.text = "true" if dev.dhcp else "false"

        ids[dev.name] = dev_id

    # --- 5. links --------------------------------------------------------- #
    for link, a_port, b_port, kind in plan:
        kwargs = {}
        if kind == "serial":
            dce_id = ids[link.dce]
            kwargs["dce"] = dce_id
            kwargs["clock"] = link.clock
        try:
            lab.link(ids[link.a], a_port, ids[link.b], b_port, kind=kind, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- surface library errors clearly
            raise ConfigError("links[%d] (%s <-> %s): %s"
                              % (link.index, link.a, link.b, exc))
        result.links.append((link.a, a_port, link.b, b_port, kind))

    # --- 6. power --------------------------------------------------------- #
    for dev in spec.devices:
        copper_power(lab, ids[dev.name])

    # --- 7. configs ------------------------------------------------------- #
    macs: dict[str, str] = {}
    for dev in spec.devices:
        mac = mac_of(lab, ids[dev.name])
        if mac:
            macs[dev.name] = mac
    result.macs = macs

    for dev in spec.devices:
        if dev.cfg is None:
            continue
        lines = _expand_cfg(dev.cfg, dev, macs)
        set_cfg(lab, ids[dev.name], lines)

    # --- 8. save ---------------------------------------------------------- #
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lab.save(str(out_path))
    result.size = out_path.stat().st_size
    return result
