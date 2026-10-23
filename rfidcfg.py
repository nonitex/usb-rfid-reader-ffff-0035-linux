#!/usr/bin/env python3
"""Linux config tool for the white USB-C 125 kHz RFID reader (VID ffff, PID 0035).

Re-implements the "USB reader intelligent setting" page of the Windows tool
(0012752907.exe + usb.dll). The reader has two HID interfaces: #0 is the
keyboard that types the card number, #1 has no endpoints and is used for
configuration through HID feature reports (control transfers on EP0):

  SET_REPORT feature, report ID 1, 256 bytes:
      01 00 00 00 | idx:u16le=0 | len:u16le | frame[len] | zero padding
  GET_REPORT feature, report ID 2, 256 bytes:
      frame starts at offset 8

  frame = AA <addr> <len> <data...> <bcc> BB, bcc = XOR(addr, len, data...)

  read config:  data = 83
  write config: data = 82 <fmt> <semicolon> <qmark> <comma> <enter> 00 00 00
  response:     AA <addr> <len> <status 00=ok> ...; for 83: byte5=fmt,
                byte6=semicolon, byte7=?, byte8=comma, byte9=enter
"""
import argparse
import sys
import time

import usb.core
import usb.util

VID, PID = 0xFFFF, 0x0035
IFACE = 1
REPORT_SIZE = 256

# code -> description, as in the Windows tool
FORMATS = {
    0x07: "10 hex digits",
    0x0C: "8 hex digits",
    0x03: "8 hex digits, reversed",
    0x0D: "00 + 8 decimal digits (last 3 bytes)",
    0x0B: "8 decimal digits (last 3 bytes)",
    0x06: "18 decimal digits",
    0x0E: "8 decimal digits (last 4 bytes), bottom-row button",
    0x08: "5 decimal digits",
    0x09: "8 decimal digits (last 4 bytes)",
    0x0A: "10 decimal digits, reversed",
    0x05: "13 decimal digits",
    0x0F: "10 decimal digits (4 bytes) - factory default",
    0x00: "2H4D + 2H4D (2 hex + 4 decimal, twice)",
}


def frame(data, addr=0):
    body = [addr, len(data)] + list(data)
    bcc = 0
    for b in body:
        bcc ^= b
    return bytes([0xAA] + body + [bcc, 0xBB])


def open_dev():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("Reader (ffff:0035) not found.")
    return dev


def transact(dev, data):
    fr = frame(data)
    rep = bytearray(REPORT_SIZE)
    rep[0] = 0x01
    rep[6:8] = len(fr).to_bytes(2, "little")
    rep[8:8 + len(fr)] = fr
    try:
        # SET_REPORT, feature (3), report ID 1
        dev.ctrl_transfer(0x21, 0x09, 0x0301, IFACE, bytes(rep))
        time.sleep(0.3)
        # GET_REPORT, feature (3), report ID 2
        resp = bytes(dev.ctrl_transfer(0xA1, 0x01, 0x0302, IFACE, REPORT_SIZE))
    except usb.core.USBError as e:
        if e.errno == 13:
            sys.exit("Permission denied - install 70-rfid-reader.rules (see README.md).")
        raise
    r = resp[8:]
    if len(r) < 5 or r[0] != 0xAA:
        sys.exit("Unexpected response: " + resp[:32].hex(" "))
    return r[: r[2] + 5]


def cmd_read(dev, verbose):
    r = transact(dev, [0x83])
    if verbose:
        print("raw:", r.hex(" "))
    if r[3] != 0x00:
        sys.exit("Read failed, status %02X" % r[3])
    fmt = r[5]
    print("Output format: %02X  %s" % (fmt, FORMATS.get(fmt, "unknown")))
    print("Semicolon:     %s" % ("yes" if r[6] else "no"))
    print("Question mark: %s" % ("yes" if r[7] else "no"))
    print("Comma:         %s" % ("yes" if r[8] else "no"))
    print("Enter:         %s" % ("yes" if r[9] else "no"))


def cmd_set(dev, a, verbose):
    data = [0x82, a.format, a.semicolon, a.qmark, a.comma, a.enter, 0, 0, 0]
    r = transact(dev, data)
    if verbose:
        print("raw:", r.hex(" "))
    if r[3] != 0x00:
        sys.exit("Set failed, status %02X" % r[3])
    print("Set up success.")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-v", "--verbose", action="store_true", help="print raw frames")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("read", help="read current settings")
    sub.add_parser("formats", help="list output format codes")
    s = sub.add_parser("set", help="write settings")
    s.add_argument("format", type=lambda x: int(x, 16),
                   help="format code in hex, see 'formats' (default reader: 0F)")
    for opt in ("enter", "semicolon", "qmark", "comma"):
        s.add_argument("--" + opt, type=int, choices=(0, 1), default=1 if opt == "enter" else 0)
    a = p.parse_args()

    if a.cmd == "formats":
        for k, v in FORMATS.items():
            print("%02X  %s" % (k, v))
        return
    if a.cmd == "set" and a.format not in FORMATS:
        sys.exit("Unknown format code %02X" % a.format)
    dev = open_dev()
    if a.cmd == "read":
        cmd_read(dev, a.verbose)
    else:
        cmd_set(dev, a, a.verbose)


if __name__ == "__main__":
    main()
