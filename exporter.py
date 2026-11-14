#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exporter.py -- turn a .pkt back into a pkt_create YAML description.

The generated YAML is the inverse of :mod:`pkt_builder.builder`: it can be fed
straight back to ``pkt_create.py -c`` to rebuild the same lab.

What is recovered
-----------------
* every device: ``model``, ``name``, ``pos`` (from ``WORKSPACE/LOGICAL``),
  ``install`` (installed interface cards), ``power`` (only when off),
  ``pc_ip``/``dhcp`` for end devices, ``description``, ``cfg``
* every link with explicit ports, so re-import does not have to guess
* serial links: ``dce`` (from ``DCEDEV``) and ``clock`` (from the DCE port's
  ``CLOCKRATE``)
* the seed: the source file itself, because its ``VERSION`` is what makes the
  result loadable on the same Packet Tracer
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pkt_core.codec.container import decode

__all__ = ["export_yaml", "dump_yaml", "PktExportError"]

_COPPER = ("eCopperFastEthernet", "eCopperGigabitEthernet", "eCopperEthernet")


class PktExportError(ValueError):
    """The .pkt could not be read or has no usable topology."""


# --------------------------------------------------------------------------- #
# YAML emission
# --------------------------------------------------------------------------- #
_BARE_OK = re.compile(r"^[A-Za-z0-9_./+=@$][A-Za-z0-9_./+=@$ ()-]*$")
_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "~"}


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (not text or text.strip() != text or text.lower() in _RESERVED
            or not _BARE_OK.match(text) or re.fullmatch(r"[-+]?\d+(\.\d+)?", text)
            or text.endswith(":")):
        return json.dumps(text, ensure_ascii=False)
    return text


def _inline(value: object) -> str:
    """Render a scalar or flat list/map on one line (flow style)."""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_inline(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join("%s: %s" % (_scalar(k), _inline(v))
                               for k, v in value.items()) + "}"
    return _scalar(value)


def _block_text(key: str, lines: list[str], indent: str) -> list[str]:
    out = ["%s%s: |" % (indent, key)]
    for line in lines:
        out.append((indent + "  " + line) if line else "")
    return out


def dump_yaml(doc: dict) -> str:
    """Render the exporter's document as YAML text."""
    out: list[str] = []
    if doc.get("header"):
        out.extend("# " + line for line in doc["header"])
        out.append("")

    if doc.get("seed"):
        out.append("seed: %s" % _scalar(doc["seed"]))
        out.append("")

    out.append("devices:")
    for dev in doc["devices"]:
        first = True
        for key in ("model", "name"):
            prefix = "  - " if first else "    "
            out.append("%s%s: %s" % (prefix, key, _scalar(dev[key])))
            first = False
        if dev.get("pos"):
            out.append("    pos: [%d, %d]" % tuple(dev["pos"]))
        if dev.get("install"):
            out.append("    install: %s" % _inline(dev["install"]))
        if dev.get("power") is False:
            out.append("    power: false")
        if dev.get("description"):
            out.append("    description: %s" % _scalar(dev["description"]))
        if dev.get("pc_ip"):
            out.append("    pc_ip: %s" % _inline(list(dev["pc_ip"])))
        if dev.get("dhcp") is not None:
            out.append("    dhcp: %s" % ("true" if dev["dhcp"] else "false"))
        cfg = dev.get("cfg")
        if cfg:
            out.extend(_block_text("cfg", cfg, "    "))
        out.append("")

    if doc.get("links"):
        out.append("links:")
        for link in doc["links"]:
            out.append("  - %s" % _inline(link))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# XML -> model
# --------------------------------------------------------------------------- #
def _installed_modules(dev: ET.Element) -> list[str]:
    """Interface cards sitting in the device's eInterfaceCard bays."""
    out: list[str] = []
    for slot in dev.iter("SLOT"):
        if slot.findtext("TYPE") != "eInterfaceCard":
            continue
        module = slot.find("MODULE")
        if module is None:
            continue
        model = (module.findtext("MODEL") or "").strip()
        # the module's own nested eInterfaceCard slot repeats the card
        if model and model not in out:
            out.append(model)
    return out


def _cfg_lines(dev: ET.Element) -> list[str] | None:
    rc = dev.find("ENGINE/RUNNINGCONFIG")
    if rc is None:
        return None
    lines = [(line.text or "") for line in rc.findall("LINE")]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or None


def _is_ios_device(dev: ET.Element) -> bool:
    """IOS devices carry a running-config; PCs/servers/phones do not."""
    rc = dev.find("ENGINE/RUNNINGCONFIG")
    return rc is not None and bool(rc.findall("LINE"))


def _end_device_net(dev: ET.Element) -> tuple[tuple[str, str, str] | None, bool | None]:
    """IP/gateway set on an end device (PC, server); the router templates carry
    a leftover NIC address that is not part of the lab, so only end devices are
    considered."""
    port = dev.find(".//PORT")
    if port is None:
        return None, None
    dhcp = (port.findtext("PORT_DHCP_ENABLE") or "").strip().lower() == "true"
    ip = (port.findtext("IP") or "").strip()
    mask = (port.findtext("SUBNET") or "").strip()
    gateway = (port.findtext("PORT_GATEWAY") or "").strip()
    if not ip or dhcp:
        return None, (dhcp if dhcp else None)
    return (ip, mask, gateway), (False if port.find("PORT_DHCP_ENABLE") is not None else None)


def _serial_clock(dev: ET.Element, port_name: str) -> int:
    serial = [p for p in dev.iter("PORT") if p.findtext("TYPE") == "eSmartSerial"]
    try:
        idx = int(str(port_name).split("/")[-1])
    except ValueError:
        idx = 0
    if idx >= len(serial):
        return 64000
    try:
        return int(serial[idx].findtext("CLOCKRATE") or 64000)
    except ValueError:
        return 64000


def export_yaml(pkt_path: str | Path, source_label: str | None = None,
                seed_value: str | None = None) -> str:
    """Read ``pkt_path`` and return the YAML description as text.

    ``seed_value`` is written as the ``seed:`` entry; by default the .pkt's own
    file name, because that file's ``VERSION`` is what makes the rebuild load.
    """
    pkt_path = Path(pkt_path)
    try:
        root = ET.fromstring(decode(str(pkt_path), None).xml)
    except Exception as exc:  # noqa: BLE001 -- any decode failure is one error
        raise PktExportError("cannot read %s: %s" % (pkt_path, exc))

    version = root.findtext("VERSION") or ""
    by_sid: dict[str, ET.Element] = {}
    names: dict[str, str] = {}
    devices: list[dict] = []

    for dev in root.findall(".//NETWORK/DEVICES/DEVICE"):
        engine = dev.find("ENGINE")
        if engine is None:
            continue
        sid = engine.findtext("SAVE_REF_ID") or ""
        ty = engine.find("TYPE")
        model = (ty.get("model") if ty is not None else "") or ""
        name = engine.findtext("NAME") or ""
        if not model or not name:
            continue
        by_sid[sid] = dev
        names[sid] = name

        entry: dict = {"model": model, "name": name}

        logical = dev.find("WORKSPACE/LOGICAL")
        if logical is not None and logical.findtext("X") is not None:
            try:
                entry["pos"] = (int(float(logical.findtext("X"))),
                                int(float(logical.findtext("Y"))))
            except (TypeError, ValueError):
                pass

        modules = _installed_modules(dev)
        if modules:
            entry["install"] = modules if len(modules) > 1 else modules[0]

        power = (engine.findtext("POWER") or "true").strip().lower()
        if power != "true":
            entry["power"] = False

        description = (engine.findtext("DESCRIPTION") or "").strip()
        if description:
            entry["description"] = description

        cfg = _cfg_lines(dev)
        if cfg:
            entry["cfg"] = cfg

        pc_ip, dhcp = (None, None) if _is_ios_device(dev) else _end_device_net(dev)
        if pc_ip:
            entry["pc_ip"] = pc_ip
        if dhcp is not None:
            entry["dhcp"] = dhcp

        devices.append(entry)

    if not devices:
        raise PktExportError("%s contains no devices" % pkt_path)

    links: list[list] = []
    for link in root.findall(".//NETWORK/LINKS/LINK"):
        cab = link.find("CABLE")
        if cab is None:
            continue
        kind = (link.findtext("TYPE") or "").strip()
        ports = [p.text or "" for p in cab.findall("PORT")]
        ends = [cab.findtext("FROM") or "", cab.findtext("TO") or ""]
        if len(ports) != 2 or ends[0] not in names or ends[1] not in names:
            continue
        item: list = [names[ends[0]], ports[0], names[ends[1]], ports[1]]
        if kind == "eSerial":
            dce_sid = cab.findtext("DCEDEV") or ends[0]
            dce_name = names.get(dce_sid, names[ends[0]])
            dce_port = cab.findtext("DCEPORT") or (
                ports[0] if dce_sid == ends[0] else ports[1])
            dce_dev = by_sid.get(dce_sid, by_sid.get(ends[0]))
            clock = _serial_clock(dce_dev, dce_port) if dce_dev is not None else 64000
            item.extend(["serial", dce_name, clock])
        else:
            item.append("copper")
        links.append(item)

    doc = {
        "header": [
            "Exported from %s by pkt_create.py --export" % (source_label or pkt_path.name),
            "Packet Tracer VERSION %s" % (version or "unknown"),
            "",
            "Rebuild with:",
            "  python pkt_create.py -c <this file> -i <out.pkt>",
        ],
        "seed": seed_value or pkt_path.name,
        "devices": devices,
        "links": links,
    }
    return dump_yaml(doc)
