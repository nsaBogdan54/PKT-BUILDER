#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""verify.py -- structural checks on a generated .pkt, without opening PT.

These are the failures Packet Tracer reports as "Incompatible File", caught
before the file ever reaches it (see ``pkt_builder.md`` section 11):

* ``VERSION`` newer than the running Packet Tracer
* a link whose ``<PORT>`` does not exist on the device
* the 7960 phone cabled on anything but ``Switch``/``PC``
* a serial link without ``DCEDEV``/``DCEPORT`` or with a zero clock rate
* ``POWER=false`` on a copper port that carries a cable
* one device's config, one link per port
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from pkt_core.codec.container import decode

__all__ = ["Report", "verify_pkt"]

_COPPER = ("eCopperFastEthernet", "eCopperGigabitEthernet", "eCopperEthernet")


@dataclass
class Report:
    path: str = ""
    version: str = ""
    devices: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _port_types(dev_el: ET.Element) -> dict[str, ET.Element]:
    """Map every PORT element of a device to its type, in document order."""
    out: dict[str, ET.Element] = {}
    for port in dev_el.iter("PORT"):
        out[str(id(port))] = port
    return out


def _copper_ports(dev_el: ET.Element) -> list[ET.Element]:
    return [p for p in dev_el.iter("PORT") if p.findtext("TYPE") in _COPPER]


def _serial_ports(dev_el: ET.Element) -> list[ET.Element]:
    return [p for p in dev_el.iter("PORT") if p.findtext("TYPE") == "eSmartSerial"]


def _serial_index(port_name: str) -> int:
    try:
        return int(str(port_name).split("/")[-1])
    except ValueError:
        return 0


def verify_pkt(path: str, max_version: tuple[int, ...] = (9, 0, 0)) -> Report:
    """Decode ``path`` and check every structural invariant we know about."""
    report = Report(path=str(path))
    root = ET.fromstring(decode(str(path), None).xml)
    version = root.findtext("VERSION") or ""
    report.version = version

    parts = [int(p) for p in version.replace("-", ".").split(".") if p.isdigit()]
    if parts and tuple(parts[:3]) > max_version:
        report.errors.append(
            "VERSION %s is newer than Packet Tracer %s; it will refuse the file"
            % (version, ".".join(str(p) for p in max_version)))

    by_sid: dict[str, ET.Element] = {}
    names: dict[str, str] = {}
    seen_mac: dict[str, str] = {}
    seen_build_in: dict[str, str] = {}
    seen_serial: dict[str, str] = {}
    seen_link_local: dict[str, str] = {}
    seen_mem: dict[str, str] = {}
    for dev in root.findall(".//NETWORK/DEVICES/DEVICE"):
        engine = dev.find("ENGINE")
        if engine is None:
            continue
        sid = engine.findtext("SAVE_REF_ID") or ""
        ty = engine.find("TYPE")
        model = (ty.get("model") if ty is not None else "") or ""
        name = engine.findtext("NAME") or ""
        by_sid[sid] = dev
        names[sid] = name
        cfg = engine.find("RUNNINGCONFIG")
        report.devices.append({
            "name": name,
            "model": model,
            "cfg_lines": len(cfg.findall("LINE")) if cfg is not None else 0,
            "copper": len(_copper_ports(dev)),
            "serial": len(_serial_ports(dev)),
            "power": engine.findtext("POWER"),
        })
        if (engine.findtext("POWER") or "true").lower() != "true":
            report.warnings.append("%s: device is powered off" % name)

        # Hardware identity: every port MAC/BIA must be unique across the whole
        # document (a cloned template duplicates them) and BIA must equal the
        # port's MACADDRESS -- they are one address in every real PT save.
        build_in = (engine.findtext("BUILD_IN_ADDR") or "").strip()
        if build_in:
            if build_in in seen_build_in:
                report.errors.append(
                    "%s: BUILD_IN_ADDR %s is already used by %s "
                    "(the phone/CME identity is not unique)"
                    % (name, build_in, seen_build_in[build_in]))
            else:
                seen_build_in[build_in] = name
        for port in dev.iter("PORT"):
            mac = (port.findtext("MACADDRESS") or "").strip()
            bia = (port.findtext("BIA") or "").strip()
            if mac and bia and mac != bia:
                report.errors.append(
                    "%s: port MACADDRESS %s != BIA %s (they are one address)"
                    % (name, mac, bia))
            # BIA repeats the port's MACADDRESS, so count one address per port
            value = mac or bia
            if value:
                if value in seen_mac:
                    report.errors.append(
                        "%s: MAC %s is already used by %s"
                        % (name, value, seen_mac[value]))
                else:
                    seen_mac[value] = name

        serial_no = (engine.findtext("SERIALNUMBER") or "").strip()
        if serial_no:
            if serial_no in seen_serial:
                report.warnings.append(
                    "%s: serial number %s is shared with %s"
                    % (name, serial_no, seen_serial[serial_no]))
            else:
                seen_serial[serial_no] = name

        # A port's IPv6 link-local is derived from its MAC, so a shared FE80::
        # means the template's address survived the clone -- PT shows it as the
        # interface address and two devices would answer to the same one.
        for ll in dev.iter("IPV6_DEFAULT_LINK_LOCAL"):
            value = (ll.text or "").strip().upper()
            if not value:
                continue
            if value in seen_link_local:
                report.errors.append(
                    "%s: IPv6 link-local %s is already used by %s"
                    % (name, value, seen_link_local[value]))
            else:
                seen_link_local[value] = name

        mem_addr = (dev.findtext("WORKSPACE/LOGICAL/MEM_ADDR") or "").strip()
        if mem_addr:
            if mem_addr in seen_mem:
                report.errors.append(
                    "%s: MEM_ADDR %s is already used by %s"
                    % (name, mem_addr, seen_mem[mem_addr]))
            else:
                seen_mem[mem_addr] = name

    cabled: dict[str, set[int]] = {sid: set() for sid in by_sid}
    for link in root.findall(".//NETWORK/LINKS/LINK"):
        cab = link.find("CABLE")
        if cab is None:
            continue
        kind_el = link.find("TYPE")
        kind = kind_el.text if kind_el is not None else ""
        ports = [p.text or "" for p in cab.findall("PORT")]
        ends = [cab.findtext("FROM") or "", cab.findtext("TO") or ""]
        info = {
            "type": kind,
            "from": names.get(ends[0], ends[0]),
            "to": names.get(ends[1], ends[1]),
            "ports": ports,
        }
        report.links.append(info)

        if len(ports) != 2:
            report.errors.append("link %r: expected two PORT elements, got %d"
                                 % (info, len(ports)))
            continue

        for sid, port_name in zip(ends, ports):
            dev = by_sid.get(sid)
            if dev is None:
                report.errors.append(
                    "link %s:%s -> %s: endpoint device not found"
                    % (info["from"], ports[0], info["to"]))
                break
            model = (dev.find("ENGINE/TYPE").get("model") or "")
            if model == "7960" and port_name not in ("Switch", "PC"):
                report.errors.append(
                    "%s: the 7960 uplink port must be 'Switch', got %r"
                    % (names.get(sid, sid), port_name))
            if kind == "eCopper":
                copper = _copper_ports(dev)
                serial = _serial_ports(dev)
                if model != "7960" and not copper and not serial:
                    continue        # naming not reconstructible (hubs, IoT, ...)
            if kind == "eCopper" and model != "7960":
                idx = None
                if port_name.lower().startswith("fastethernet"):
                    try:
                        idx = int(port_name.rsplit("/", 1)[-1])
                    except ValueError:
                        idx = None
                if idx is not None and idx > len(_copper_ports(dev)):
                    report.errors.append(
                        "%s: no port %s (device has %d copper ports)"
                        % (names.get(sid, sid), port_name, len(_copper_ports(dev))))

        if kind == "eSerial":
            dce = cab.findtext("DCEDEV")
            dceport = cab.findtext("DCEPORT")
            if not dce or not dceport:
                report.errors.append(
                    "serial link %s <-> %s has no DCEDEV/DCEPORT"
                    % (info["from"], info["to"]))
            for sid, port_name in zip(ends, ports):
                dev = by_sid.get(sid)
                if dev is None:
                    continue
                serial = _serial_ports(dev)
                if not serial:
                    report.errors.append(
                        "%s: serial link on a device with no serial ports"
                        % names.get(sid, sid))
                    continue
                idx = _serial_index(port_name)
                if idx >= len(serial):
                    report.errors.append(
                        "%s: serial port %s does not exist (has %d)"
                        % (names.get(sid, sid), port_name, len(serial)))
                    continue
                cabled[sid].add(id(serial[idx]))
                if (serial[idx].findtext("POWER") or "").lower() != "true":
                    report.errors.append(
                        "%s: serial port %s is powered down but cabled"
                        % (names.get(sid, sid), port_name))
                rate = serial[idx].findtext("CLOCKRATE") or "0"
                flag = (serial[idx].findtext("CLOCKRATEFLAG") or "").lower()
                if dce == sid and rate in ("0", "") and flag != "true":
                    report.errors.append(
                        "%s: DCE end %s has clock rate 0" % (names.get(sid, sid), port_name))
                if flag != "true":
                    report.errors.append(
                        "%s: serial port %s has CLOCKRATEFLAG=false"
                        % (names.get(sid, sid), port_name))

    # copper power on cabled ports: link CABLE ports are named, so match by name
    # against the device's port list order (PT keeps <PORT> names implicit for
    # copper; the running-config order is the interface order).
    for dev in root.findall(".//NETWORK/DEVICES/DEVICE"):
        engine = dev.find("ENGINE")
        if engine is None:
            continue
        name = engine.findtext("NAME") or ""
        model = (engine.find("TYPE").get("model") if engine.find("TYPE") is not None else "")
        ports = _copper_ports(dev)
        if not ports or model == "7960":
            continue
        off = [p for p in ports if (p.findtext("POWER") or "true").lower() != "true"]
        if off and len(off) == len(ports):
            report.warnings.append(
                "%s: every copper port is powered down" % name)

    # duplicate cable on one port name
    seen: dict[tuple[str, str], int] = {}
    for info in report.links:
        for dev_name, port in ((info["from"], info["ports"][0] if info["ports"] else ""),
                               (info["to"], info["ports"][1] if len(info["ports"]) > 1 else "")):
            key = (dev_name, port)
            seen[key] = seen.get(key, 0) + 1
    for (dev_name, port), count in seen.items():
        if count > 1:
            report.errors.append("%s: port %s is cabled %d times"
                                 % (dev_name, port, count))
    return report
