#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_8lab.py -- reference/template builder for lab 8 (Cisco 2811 CME + 2600 remote).

This is the exact script that produced the accepted `8lab.pkt`. Copy it, change the
device list / configs / addresses, and you get a new lab. See pkt_builder.md for the
full explanation of every non-obvious decision (phone port naming, seed version,
serial DCE, port power, ...).

Run with the bundled interpreter:
    python312\\python.exe build_8lab.py

Requires the ``pkt_builder`` package (the vendored ``pkt_core`` comes with it).
"""
import sys
import pathlib
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pkt_builder  # noqa: E402,F401  (registers vendored pkt_core on sys.path)
from pkt_core.builder import Lab  # noqa: E402
from pkt_builder.resources import donor_path  # noqa: E402

# --------------------------------------------------------------------------- #
# EDIT THESE
# --------------------------------------------------------------------------- #
# Donor .pkt used as the template for the whole document (version tag, workspace,
# root options). MUST be a file that your installed Packet Tracer itself opens.
# The bundled `lab3_donor.pkt` is Packet Tracer 9.0.0.0810 -- use it for PT 9.0.0.
SEED = donor_path()

# Output file
OUT = HERE / "8lab.pkt"


def mac_of(lab, dev):
    """MAC of a device's first copper port -- needed for ephone/CALL config."""
    for p in lab._els[dev].iter("PORT"):
        if p.findtext("TYPE") == "eCopperFastEthernet":
            return p.findtext("MACADDRESS")
    return None


def client_id(mac):
    """DHCP client-identifier for a phone: '01' + dotted-hex MAC."""
    h = mac.replace(".", "").upper()
    return "01" + ".".join(h[i:i + 4] for i in range(0, 12, 4))


def force_copper_power(lab, dev):
    """Set <PORT><POWER>true</PORT> on every copper port of `dev`.

    Harvested templates sometimes carry POWER=false (the 2620XM donor ships with
    Fa0/0 powered down), which renders the cable red even though the IOS config is
    right. Only copper ports are touched: serial power state belongs to link().
    """
    for p in lab._els[dev].iter("PORT"):
        if p.findtext("TYPE") != "eCopperFastEthernet":
            continue
        e = p.find("POWER")
        if e is None:
            e = ET.SubElement(p, "POWER")
        e.text = "true"


def set_cfg(lab, dev, lines):
    """Replace a device's RUNNINGCONFIG with `lines` (one IOS line per item).

    Do this AFTER add_device()/link(): link() appends `clock rate` to the DCE
    config, so writing the config first and linking second would clobber it.
    """
    eng = lab._els[dev].find("ENGINE")
    for rc in list(eng.findall("RUNNINGCONFIG")):
        eng.remove(rc)
    rc = ET.SubElement(eng, "RUNNINGCONFIG")
    for line in lines:
        ET.SubElement(rc, "LINE").text = line


# --------------------------------------------------------------------------- #
# 1. Create the lab on top of the donor, drop the donor's own devices
# --------------------------------------------------------------------------- #
lab = Lab(seed=str(SEED))
lab.prune_seed_devices()          # removes donor devices AND their links/leaves

# --------------------------------------------------------------------------- #
# 2. Place devices
#    add_device(model, name, x, y, install=<module>, ios_config=<lines>)
#    Models available: see pkt_builder/_vendor/pkt_core/data/device_templates.json
#    Modules available: HWIC-2T, WIC-2T, NM-4A/S, ... (same file)
# --------------------------------------------------------------------------- #
cme = lab.add_device("2811", "CMERouter", 200, 220, install="HWIC-2T")
swA = lab.add_device("3560-24PS", "CMESwitch", 200, 400)
ph1 = lab.add_device("7960", "IP Phone 1001", 110, 580)
ph2 = lab.add_device("7960", "IP Phone 1002", 300, 580)
rem = lab.add_device("2620XM", "RemoteRouter", 830, 220, install="WIC-2T")
swB = lab.add_device("3560-24PS", "RemoteSwitch", 830, 400)
ph3 = lab.add_device("7960", "IP Phone 2001", 830, 580)

# --------------------------------------------------------------------------- #
# 3. Cable everything
#    Copper:  lab.link(a, 'FastEthernet0/0', b, 'FastEthernet0/1')
#    Phone:   the 7960 uplink port is literally named 'Switch' (passthrough = 'PC')
#    Serial:  lab.link(a, 'Serial0/0/0', b, 'Serial0/0', kind='serial',
#                      dce=a, clock=64000)
# --------------------------------------------------------------------------- #
lab.link(cme, "FastEthernet0/0", swA, "FastEthernet0/1")
lab.link(rem, "FastEthernet0/0", swB, "FastEthernet0/1")
lab.link(swA, "FastEthernet0/2", ph1, "Switch")
lab.link(swA, "FastEthernet0/3", ph2, "Switch")
lab.link(swB, "FastEthernet0/2", ph3, "Switch")
lab.link(cme, "Serial0/0/0", rem, "Serial0/0", kind="serial", dce=cme, clock=64000)

for d in (cme, swA, ph1, ph2, rem, swB, ph3):
    force_copper_power(lab, d)

# --------------------------------------------------------------------------- #
# 4. Read real MACs so ephone/CALL config matches the generated devices
# --------------------------------------------------------------------------- #
M1, M2, M3 = mac_of(lab, ph1), mac_of(lab, ph2), mac_of(lab, ph3)
C3 = client_id(M3)

# --------------------------------------------------------------------------- #
# 5. IOS configs (one list entry == one line of `show running-config`)
# --------------------------------------------------------------------------- #
CME = [
    "!", "version 15.1",
    "no service timestamps log datetime msec",
    "no service timestamps debug datetime msec",
    "no service password-encryption", "!",
    "hostname CMERouter",
    "!", "enable secret class", "!", "no ip domain-lookup", "!",
    "ip dhcp excluded-address 10.20.1.1 10.20.1.10", "!",
    "ip dhcp pool VOICE",
    " network 10.20.1.0 255.255.255.0",
    " default-router 10.20.1.1",
    " option 150 ip 10.20.1.1", "!",
    "interface FastEthernet0/0",
    " description To-CMESwitch-trunk",
    " ip address 10.20.1.1 255.255.255.0",
    " duplex auto", " speed auto", " no shutdown", "!",
    "interface FastEthernet0/1",
    " no ip address", " duplex auto", " speed auto", " shutdown", "!",
    "interface Serial0/0/0",
    " description To-RemoteRouter",
    " ip address 192.168.1.1 255.255.255.252",
    " clock rate 64000", " no shutdown", "!",
    "interface Serial0/0/1", " no ip address", " shutdown", "!",
    "interface Vlan1", " no ip address", " shutdown", "!",
    "router eigrp 1",
    " network 10.0.0.0",
    " network 192.168.1.0",
    " no auto-summary", "!",
    "ip classless", "!", "no ip http server", "!",
    "telephony-service",
    " max-ephones 5",
    " max-dn 5",
    " ip source-address 10.20.1.1 port 2000",
    " keepalive 30", "!",
    "ephone-dn 1", " number 1001", " name Phone-1001", "!",
    "ephone-dn 2", " number 1002", " name Phone-1002", "!",
    "ephone-dn 3", " number 2001", " name Phone-Remote-2001", "!",
    "ephone 1",
    " device-security-mode none",
    " description Phone-1001",
    " mac-address " + M1,
    " type 7960", " button 1:1", "!",
    "ephone 2",
    " device-security-mode none",
    " description Phone-1002",
    " mac-address " + M2,
    " type 7960", " button 1:2", "!",
    "dial-peer voice 1 voip",
    " description To-Remote-Site-2001",
    " destination-pattern 2001",
    " session target ipv4:192.168.1.2",
    " codec g711ulaw", "!",
    "line con 0", " password cisco", " logging synchronous", " login",
    "line aux 0", "!",
    "line vty 0 4", " password cisco", " logging synchronous", " login",
    "line vty 5 15", " password cisco", " logging synchronous", " login",
    "!", "end",
]

SWA = [
    "!", "version 12.2",
    "no service timestamps log datetime msec",
    "no service timestamps debug datetime msec",
    "no service password-encryption", "!",
    "hostname CMESwitch", "!", "enable secret class", "!",
    "no ip domain-lookup", "!",
    "interface FastEthernet0/1",
    " description Uplink-CMERouter",
    " switchport mode trunk",
    " switchport trunk native vlan 1",
    " spanning-tree portfast",
    " no shutdown", "!",
    "interface range FastEthernet0/2 - 3",
    " description IP-Phone-7960",
    " switchport mode access",
    " switchport access vlan 1",
    " switchport voice vlan 1",
    " spanning-tree portfast",
    " no shutdown", "!",
    "interface range FastEthernet0/4 - 24", " shutdown", "!",
    "interface GigabitEthernet0/1", " shutdown",
    "interface GigabitEthernet0/2", " shutdown", "!",
    "interface Vlan1",
    " ip address 10.20.1.11 255.255.255.0",
    " no shutdown", "!",
    "ip default-gateway 10.20.1.1", "!",
    "line con 0", " password cisco", " logging synchronous", " login",
    "line vty 0 4", " password cisco", " logging synchronous", " login",
    "line vty 5 15", " password cisco", " logging synchronous", " login",
    "!", "end",
]

REM = [
    "!", "version 12.2",
    "no service timestamps log datetime msec",
    "no service timestamps debug datetime msec",
    "no service password-encryption", "!",
    "hostname RemoteRouter", "!", "enable secret class", "!",
    "no ip domain-lookup", "!",
    "ip dhcp excluded-address 10.30.1.1 10.30.1.1",
    "ip dhcp excluded-address 10.40.1.1 10.40.1.10", "!",
    "ip dhcp pool VOICE",
    " network 10.30.1.0 255.255.255.0",
    " default-router 10.30.1.1",
    " option 150 ip 10.20.1.1", "!",
    "ip dhcp pool PHONE-2001",
    " host 10.30.1.2 255.255.255.0",
    " client-identifier " + C3,
    " default-router 10.30.1.1",
    " option 150 ip 10.20.1.1", "!",
    "ip dhcp pool DATA",
    " network 10.40.1.0 255.255.255.0",
    " default-router 10.40.1.1", "!",
    "interface FastEthernet0/0",
    " description To-RemoteSwitch-trunk",
    " no ip address", " duplex auto", " speed auto", " no shutdown", "!",
    "interface FastEthernet0/0.30",
    " description Voice-VLAN30",
    " encapsulation dot1Q 30",
    " ip address 10.30.1.1 255.255.255.0", "!",
    "interface FastEthernet0/0.40",
    " description Data-VLAN40",
    " encapsulation dot1Q 40",
    " ip address 10.40.1.1 255.255.255.0", "!",
    "interface Serial0/0",
    " description To-CMERouter",
    " ip address 192.168.1.2 255.255.255.252",
    " no shutdown", "!",
    "interface Serial0/1", " no ip address", " shutdown", "!",
    "interface Vlan1", " no ip address", " shutdown", "!",
    "router eigrp 1",
    " network 10.0.0.0",
    " network 192.168.1.0",
    " no auto-summary", "!",
    "ip classless", "!", "no ip http server", "!",
    "dial-peer voice 1 voip",
    " description To-CME-1001",
    " destination-pattern 1001",
    " session target ipv4:192.168.1.1",
    " codec g711ulaw", "!",
    "dial-peer voice 2 voip",
    " description To-CME-1002",
    " destination-pattern 1002",
    " session target ipv4:192.168.1.1",
    " codec g711ulaw", "!",
    "line con 0", " password cisco", " logging synchronous", " login",
    "line aux 0", "!",
    "line vty 0 4", " password cisco", " logging synchronous", " login",
    "!", "end",
]

SWB = [
    "!", "version 12.2",
    "no service timestamps log datetime msec",
    "no service timestamps debug datetime msec",
    "no service password-encryption", "!",
    "hostname RemoteSwitch", "!", "enable secret class", "!",
    "no ip domain-lookup", "!",
    "vlan 30", " name VOICE",
    "vlan 40", " name DATA", "!",
    "interface FastEthernet0/1",
    " description Uplink-RemoteRouter",
    " switchport mode trunk",
    " switchport trunk native vlan 1",
    " switchport trunk allowed vlan 30,40",
    " spanning-tree portfast",
    " no shutdown", "!",
    "interface FastEthernet0/2",
    " description IP-Phone-7960-2001",
    " switchport mode access",
    " switchport access vlan 40",
    " switchport voice vlan 30",
    " spanning-tree portfast",
    " no shutdown", "!",
    "interface range FastEthernet0/3 - 24", " shutdown", "!",
    "interface GigabitEthernet0/1", " shutdown",
    "interface GigabitEthernet0/2", " shutdown", "!",
    "interface Vlan40",
    " ip address 10.40.1.11 255.255.255.0",
    " no shutdown", "!",
    "ip default-gateway 10.40.1.1", "!",
    "line con 0", " password cisco", " logging synchronous", " login",
    "line vty 0 4", " password cisco", " logging synchronous", " login",
    "line vty 5 15", " password cisco", " logging synchronous", " login",
    "!", "end",
]

set_cfg(lab, cme, CME)
set_cfg(lab, swA, SWA)
set_cfg(lab, rem, REM)
set_cfg(lab, swB, SWB)

# --------------------------------------------------------------------------- #
# 6. Save (encodes back to the .pkt container)
# --------------------------------------------------------------------------- #
lab.save(OUT)
print("saved", OUT, OUT.stat().st_size)
print("phone MACs", M1, M2, M3)
print("client-id ", C3)
