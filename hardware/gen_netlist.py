#!/usr/bin/env python3
"""Schematic source of the WiFi-to-USB gateway.

The circuit is described here as data (parts, pins, nets); this script checks
it and writes two files next to itself:

  wifi-usb-gateway.net   KiCad netlist (Pcbnew: File > Import > Netlist)
  bom-jlcpcb.csv         BOM in the JLCPCB assembly column layout

Checks, all fatal: every pin of every part is either on a net or listed as
intentionally unconnected, no pin is on two nets, no net has a single node.

Usage: python3 gen_netlist.py [--check]   (--check: verify the committed
outputs are up to date instead of rewriting them)
"""
import csv
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Pin maps: pin name -> pad number. Names are what the nets below refer to.
# --------------------------------------------------------------------------
TWO = {"1": "1", "2": "2"}
POLAR = {"P": "1", "N": "2"}            # polarised capacitor, pad 1 = plus
DIODE = {"K": "1", "A": "2"}            # KiCad diode/LED footprints: pad 1 = cathode
PMOS_SOT23 = {"G": "1", "S": "2", "D": "3"}
PNP_SOT23 = {"B": "1", "E": "2", "C": "3"}

ESP32_S3_WROOM_1 = {
    "GND1": "1", "3V3": "2", "EN": "3", "IO4": "4", "IO5": "5", "IO6": "6",
    "IO7": "7", "IO15": "8", "IO16": "9", "IO17": "10", "IO18": "11",
    "IO8": "12", "IO19": "13", "IO20": "14", "IO3": "15", "IO46": "16",
    "IO9": "17", "IO10": "18", "IO11": "19", "IO12": "20", "IO13": "21",
    "IO14": "22", "IO21": "23", "IO47": "24", "IO48": "25", "IO45": "26",
    "IO0": "27", "IO35": "28", "IO36": "29", "IO37": "30", "IO38": "31",
    "IO39": "32", "IO40": "33", "IO41": "34", "IO42": "35", "RXD0": "36",
    "TXD0": "37", "IO2": "38", "IO1": "39", "GND40": "40", "GND41": "41",
}

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
CELEC = "Capacitor_SMD:CP_Elec_6.3x7.7"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT236 = "Package_TO_SOT_SMD:SOT-23-6"
SOD123 = "Diode_SMD:D_SOD-123"
LED0603 = "LED_SMD:LED_0603_1608Metric"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x0{}_P2.54mm_Vertical"
# Connector and switch footprints depend on the exact LCSC part: pull them by
# C-number (e.g. easyeda2kicad) once the part is confirmed in the JLCPCB library.
BY_PART = "TODO:footprint_from_LCSC_part"

# ref: (value, footprint, pin map, LCSC part, LCSC status, populate)
# LCSC status: "ok" = looked up 2026-11, "?" = from memory, confirm before order,
# "" = pick in the JLCPCB library.
PARTS = {
    # --- 5 V input, reverse-polarity and over-voltage cut-off ---------------
    "J1": ("DC-005 5.5/2.1", BY_PART, {"TIP": "1", "SLEEVE": "2", "SW": "3"}, "C381116", "ok", True),
    "Q1": ("AO3401A", SOT23, PMOS_SOT23, "C15127", "ok", True),
    "Q2": ("AO3401A", SOT23, PMOS_SOT23, "C15127", "ok", True),
    "Q3": ("MMBT3906", SOT23, PNP_SOT23, "", "", True),
    "D1": ("BZT52C10", SOD123, DIODE, "", "", True),
    "D2": ("BZT52C5V6", SOD123, DIODE, "", "", True),
    "R1": ("100k", R0603, TWO, "C25803", "?", True),
    "R2": ("4k7", R0603, TWO, "C23162", "?", True),
    "R3": ("3k3", R0603, TWO, "C22978", "?", True),
    "C1": ("220u/10V", CELEC, POLAR, "", "", True),
    "C2": ("100n", C0603, TWO, "C14663", "?", True),
    # --- 3V3 rail ------------------------------------------------------------
    "U2": ("AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
           {"GND": "1", "VOUT": "2", "VIN": "3"}, "C6186", "ok", True),
    "C3": ("10u", C0805, TWO, "C15850", "?", True),
    "C4": ("22u", C0805, TWO, "C45783", "?", True),
    # --- WiFi MCU ------------------------------------------------------------
    "U1": ("ESP32-S3-WROOM-1-N16R8", "RF_Module:ESP32-S3-WROOM-1",
           ESP32_S3_WROOM_1, "C2913202", "ok", True),
    "C5": ("10u", C0805, TWO, "C15850", "?", True),
    "C6": ("100n", C0603, TWO, "C14663", "?", True),
    "R4": ("10k", R0603, TWO, "C25804", "?", True),
    "C7": ("1u", C0603, TWO, "C15849", "?", True),
    "R5": ("10k", R0603, TWO, "C25804", "?", True),
    "SW1": ("RESET", BY_PART, TWO, "", "", True),
    "SW2": ("BOOT", BY_PART, TWO, "", "", True),
    # --- switched, current-limited target port --------------------------------
    "U3": ("TPS2553DBVR", SOT236,
           {"IN": "1", "GND": "2", "EN": "3", "FAULT": "4", "ILIM": "5", "OUT": "6"},
           "C55266", "ok", True),
    "R6": ("24k9 1%", R0603, TWO, "", "", True),
    "R7": ("100k", R0603, TWO, "C25803", "?", True),
    "R8": ("10k", R0603, TWO, "C25804", "?", True),
    "C8": ("100n", C0603, TWO, "C14663", "?", True),
    "C9": ("220u/10V", CELEC, POLAR, "", "", True),
    "R9": ("1k", R0603, TWO, "C21190", "?", True),
    "U4": ("USBLC6-2SC6", SOT236,
           {"IO1A": "1", "GND": "2", "IO2A": "3", "IO2B": "4", "VBUS": "5", "IO1B": "6"},
           "C7519", "?", True),
    "J2": ("USB-A receptacle SMD", BY_PART,
           {"VBUS": "1", "DM": "2", "DP": "3", "GND": "4", "SHELL": "5"}, "C718023", "?", True),
    # --- voltage telemetry ----------------------------------------------------
    "R10": ("100k", R0603, TWO, "C25803", "?", True),
    "R11": ("100k", R0603, TWO, "C25803", "?", True),
    "C10": ("100n", C0603, TWO, "C14663", "?", True),
    "R12": ("100k", R0603, TWO, "C25803", "?", True),
    "R13": ("100k", R0603, TWO, "C25803", "?", True),
    "C11": ("100n", C0603, TWO, "C14663", "?", True),
    # --- indicators -----------------------------------------------------------
    "D3": ("LED green (3V3)", LED0603, DIODE, "", "", True),
    "D4": ("LED yellow (target power)", LED0603, DIODE, "", "", True),
    "D5": ("LED red (status)", LED0603, DIODE, "", "", True),
    "R14": ("1k", R0603, TWO, "C21190", "?", True),
    "R15": ("1k", R0603, TWO, "C21190", "?", True),
    "R16": ("1k", R0603, TWO, "C21190", "?", True),
    # --- headers, footprints only (not assembled) -----------------------------
    "J3": ("ESP UART0 prog", HDR.format(6), {str(i): str(i) for i in range(1, 7)}, "", "", False),
    "J4": ("Target aux UART", HDR.format(4), {str(i): str(i) for i in range(1, 5)}, "", "", False),
    "R17": ("1k", R0603, TWO, "C21190", "?", True),
    "R18": ("1k", R0603, TWO, "C21190", "?", True),
    "R19": ("1k", R0603, TWO, "C21190", "?", True),
}

NETS = {
    "VIN_RAW": ["J1.TIP", "Q1.D"],
    # Q1/Q2 are back to back with a common source. Q1 blocks a reversed plug,
    # Q2 blocks an over-voltage; one gate network drives both.
    "VMID": ["Q1.S", "Q2.S", "Q3.E", "R2.1", "D1.K"],
    "OVP_GATE": ["Q1.G", "Q2.G", "Q3.C", "R1.1", "D1.A"],
    "OVP_BASE": ["Q3.B", "R2.2", "R3.1"],
    "OVP_REF": ["R3.2", "D2.K"],
    "+5V": ["Q2.D", "C1.P", "C2.1", "U2.VIN", "C3.1", "U3.IN", "R12.1"],
    "+3V3": ["U2.VOUT", "C4.1", "U1.3V3", "C5.1", "C6.1", "R4.1", "R5.1",
             "R8.1", "R14.1", "J3.2"],
    "ESP_EN": ["U1.EN", "R4.2", "C7.1", "SW1.1", "J3.3"],
    "ESP_IO0": ["U1.IO0", "R5.2", "SW2.1", "J3.4"],
    "ESP_TXD0": ["U1.TXD0", "J3.5"],
    "ESP_RXD0": ["U1.RXD0", "J3.6"],
    "TGT_PWR_EN": ["U1.IO6", "U3.EN", "R7.1"],
    "TGT_FAULT_N": ["U1.IO7", "U3.FAULT", "R8.2"],
    "ILIM": ["U3.ILIM", "R6.1"],
    "VBUS_OUT": ["U3.OUT", "C8.1", "C9.P", "R9.1", "R10.1", "U4.VBUS",
                 "J2.VBUS", "R15.1"],
    "VBUS_SENSE": ["R10.2", "R11.1", "C10.1", "U1.IO4"],
    "VIN_SENSE": ["R12.2", "R13.1", "C11.1", "U1.IO5"],
    "USB_DM": ["U1.IO19", "U4.IO1A", "U4.IO1B", "J2.DM"],
    "USB_DP": ["U1.IO20", "U4.IO2A", "U4.IO2B", "J2.DP"],
    "LED_PWR_A": ["R14.2", "D3.A"],
    "LED_TGT_A": ["R15.2", "D4.A"],
    "LED_STAT": ["U1.IO15", "R16.1"],
    "LED_STAT_A": ["R16.2", "D5.A"],
    "TGT_NRST": ["U1.IO16", "R17.1"],
    "TGT_UART_TX": ["U1.IO17", "R18.1"],
    "TGT_UART_RX": ["U1.IO18", "R19.1"],
    "J4_NRST": ["R17.2", "J4.4"],
    "J4_TX": ["R18.2", "J4.2"],
    "J4_RX": ["R19.2", "J4.3"],
    "GND": ["J1.SLEEVE", "J1.SW", "R1.2", "D2.A", "C1.N", "C2.2", "U2.GND",
            "C3.2", "C4.2", "U1.GND1", "U1.GND40", "U1.GND41", "C5.2", "C6.2",
            "C7.2", "SW1.2", "SW2.2", "U3.GND", "R6.2", "R7.2", "C8.2", "C9.N",
            "R9.2", "U4.GND", "J2.GND", "J2.SHELL", "R11.2", "C10.2", "R13.2",
            "C11.2", "D3.K", "D4.K", "D5.K", "J3.1", "J4.1"],
}

# Left open on purpose. IO35..IO37 belong to the octal PSRAM of the N16R8
# module; IO3/IO45/IO46 are strapping pins that must keep their defaults.
UNCONNECTED = ["U1." + p for p in (
    "IO8 IO3 IO46 IO9 IO10 IO11 IO12 IO13 IO14 IO21 IO47 IO48 IO45 IO35 "
    "IO36 IO37 IO38 IO39 IO40 IO41 IO42 IO2 IO1").split()]


def verify():
    seen = {}
    errors = []
    for net, nodes in NETS.items():
        if len(nodes) < 2:
            errors.append(f"net {net} has a single node")
        for node in nodes:
            ref, pin = node.split(".")
            if ref not in PARTS or pin not in PARTS[ref][2]:
                errors.append(f"net {net}: unknown pin {node}")
            elif node in seen:
                errors.append(f"{node} is on both {seen[node]} and {net}")
            seen[node] = net
    for node in UNCONNECTED:
        if node in seen:
            errors.append(f"{node} is marked unconnected but is on {seen[node]}")
        seen[node] = "(nc)"
    for ref, part in PARTS.items():
        for pin in part[2]:
            if f"{ref}.{pin}" not in seen:
                errors.append(f"{ref}.{pin} is not connected and not marked unconnected")
    if errors:
        sys.exit("netlist errors:\n  " + "\n  ".join(errors))


def netlist():
    out = ['(export (version "E")', "  (components"]
    for ref, (value, footprint, _, lcsc, _, _) in PARTS.items():
        out.append(f'    (comp (ref "{ref}") (value "{value}") (footprint "{footprint}")'
                   f' (fields (field (name "LCSC") "{lcsc}")))')
    out.append("  )")
    out.append("  (nets")
    for code, (net, nodes) in enumerate(NETS.items(), 1):
        out.append(f'    (net (code "{code}") (name "{net}")')
        for node in nodes:
            ref, pin = node.split(".")
            out.append(f'      (node (ref "{ref}") (pin "{PARTS[ref][2][pin]}"))')
        out.append("    )")
    out.append("  )")
    out.append(")")
    return "\n".join(out) + "\n"


def bom():
    groups = {}
    for ref, (value, footprint, _, lcsc, status, populate) in PARTS.items():
        if populate:
            groups.setdefault((value, footprint, lcsc, status), []).append(ref)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "LCSC status"])
    for (value, footprint, lcsc, status), refs in groups.items():
        writer.writerow([value, ",".join(refs), footprint.split(":")[-1], lcsc,
                         {"ok": "confirmed", "?": "confirm", "": "select"}[status]])
    return buf.getvalue()


def main():
    verify()
    outputs = {"wifi-usb-gateway.net": netlist(), "bom-jlcpcb.csv": bom()}
    stale = False
    for name, text in outputs.items():
        path = HERE / name
        if "--check" in sys.argv:
            if not path.exists() or path.read_text() != text:
                print(f"{name} is out of date, rerun gen_netlist.py")
                stale = True
        else:
            path.write_text(text)
    populated = sum(1 for p in PARTS.values() if p[5])
    print(f"{len(PARTS)} parts ({populated} assembled), {len(NETS)} nets: OK")
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
