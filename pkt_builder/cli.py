#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py -- command line entry point of :mod:`pkt_builder`.

Builds a Cisco Packet Tracer .pkt from a YAML description, and exports a .pkt
back to YAML.

Usage::

    python -m pkt_builder -c %USERPROFILE%\\configs\\configuration.yml -i %USERPROFILE%\\projects\\my_new.pkt

    python -m pkt_builder -c lab.yml -i lab.pkt --seed my_pt.pkt
    python -m pkt_builder -c lab.yml -i lab.pkt --check-only
    python -m pkt_builder -c lab.yml -i lab.pkt --accept

    python -m pkt_builder --export lab.pkt -o lab.yml

The YAML schema is documented in ``pkt_builder/config.py`` and in README.md.
Exit codes: 0 = success, 1 = build/validation error, 2 = Packet Tracer was not
available (``--accept`` only).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent      # pkt_builder/pkt_builder/
PROJECT = HERE.parent                               # repository root
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))                    # import pkt_builder.* and pkt_core

from pkt_builder import miniyaml                            # noqa: E402
from pkt_builder.config import ConfigError, parse_spec      # noqa: E402
from pkt_builder.builder import build_lab, seed_version     # noqa: E402
from pkt_builder.exporter import PktExportError, export_yaml  # noqa: E402
from pkt_builder.ports import PortError                     # noqa: E402

DEFAULT_SEED = PROJECT / "donors" / "lab3_donor.pkt"
PT_ACCEPT = PROJECT / "tools" / "pt_accept.ps1"


# --------------------------------------------------------------------------- #
# path handling
# --------------------------------------------------------------------------- #
_WIN_ENV = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def expand_path(text: str, base: pathlib.Path | None = None) -> pathlib.Path:
    """Expand ``~``, ``%VAR%``, ``$VAR`` and resolve relative to ``base``.

    A relative path is taken relative to the config file's directory (falling
    back to the working directory) -- that is what people mean when the config
    says ``seed: donors/lab3_donor.pkt`` (relative to the config, and the
    default seed lives in ``pkt_builder/donors/``).
    """
    text = str(text).strip().strip('"').strip("'")
    text = _WIN_ENV.sub(lambda m: os.environ.get(m.group(1), m.group(0)), text)
    text = os.path.expandvars(text)
    path = pathlib.Path(os.path.expanduser(text))
    if not path.is_absolute():
        path = (base or pathlib.Path.cwd()) / path
    return path.resolve()


# --------------------------------------------------------------------------- #
# YAML loading
# --------------------------------------------------------------------------- #
def load_config(path: pathlib.Path):
    """Load the YAML file, preferring PyYAML and falling back to miniyaml.

    PyYAML is not required -- the project rule is a stock interpreter.  When it
    *is* installed it is used, because its diagnostics for malformed files are
    better; ``miniyaml`` covers the same subset when it is not.
    """
    text = path.read_text(encoding="utf-8-sig")
    backend = os.environ.get("PKT_BUILDER_YAML", "").strip().lower()
    if backend in ("mini", "miniyaml", "builtin"):
        try:
            return miniyaml.load(text), "miniyaml"
        except miniyaml.YamlError as exc:
            raise ConfigError("%s: invalid YAML: %s" % (path.name, exc))
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            return miniyaml.load(text), "miniyaml"
        except miniyaml.YamlError as exc:
            raise ConfigError("%s: invalid YAML: %s" % (path.name, exc))
    try:
        return yaml.safe_load(text), "pyyaml"
    except yaml.YAMLError as exc:
        raise ConfigError("%s: invalid YAML: %s" % (path.name, exc))


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def print_plan(spec, out_path, seed, parsed_with: str, source: str = "",
               verbose: bool = False) -> None:
    print("config      : %s (%s)" % (source or "?", parsed_with))
    print("seed        : %s%s" % (seed, "  [VERSION %s]" % seed_version(seed)
                                  if seed.exists() else "  [MISSING]"))
    print("output      : %s" % out_path)
    print("devices     : %d" % len(spec.devices))
    for dev in spec.devices:
        extra = []
        if dev.install:
            extra.append("modules=" + ",".join(dev.install))
        if dev.x is not None:
            extra.append("pos=%d,%d" % (dev.x, dev.y))
        if dev.cfg is not None:
            extra.append("cfg=%d lines" % len(dev.cfg))
        print("  %-16s %-12s %s" % (dev.name, dev.model, " ".join(extra)))
        if verbose and dev.cfg:
            for line in dev.cfg:
                print("      | %s" % line)
    print("links       : %d" % len(spec.links))
    for link in spec.links:
        if link.auto:
            print("  %s <-> %s  (auto%s)" % (link.a, link.b,
                                             " serial" if link.kind == "serial" else ""))
        else:
            print("  %s:%s <-> %s:%s%s" % (link.a, link.a_port, link.b, link.b_port,
                                           " [" + link.kind + "]" if link.kind else ""))


def print_report(report) -> None:
    print()
    print("VERSION     : %s" % (report.version or "?"))
    print("DEVICES     : %d" % len(report.devices))
    for dev in report.devices:
        print("  %-16s %-12s cfg=%-4d copper=%-2d serial=%-2d power=%s"
              % (dev["name"], dev["model"], dev["cfg_lines"], dev["copper"],
                 dev["serial"], dev["power"]))
    print("LINKS       : %d" % len(report.links))
    for link in report.links:
        print("  %-16s %-18s <-> %-16s %-18s %s"
              % (link["from"], link["ports"][0], link["to"], link["ports"][1],
                 link["type"]))
    for warning in report.warnings:
        print("WARNING     : %s" % warning)
    for error in report.errors:
        print("ERROR       : %s" % error)
    print()
    print("VERDICT     : %s" % ("structure looks OK" if report.ok else "FAILED"))


def export_mode(args) -> int:
    """``--export file.pkt -o file.yml``: write the YAML description."""
    try:
        pkt_path = expand_path(args.export)
    except OSError as exc:
        print("error: bad --export path: %s" % exc, file=sys.stderr)
        return 1
    if not pkt_path.exists():
        print("error: .pkt not found: %s" % pkt_path, file=sys.stderr)
        return 1

    out_path = expand_path(args.output) if args.output else pkt_path.with_suffix(".yml")
    seed_value = args.export_seed
    if seed_value is None:
        # Point at the original .pkt, relative to the YAML: rebuilding then uses
        # a file whose VERSION is known to load, even though it lives elsewhere.
        try:
            seed_value = pathlib.Path(os.path.relpath(pkt_path, out_path.parent)).as_posix()
        except ValueError:                    # different drives on Windows
            seed_value = str(pkt_path)

    try:
        text = export_yaml(pkt_path, seed_value=seed_value)
    except PktExportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        print("error: cannot write %s: %s" % (out_path, exc), file=sys.stderr)
        return 1

    if not args.quiet:
        devices = text.count("\n  - model:")
        links = text.count("\n  - [")
        print("exported    : %s -> %s" % (pkt_path, out_path))
        print("devices     : %d" % devices)
        print("links       : %d" % links)
        print("bytes       : %d" % len(text.encode("utf-8")))
        print()
        print("VERDICT     : YAML written (rebuild with -c %s -i <out.pkt>)"
              % out_path.name)
    return 0


def run_accept(out_path: pathlib.Path) -> int:
    if not PT_ACCEPT.exists():
        print("pt_accept.ps1 not found at %s" % PT_ACCEPT)
        return 0
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(PT_ACCEPT), "-File", str(out_path)]
    print("running Packet Tracer acceptance check (takes ~60s) ...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("could not run pt_accept.ps1: %s" % exc)
        return 2
    output = (proc.stdout or "") + (proc.stderr or "")
    for line in output.splitlines():
        if "VERDICT" in line or "not found" in line:
            print(line.strip())
    if proc.returncode == 2:
        return 2
    return 0 if proc.returncode == 0 else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkt_builder",
        description="Build a Cisco Packet Tracer .pkt from a YAML description, "
                    "or export a .pkt back to YAML.",
        epilog="Examples:\n"
               "  python -m pkt_builder -c configs\\configuration.yml -i projects\\my_new.pkt\n"
               "  python -m pkt_builder --export 9lab.pkt -o 9lab.yml\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--config", metavar="YAML",
                        help="input .yml/.yaml description (build mode)")
    parser.add_argument("-i", "--input", metavar="PKT",
                        help="output .pkt file to write (build mode)")
    parser.add_argument("--export", metavar="PKT",
                        help="export a .pkt to YAML instead of building")
    parser.add_argument("-o", "--output", metavar="YAML",
                        help="output .yml for --export (default: next to the .pkt)")
    parser.add_argument("--export-seed", metavar="PKT",
                        help="value written as 'seed:' in the exported YAML "
                             "(default: the exported file itself)")
    parser.add_argument("-s", "--seed", metavar="PKT",
                        help="donor .pkt used as the template "
                             "(default: %s)" % DEFAULT_SEED.name)
    parser.add_argument("--check-only", action="store_true",
                        help="validate the config and print the plan, write nothing")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the structural verification of the result")
    parser.add_argument("--accept", action="store_true",
                        help="also launch Packet Tracer to check the file loads")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="only print errors and the final verdict")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print every config line and port decision")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.export:
        return export_mode(args)
    if not args.config:
        parser.error("the following arguments are required: -c/--config")
    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    try:
        cfg_path = expand_path(args.config)
    except OSError as exc:
        print("error: bad --config path: %s" % exc, file=sys.stderr)
        return 1

    if not cfg_path.exists():
        print("error: config file not found: %s" % cfg_path, file=sys.stderr)
        return 1

    try:
        doc, parsed_with = load_config(cfg_path)
        spec = parse_spec(doc, str(cfg_path))
    except ConfigError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("error: cannot read %s: %s" % (cfg_path, exc), file=sys.stderr)
        return 1

    out_path = expand_path(args.input)
    seed = expand_path(args.seed) if args.seed else DEFAULT_SEED
    if args.seed is None and spec.seed:
        seed = expand_path(spec.seed, cfg_path.parent)

    if not args.quiet:
        print_plan(spec, out_path, seed, parsed_with, str(cfg_path), args.verbose)

    if args.check_only:
        print("\nVERDICT     : config is valid (nothing written)")
        return 0

    try:
        result = build_lab(spec, out_path, seed)
    except ConfigError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except PortError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    if result.warnings and not args.quiet:
        for warning in result.warnings:
            print("WARNING     : %s" % warning)

    if not args.quiet:
        print()
        print("saved       : %s (%d bytes)" % (result.path, result.size))
        for name, mac in result.macs.items():
            print("mac         : %-16s %s" % (name, mac))

    status = 0
    if not args.no_verify:
        from pkt_builder.verify import verify_pkt
        report = verify_pkt(str(out_path))
        if not args.quiet:
            print_report(report)
        elif not report.ok:
            print_report(report)
        if not report.ok:
            status = 1

    if args.accept and status == 0:
        status = run_accept(out_path)

    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
