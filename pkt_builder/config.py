#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py -- the pkt_builder YAML schema: parsing, normalisation, validation.

The file describes a whole lab::

    seed: donors/lab3_donor.pkt          # optional donor .pkt (version!); relative to this file
    defaults:                            # optional per-device defaults
      power: true

    devices:
      - model: 2911
        name: HQswitch
        pos: 200, 235                    # optional; omit to auto-place
        install: HWIC-2T                 # string or list
        cfg: |
          hostname HQswitch
           ip address 10.0.0.1 255.255.255.0

    links:
      - auto: [CMERouter, CMESwitch]
      - auto: [CMERouter, RemoteRouter, dce: CMERouter, clock: 64000]
      - [CMESwitch, Fa0/2, PH1, Switch]                    # kind from port names
      - [CMESwitch, Fa0/2, PH1, Switch, copper]            # explicit kind
      - [CMERouter, Serial0/0/0, RemoteRouter, Serial0/0, serial, CMERouter, 64000]

Link list entries are positional::

    [device_a, port_a, device_b, port_b, (kind), (dce), (clock)]
       [1]       [2]      [3]       [4]     [5]     [6]    [7]

Omitted trailing elements default sensibly: ``kind`` is inferred from the port
names, ``clock`` is 64000, and ``dce`` defaults to side A for serial links.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ConfigError",
    "DeviceSpec",
    "LinkSpec",
    "LabSpec",
    "parse_spec",
    "PORT_KINDS",
]

PORT_KINDS = ("copper", "serial")

_KIND_ALIASES = {
    "copper": "copper", "straight": "copper", "straight-through": "copper",
    "straightthrough": "copper", "crossover": "copper", "cross": "copper",
    "fiber": "copper", "fibre": "copper", "ethernet": "copper",
    "serial": "serial", "ser": "serial",
}

_CFG_KEY_ALIASES = ("cfg", "config", "ios_config", "running_config")


class ConfigError(ValueError):
    """A problem in the YAML file, reported with a path inside the document."""


@dataclass
class DeviceSpec:
    model: str
    name: str
    x: int | None = None
    y: int | None = None
    install: list[str] = field(default_factory=list)
    power: bool = True
    cfg: list[str] | None = None
    pc_ip: tuple[str, str, str] | None = None
    dhcp: bool | None = None
    description: str | None = None
    index: int = 0


@dataclass
class LinkSpec:
    """A cable.  ``a_port``/``b_port`` are None for ``auto`` links."""

    a: str
    b: str
    a_port: str | None = None
    b_port: str | None = None
    kind: str | None = None
    dce: str | None = None
    clock: int = 64000
    auto: bool = False
    index: int = 0


@dataclass
class LabSpec:
    devices: list[DeviceSpec] = field(default_factory=list)
    links: list[LinkSpec] = field(default_factory=list)
    seed: str | None = None

    def device(self, name: str) -> DeviceSpec:
        for d in self.devices:
            if d.name == name:
                return d
        raise ConfigError("unknown device %r" % (name,))


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _as_list(value: Any, where: str) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    raise ConfigError("%s: expected a list, got %r" % (where, type(value).__name__))


def _pos(value: Any, where: str) -> tuple[int, int]:
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ConfigError("%s: pos needs exactly two numbers" % where)
        x, y = value
    else:
        parts = re.split(r"[,\s]+", str(value).strip())
        parts = [p for p in parts if p]
        if len(parts) != 2:
            raise ConfigError("%s: pos must look like '200, 235', got %r" % (where, value))
        x, y = parts
    try:
        return int(round(float(x))), int(round(float(y)))
    except (TypeError, ValueError):
        raise ConfigError("%s: pos values must be numbers, got %r" % (where, value))


def _cfg_lines(value: Any, where: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("\r\n", "\n").replace("\r", "\n")
        if text.endswith("\n"):
            text = text[:-1]
        if not text.strip():
            return []
        return text.split("\n")
    if isinstance(value, (list, tuple)):
        return ["" if v is None else str(v) for v in value]
    raise ConfigError("%s: cfg must be a string or a list of lines" % where)


def _install(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if not isinstance(v, str) or not v.strip():
                raise ConfigError("%s: install entries must be non-empty strings" % where)
            out.append(v.strip())
        return out
    raise ConfigError("%s: install must be a string or a list of strings" % where)


def _pc_ip(value: Any, where: str) -> tuple[str, str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p for p in re.split(r"[,\s]+", value.strip()) if p]
    else:
        parts = [str(v) for v in _as_list(value, where)]
    if len(parts) == 2:
        parts.append("")
    if len(parts) != 3:
        raise ConfigError(
            "%s: pc_ip must be 'ip, mask, gateway' (gateway may be empty)" % where)
    return parts[0], parts[1], parts[2]


# --------------------------------------------------------------------------- #
# devices
# --------------------------------------------------------------------------- #
def _device(raw: Any, where: str, defaults: dict, index: int) -> DeviceSpec:
    if isinstance(raw, str):
        # shorthand: "2911 HQswitch" / "2911:HQswitch"
        parts = [p for p in re.split(r"[\s:]+", raw.strip()) if p]
        if len(parts) != 2:
            raise ConfigError("%s: device shorthand must be 'MODEL NAME'" % where)
        raw = {"model": parts[0], "name": parts[1]}
    if not isinstance(raw, dict):
        raise ConfigError("%s: expected a mapping with model/name" % where)

    merged = dict(defaults)
    merged.update(raw)

    model = merged.get("model")
    if isinstance(model, bool) or model is None:
        raise ConfigError("%s: 'model' is required" % where)
    # YAML turns a bare `model: 2811` into an int; PT model names are strings
    model = str(model).strip()
    if not model:
        raise ConfigError("%s: 'model' is required" % where)
    name = merged.get("name")
    if isinstance(name, bool) or name is None:
        raise ConfigError("%s: 'name' is required" % where)
    name = str(name).strip()
    if not name:
        raise ConfigError("%s: 'name' is required" % where)

    x = y = None
    if merged.get("pos") is not None:
        x, y = _pos(merged["pos"], where)

    cfg = None
    for key in _CFG_KEY_ALIASES:
        if key in merged:
            cfg = _cfg_lines(merged[key], "%s.%s" % (where, key))
            break

    power = merged.get("power", True)
    if not isinstance(power, bool):
        raise ConfigError("%s: power must be true/false" % where)

    dhcp = merged.get("dhcp")
    if dhcp is not None and not isinstance(dhcp, bool):
        raise ConfigError("%s: dhcp must be true/false" % where)

    desc = merged.get("description") or merged.get("desc")

    return DeviceSpec(
        model=model,
        name=name,
        x=x, y=y,
        install=_install(merged.get("install"), where + ".install"),
        power=power,
        cfg=cfg,
        pc_ip=_pc_ip(merged.get("pc_ip"), where + ".pc_ip"),
        dhcp=dhcp,
        description=str(desc) if desc is not None else None,
        index=index,
    )


# --------------------------------------------------------------------------- #
# links
# --------------------------------------------------------------------------- #
def _link_kind(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError("%s: cable kind must be a string" % where)
    kind = _KIND_ALIASES.get(value.strip().lower())
    if kind is None:
        raise ConfigError(
            "%s: unknown cable kind %r (use %s)" % (where, value, " or ".join(PORT_KINDS)))
    return kind


def _merge_hints(items: list, where: str) -> tuple[list[str], dict]:
    """Split a flow sequence into names and a merged hints mapping."""
    names: list[str] = []
    hints: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            hints.update({str(k).lower(): v for k, v in item.items()})
        elif isinstance(item, str):
            names.append(item.strip())
        else:
            raise ConfigError("%s: unexpected link element %r" % (where, item))
    return names, hints


def _link(raw: Any, where: str, index: int) -> LinkSpec:
    if isinstance(raw, dict) and "auto" in raw:
        auto = raw["auto"]
        if isinstance(auto, str):
            auto = [p for p in re.split(r"[\s,]+", auto) if p]
        items = _as_list(auto, where + ".auto")
        names, hints = _merge_hints(items, where + ".auto")
        if len(names) != 2:
            raise ConfigError(
                "%s.auto: expected two device names, got %d (%s)"
                % (where, len(names), ", ".join(names) or "none"))
        kind = _link_kind(hints["kind"], where) if "kind" in hints else None
        if kind is None and ("dce" in hints or "clock" in hints):
            kind = "serial"
        clock = hints.get("clock", 64000)
        try:
            clock = int(clock)
        except (TypeError, ValueError):
            raise ConfigError("%s: clock must be an integer" % where)
        dce = hints.get("dce")
        return LinkSpec(a=names[0], b=names[1], kind=kind,
                        dce=str(dce) if dce is not None else None,
                        clock=clock, auto=True, index=index)

    if isinstance(raw, dict):
        a = raw.get("a") or raw.get("from") or raw.get("device_a")
        b = raw.get("b") or raw.get("to") or raw.get("device_b")
        if not a or not b:
            raise ConfigError("%s: link mapping needs 'a' and 'b'" % where)
        a_port = raw.get("a_port") or raw.get("from_port") or raw.get("port_a")
        b_port = raw.get("b_port") or raw.get("to_port") or raw.get("port_b")
        kind = _link_kind(raw["kind"], where) if raw.get("kind") else None
        clock = raw.get("clock", 64000)
        try:
            clock = int(clock)
        except (TypeError, ValueError):
            raise ConfigError("%s: clock must be an integer" % where)
        dce = raw.get("dce")
        return LinkSpec(a=str(a), b=str(b),
                        a_port=str(a_port) if a_port else None,
                        b_port=str(b_port) if b_port else None,
                        kind=kind, dce=str(dce) if dce is not None else None,
                        clock=clock, auto=not (a_port and b_port), index=index)

    if isinstance(raw, str):
        raw = [p.strip() for p in re.split(r"[\s,]+", raw) if p]

    items = _as_list(raw, where)
    if not 2 <= len(items) <= 7:
        raise ConfigError(
            "%s: a link list needs 2..7 elements "
            "[device_a, port_a, device_b, port_b, kind, dce, clock]; got %d"
            % (where, len(items)))

    if len(items) == 2:
        return LinkSpec(a=str(items[0]), b=str(items[1]), auto=True, index=index)
    if len(items) == 3:
        raise ConfigError(
            "%s: 3 elements is ambiguous; use [a, b] for auto or "
            "[device_a, port_a, device_b, port_b]" % where)

    spec = LinkSpec(
        a=str(items[0]), a_port=str(items[1]),
        b=str(items[2]), b_port=str(items[3]), index=index,
    )
    if len(items) >= 5 and items[4] is not None:
        spec.kind = _link_kind(items[4], where)
    if len(items) >= 6 and items[5] is not None:
        spec.dce = str(items[5])
    if len(items) >= 7 and items[6] is not None:
        try:
            spec.clock = int(items[6])
        except (TypeError, ValueError):
            raise ConfigError("%s: clock must be an integer, got %r" % (where, items[6]))
    return spec


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
def parse_spec(doc: Any, source: str = "<config>") -> LabSpec:
    """Normalise a loaded YAML document into a :class:`LabSpec`."""
    if doc is None:
        raise ConfigError("%s: empty document" % source)
    if isinstance(doc, list):
        doc = {"devices": doc}
    if not isinstance(doc, dict):
        raise ConfigError("%s: the document must be a mapping" % source)

    spec = LabSpec()

    seed = doc.get("seed") or doc.get("donor")
    if seed is not None:
        if not isinstance(seed, str):
            raise ConfigError("%s: seed must be a file path" % source)
        spec.seed = seed

    defaults = doc.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("%s: defaults must be a mapping" % source)
    defaults = {str(k): v for k, v in defaults.items()}

    raw_devices = doc.get("devices")
    if raw_devices is None and ("model" in doc or "name" in doc):
        # convenience: a single device described at the top level
        raw_devices = [{k: v for k, v in doc.items()
                        if k not in ("devices", "links", "seed", "donor", "defaults")}]
    devices = _as_list(raw_devices, "devices")
    if not devices:
        raise ConfigError("%s: no devices defined" % source)

    seen: dict[str, int] = {}
    for i, raw in enumerate(devices):
        where = "devices[%d]" % i
        dev = _device(raw, where, defaults, i)
        if dev.name in seen:
            raise ConfigError(
                "%s: duplicate device name %r (already used by devices[%d])"
                % (where, dev.name, seen[dev.name]))
        seen[dev.name] = i
        spec.devices.append(dev)

    names = set(seen)
    for i, raw in enumerate(_as_list(doc.get("links"), "links")):
        where = "links[%d]" % i
        link = _link(raw, where, i)
        for end in (link.a, link.b):
            if end not in names:
                raise ConfigError("%s: unknown device %r (defined: %s)"
                                  % (where, end, ", ".join(sorted(names))))
        if link.a == link.b:
            raise ConfigError("%s: both ends are the same device %r" % (where, link.a))
        if link.dce is not None and link.dce not in (link.a, link.b):
            raise ConfigError(
                "%s: dce %r must be one of the linked devices (%s, %s)"
                % (where, link.dce, link.a, link.b))
        if link.kind == "copper" and link.dce:
            raise ConfigError("%s: 'dce' only applies to serial links" % where)
        spec.links.append(link)

    return spec
