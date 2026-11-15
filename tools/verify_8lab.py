#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_8lab.py -- dump devices, ports and links of a .pkt so you can check the
file without opening Packet Tracer.

Usage:
    python312\\python.exe tools\\verify_8lab.py [file.pkt]

Checks performed (read the output, no automation):
  * every device: model + copper/serial port POWER flags
  * every link: exact PORT NAME on both ends (the phone uplink must be "Switch")
  * serial links: which side is DCE and its clock rate
  * RUNNINGCONFIG length per device (0 for phones is normal)

If a phone link shows "FastEthernet0/0" -> PT will reject the file: the 7960's
uplink port is literally named "Switch" (and its passthrough port is "PC").
"""
import pathlib
import sys
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # so `pkt_builder` is importable

import pkt_builder                            # noqa: E402,F401  (registers vendored pkt_core)
from pkt_core.codec.container import decode  # noqa: E402


def main(argv):
    pkt = pathlib.Path(argv[1]) if len(argv) > 1 else HERE.parent / "8lab.pkt"
    if not pkt.exists():
        sys.exit("no such file: %s" % pkt)

    root = ET.fromstring(decode(str(pkt), None).xml)
    print("VERSION", root.findtext("VERSION"))
    print("FILE   ", pkt, pkt.stat().st_size, "bytes")
    print()

    names = {}
    models = {}
    for d in root.findall(".//NETWORK/DEVICES/DEVICE"):
        e = d.find("ENGINE")
        sid = e.findtext("SAVE_REF_ID")
        names[sid] = e.findtext("NAME")
        models[sid] = e.find("TYPE").get("model")

    print("DEVICES")
    for sid, name in names.items():
        el = [d.find("ENGINE") for d in root.findall(".//NETWORK/DEVICES/DEVICE")
              if d.find("ENGINE").findtext("SAVE_REF_ID") == sid][0]
        ports = []
        for p in el.iter("PORT"):
            t = p.findtext("TYPE")
            if t in ("eCopperFastEthernet", "eSmartSerial"):
                ports.append("%s(power=%s)" % (
                    "copper" if t == "eCopperFastEthernet" else "serial",
                    p.findtext("POWER")))
        rc = el.find("RUNNINGCONFIG")
        ncfg = len(rc.findall("LINE")) if rc is not None else 0
        print("  %-16s %-11s cfg_lines=%-4d %s" % (
            name, models[sid], ncfg, " ".join(ports)))
    print()

    print("LINKS")
    ok = True
    for L in root.findall(".//NETWORK/LINKS/LINK"):
        cab = L.find("CABLE")
        ports = [c.text for c in cab if c.tag == "PORT"]
        fr, to = cab.findtext("FROM"), cab.findtext("TO")
        fn, tn = names.get(fr, "?"), names.get(to, "?")
        extra = ""
        if L.findtext("TYPE") == "eSerial":
            dce_sid = cab.findtext("DCEDEV")
            rate = ""
            if dce_sid in names:
                for d in root.findall(".//NETWORK/DEVICES/DEVICE"):
                    e = d.find("ENGINE")
                    if e.findtext("SAVE_REF_ID") != dce_sid:
                        continue
                    for p in e.iter("PORT"):
                        if (p.findtext("TYPE") == "eSmartSerial"
                                and p.findtext("CLOCKRATEFLAG") == "true"):
                            rate = " @%s" % p.findtext("CLOCKRATE")
            extra = "  DCE=%s %s%s" % (
                names.get(dce_sid, "-"), cab.findtext("DCEPORT") or "", rate)
        print("  %-9s %-16s %-18s -> %-16s %-18s%s" % (
            L.findtext("TYPE"), fn, ports[0], tn, ports[1], extra))
        # sanity: a non-phone side must not name a phone port "FastEthernet0/0"
        for sid, port in ((fr, ports[0]), (to, ports[1])):
            if models.get(sid) == "7960" and port not in ("Switch", "PC"):
                print("    !! 7960 port must be 'Switch' or 'PC', got %r" % port)
                ok = False

    print()
    print("VERDICT:", "structure looks OK" if ok else "PHONE PORT NAMES BROKEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
