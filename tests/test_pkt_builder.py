#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for pkt_builder.  Run:  python pkt_builder/tests/test_pkt_builder.py"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
ROOT = PKG.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(ROOT))

from pkt_builder import miniyaml                                    # noqa: E402
from pkt_builder.builder import client_id                           # noqa: E402
from pkt_builder.config import ConfigError, parse_spec              # noqa: E402
from pkt_builder.exporter import PktExportError, export_yaml, dump_yaml  # noqa: E402
from pkt_builder.ports import PortError, port_catalogue, resolve_port  # noqa: E402
from pkt_builder.verify import verify_pkt                           # noqa: E402

SCRIPT = PKG / "pkt_builder.py"
EXAMPLES = PKG / "examples"
SEED = PKG / "donors" / "lab3_donor.pkt"


# --------------------------------------------------------------------------- #
class MiniYamlTest(unittest.TestCase):
    def test_scalars(self):
        doc = miniyaml.load("a: 1\nb: true\nc: null\nd: text\ne: 1.5\n")
        self.assertEqual(doc, {"a": 1, "b": True, "c": None, "d": "text", "e": 1.5})

    def test_nested_and_sequences(self):
        doc = miniyaml.load(
            "devices:\n  - model: 2911\n    name: R1\n    cfg: |\n      hostname R1\n"
            "       ip address 1.1.1.1\n  - model: 7960\n    name: PH1\n")
        self.assertEqual(len(doc["devices"]), 2)
        self.assertEqual(doc["devices"][0]["cfg"],
                         "hostname R1\n ip address 1.1.1.1\n")

    def test_flow_sequence_with_hints(self):
        doc = miniyaml.load("a: [R1, R2, dce: R1, clock: 64000]\n")
        self.assertEqual(doc["a"], ["R1", "R2", {"dce": "R1"}, {"clock": 64000}])

    def test_comments_and_quotes(self):
        doc = miniyaml.load('a: "x # y"  # trailing\nb: it\'s\n')
        self.assertEqual(doc["a"], "x # y")
        self.assertEqual(doc["b"], "it's")

    def test_matches_pyyaml_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        text = (EXAMPLES / "lab8.yml").read_text(encoding="utf-8-sig")
        mine = miniyaml.load(text)
        theirs = yaml.safe_load(text)

        def norm(o):
            if isinstance(o, dict):
                return {str(k): norm(v) for k, v in o.items()}
            if isinstance(o, list):
                return [norm(v) for v in o]
            if isinstance(o, (int, float)) and not isinstance(o, bool):
                return str(o)
            return o

        self.assertEqual(norm(mine), norm(theirs))

    def test_rejects_unsupported(self):
        with self.assertRaises(miniyaml.YamlError):
            miniyaml.load("a: [1, 2\n")


# --------------------------------------------------------------------------- #
class PortCatalogueTest(unittest.TestCase):
    def test_switch_names(self):
        cat = port_catalogue("3560-24PS")
        self.assertIn("FastEthernet0/1", cat.copper)
        self.assertIn("FastEthernet0/24", cat.copper)
        self.assertIn("GigabitEthernet0/1", cat.copper)
        self.assertEqual(cat.serial, [])

    def test_router_names(self):
        cat = port_catalogue("2911")
        self.assertEqual(cat.copper,
                         ["GigabitEthernet0/0", "GigabitEthernet0/1",
                          "GigabitEthernet0/2"])
        self.assertEqual(cat.serial, [])

    def test_phone_ports(self):
        cat = port_catalogue("7960")
        self.assertEqual(sorted(cat.kinds), ["PC", "Switch"])
        self.assertRaises(PortError, resolve_port, cat, "FastEthernet0/0")

    def test_abbreviations(self):
        cat = port_catalogue("3560-24PS")
        self.assertEqual(resolve_port(cat, "Fa0/2"), "FastEthernet0/2")
        self.assertEqual(resolve_port(cat, "fa0/2"), "FastEthernet0/2")
        self.assertEqual(resolve_port(cat, "g0/1"), "GigabitEthernet0/1")
        self.assertEqual(resolve_port(cat, "FastEthernet0/2"), "FastEthernet0/2")

    def test_end_device_port(self):
        self.assertEqual(resolve_port(port_catalogue("PC-PT"), "FastEthernet0"),
                         "FastEthernet0")

    def test_serial_naming(self):
        from pkt_builder.ports import with_modules
        self.assertIn("Serial0/0/0", with_modules("2811", ["HWIC-2T"]).serial)
        # 26xx uses the flat Serial0/0, Serial0/1 scheme
        self.assertIn("Serial0/0", with_modules("2620XM", ["WIC-2T"]).serial)

    def test_unknown_model(self):
        with self.assertRaises(PortError):
            port_catalogue("NOPE-1")


# --------------------------------------------------------------------------- #
class ConfigTest(unittest.TestCase):
    def test_minimal(self):
        spec = parse_spec({"devices": [{"model": "2911", "name": "R1"}]})
        self.assertEqual(len(spec.devices), 1)
        self.assertEqual(spec.devices[0].name, "R1")

    def test_user_example(self):
        doc = miniyaml.load(
            "model: 2911\nname: HQswitch\npos: 200, 235\n"
            'cfg: "hostname X\\n ip address 1.1.1.1 255.0.0.0"\n')
        spec = parse_spec(doc)
        dev = spec.devices[0]
        self.assertEqual(dev.model, "2911")
        self.assertEqual((dev.x, dev.y), (200, 235))
        self.assertEqual(dev.cfg, ["hostname X", " ip address 1.1.1.1 255.0.0.0"])

    def test_link_form_two(self):
        doc = {"devices": [{"model": "2911", "name": "R1"},
                           {"model": "2911", "name": "R2"}],
               "links": [["R1", "R2"]]}
        link = parse_spec(doc).links[0]
        self.assertTrue(link.auto)

    def test_link_form_auto_with_hints(self):
        doc = miniyaml.load(
            "devices:\n  - {model: 2811, name: R1}\n  - {model: 2811, name: R2}\n"
            "links:\n  - auto: [R1, R2, dce: R1, clock: 128000]\n")
        link = parse_spec(doc).links[0]
        self.assertTrue(link.auto)
        self.assertEqual(link.kind, "serial")
        self.assertEqual(link.dce, "R1")
        self.assertEqual(link.clock, 128000)

    def test_link_positional_seven(self):
        doc = {"devices": [{"model": "2811", "name": "R1"},
                           {"model": "2811", "name": "R2"}],
               "links": [["R1", "Serial0/0/0", "R2", "Serial0/0",
                          "serial", "R1", 64000]]}
        link = parse_spec(doc).links[0]
        self.assertEqual((link.a_port, link.b_port, link.kind, link.dce, link.clock),
                         ("Serial0/0/0", "Serial0/0", "serial", "R1", 64000))

    def test_link_positional_six_defaults_clock(self):
        doc = {"devices": [{"model": "2811", "name": "R1"},
                           {"model": "2811", "name": "R2"}],
               "links": [["R1", "s0/0/0", "R2", "s0/0/0", "serial", "R1"]]}
        self.assertEqual(parse_spec(doc).links[0].clock, 64000)

    def test_link_kind_inferred(self):
        doc = {"devices": [{"model": "2811", "name": "R1"},
                           {"model": "7960", "name": "PH1"}],
               "links": [["R1", "Fa0/0", "PH1", "Switch"]]}
        self.assertIsNone(parse_spec(doc).links[0].kind)

    def test_three_elements_ambiguous(self):
        doc = {"devices": [{"model": "2811", "name": "R1"},
                           {"model": "2811", "name": "R2"}],
               "links": [["R1", "R2", "copper"]]}
        with self.assertRaises(ConfigError):
            parse_spec(doc)

    def test_duplicate_names(self):
        with self.assertRaises(ConfigError):
            parse_spec({"devices": [{"model": "2811", "name": "R1"},
                                    {"model": "2811", "name": "R1"}]})

    def test_unknown_link_device(self):
        with self.assertRaises(ConfigError):
            parse_spec({"devices": [{"model": "2811", "name": "R1"}],
                        "links": [["R1", "R2"]]})

    def test_bad_dce(self):
        doc = {"devices": [{"model": "2811", "name": "R1"},
                           {"model": "2811", "name": "R2"}],
               "links": [["R1", "s0/0/0", "R2", "s0/0/0", "serial", "R3"]]}
        with self.assertRaises(ConfigError):
            parse_spec(doc)

    def test_pos_forms(self):
        for pos in ("200, 235", [200, 235], "200 235", (200, 235)):
            spec = parse_spec({"devices": [{"model": "2911", "name": "R1",
                                            "pos": pos}]})
            self.assertEqual((spec.devices[0].x, spec.devices[0].y), (200, 235))

    def test_cfg_list(self):
        spec = parse_spec({"devices": [{"model": "2911", "name": "R1",
                                        "cfg": ["hostname R1", "end"]}]})
        self.assertEqual(spec.devices[0].cfg, ["hostname R1", "end"])

    def test_client_id(self):
        self.assertEqual(client_id("0212.0000.207F"), "010212.0000.207F")


# --------------------------------------------------------------------------- #
class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pktbuilder-"))

    def _run(self, config, name, extra_env=None):
        out = self.tmp / (name + ".pkt")
        env = dict(os.environ)
        env.update(extra_env or {})
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-c", str(config), "-i", str(out), "-q"],
            capture_output=True, text=True, env=env, cwd=str(ROOT))
        return proc, out

    def test_example_lab_builds(self):
        proc, out = self._run(EXAMPLES / "lab8.yml", "lab8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.exists())
        report = verify_pkt(str(out))
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(len(report.devices), 7)
        self.assertEqual(len(report.links), 6)

    def test_example_lab_with_miniyaml(self):
        proc, out = self._run(EXAMPLES / "lab8.yml", "lab8mini",
                              {"PKT_BUILDER_YAML": "mini"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(verify_pkt(str(out)).ok)

    def test_link_forms(self):
        proc, out = self._run(EXAMPLES / "link_forms.yml", "forms")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = verify_pkt(str(out))
        self.assertTrue(report.ok, report.errors)
        ports = {(l["from"], l["ports"][0]) for l in report.links}
        self.assertIn(("CMERouter", "Serial0/0/0"), ports)

    def test_end_devices(self):
        proc, out = self._run(EXAMPLES / "end_devices.yml", "end")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(verify_pkt(str(out)).ok)

    def test_bad_phone_port_is_rejected(self):
        proc, _ = self._run(EXAMPLES / "bad_phone_port.yml", "badphone")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("available: Switch, PC", proc.stderr)

    def test_placeholders_expand(self):
        cfg = self.tmp / "mac.yml"
        cfg.write_text(
            "seed: %s\n"
            "devices:\n"
            "  - {model: 2911, name: R1}\n"
            "  - {model: 7960, name: PH1}\n"
            "links:\n"
            "  - [R1, GigabitEthernet0/0, PH1, Switch]\n"
            "  - [R1, GigabitEthernet0/1, PH1, PC]\n"
            "  - [R1, GigabitEthernet0/2]\n"
            % SEED, encoding="utf-8")
        # the third link is intentionally malformed -> rejected
        proc, _ = self._run(cfg, "badlink")
        self.assertEqual(proc.returncode, 1)

        cfg.write_text(
            "seed: %s\n"
            "devices:\n"
            "  - {model: 2911, name: R1,\n"
            "     cfg: 'ephone 1\\n mac-address {{mac:PH1}}\\n"
            " client-identifier {{client_id:PH1}}'}\n"
            "  - {model: 7960, name: PH1}\n"
            "links:\n"
            "  - [R1, GigabitEthernet0/0, PH1, Switch]\n" % SEED, encoding="utf-8")
        proc, out = self._run(cfg, "mac")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        from pkt_core.codec.container import decode
        import xml.etree.ElementTree as ET
        root = ET.fromstring(decode(str(out), None).xml)
        lines = []
        for dev in root.findall(".//NETWORK/DEVICES/DEVICE"):
            if dev.findtext("ENGINE/NAME") == "R1":
                lines = [l.text for l in dev.findall("ENGINE/RUNNINGCONFIG/LINE")]
        text = "\n".join(lines or [])
        self.assertRegex(text, r"mac-address 0212\.0000\.[0-9A-F]{4}")
        self.assertRegex(text, r"client-identifier 010212\.0000\.[0-9A-F]{4}")
        self.assertNotIn("{{", text)

    def test_check_only_writes_nothing(self):
        out = self.tmp / "nothing.pkt"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-c", str(EXAMPLES / "lab8.yml"),
             "-i", str(out), "--check-only", "-q"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(out.exists())


# --------------------------------------------------------------------------- #
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pktexport-"))
        cls.ref = PKG / "8lab.pkt"

    def _export(self, src, out):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--export", str(src), "-o", str(out), "-q"],
            capture_output=True, text=True, cwd=str(ROOT))

    def test_export_writes_yaml(self):
        self.assertTrue(self.ref.exists(), "8lab.pkt missing")
        out = self.tmp / "exp.yml"
        proc = self._export(self.ref, out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("devices:", text)
        self.assertIn("links:", text)
        self.assertIn("cfg: |", text)

    def test_export_yaml_is_valid_and_parses_to_spec(self):
        out = self.tmp / "spec.yml"
        self.assertEqual(self._export(self.ref, out).returncode, 0)
        doc = miniyaml.load(out.read_text(encoding="utf-8"))
        spec = parse_spec(doc, "exported")
        self.assertEqual(len(spec.devices), 7)
        self.assertEqual(len(spec.links), 6)
        # serial link keeps its DCE and clock rate
        serial = [l for l in spec.links if l.kind == "serial"]
        self.assertEqual(len(serial), 1)
        self.assertEqual(serial[0].dce, "CMERouter")
        self.assertEqual(serial[0].clock, 64000)

    def test_export_matches_pyyaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        out = self.tmp / "cmp.yml"
        self.assertEqual(self._export(self.ref, out).returncode, 0)
        text = out.read_text(encoding="utf-8")
        self.assertEqual(miniyaml.load(text), yaml.safe_load(text))

    def test_round_trip_rebuilds_same_topology(self):
        import xml.etree.ElementTree as ET
        from pkt_core.codec.container import decode

        yml = self.tmp / "rt.yml"
        out = self.tmp / "rt.pkt"
        self.assertEqual(self._export(self.ref, yml).returncode, 0)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-c", str(yml), "-i", str(out), "-q"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr)

        def snapshot(path):
            root = ET.fromstring(decode(str(path), None).xml)
            devs = []
            for d in root.findall(".//NETWORK/DEVICES/DEVICE"):
                engine = d.find("ENGINE")
                if engine is None or engine.findtext("NAME") is None:
                    continue
                devs.append((
                    engine.findtext("NAME"),
                    engine.find("TYPE").get("model"),
                    [l.text or "" for l in d.findall("ENGINE/RUNNINGCONFIG/LINE")],
                ))
            return sorted(devs)

        self.assertEqual(snapshot(self.ref), snapshot(out))

    def test_export_missing_file(self):
        proc = self._export(self.tmp / "nope.pkt", self.tmp / "x.yml")
        self.assertEqual(proc.returncode, 1)
        self.assertIn(".pkt not found", proc.stderr)

    def test_dump_yaml_quotes_ambiguous_scalars(self):
        doc = {"devices": [{"model": "2811", "name": "true"}], "links": []}
        text = dump_yaml(doc)
        self.assertIn('name: "true"', text)
        self.assertEqual(miniyaml.load(text)["devices"][0]["name"], "true")


if __name__ == "__main__":
    unittest.main(verbosity=2)
