#!/usr/bin/env python3
"""Nick converter: nick.txt -> nick.bin for FPGA flash at 0x0a0000.

Binary format:
    Nick file header (8 bytes):
        [0x00] MAGIC:8       'N' (0x4E)
        [0x01] VERSION:8     3
        [0x02] NUM_NICKS:16  big-endian
        [0x04] RESERVED:32   zeros

    Per-nick entry header (16 bytes):
        [0x00] MAGIC:8       'n' (0x6E)
        [0x01] VERSION:8     3
        [0x02] INDEX:16      1-based index (big-endian)
        [0x04] FG_R:8
        [0x05] FG_G:8
        [0x06] FG_B:8
        [0x07] BG_R:8
        [0x08] BG_G:8
        [0x09] BG_B:8
        [0x0A] STRLEN:16     big-endian
        [0x0C] RESERVED:32   zeros

    Per-nick entry data:
        [STRLEN bytes]       ASCII nick text
        [padding]            zero-padded to next 8-byte boundary

Input format (nick.txt):
    # comment
    name,R,G,B[,BG_R,BG_G,BG_B]

Usage:
    python3 host/nick_convert.py nick.txt -o build/nick.bin
"""

import argparse
import os
import struct
import sys


def parse_nick_file(path):
    """Parse nick.txt, returns list of (name, fg_rgb, bg_rgb)."""
    nicks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('~')
            if len(parts) < 4:
                continue
            name = parts[0]
            fg = (int(parts[1]), int(parts[2]), int(parts[3]))
            if len(parts) >= 7:
                bg = (int(parts[4]), int(parts[5]), int(parts[6]))
            else:
                bg = (0, 0, 0)
            nicks.append((name, fg, bg))
    return nicks


def build_nick_bin(nicks, output_path):
    out = bytearray()

    # File header (8 bytes)
    out += struct.pack('>BBH', ord('N'), 3, len(nicks))
    out += b'\x00' * 4  # reserved

    for i, (name, fg, bg) in enumerate(nicks):
        text = name.encode('ascii')
        strlen = len(text)
        padded_len = ((strlen + 7) // 8) * 8  # pad to 8-byte boundary

        # Entry header (16 bytes)
        hdr = bytearray(16)
        hdr[0] = ord('n')
        hdr[1] = 3
        struct.pack_into('>H', hdr, 2, i + 1)  # 1-based index
        hdr[4] = fg[0]
        hdr[5] = fg[1]
        hdr[6] = fg[2]
        hdr[7] = bg[0]
        hdr[8] = bg[1]
        hdr[9] = bg[2]
        struct.pack_into('>H', hdr, 10, strlen)
        # bytes 12-15 reserved (zeros)
        out += hdr

        # Entry data (padded to 8-byte boundary)
        entry = bytearray(padded_len)
        entry[:strlen] = text
        out += entry

    with open(output_path, 'wb') as fp:
        fp.write(out)

    print(f"Wrote {output_path} ({len(out)} bytes, {len(nicks)} nicks)")
    for i, (name, fg, bg) in enumerate(nicks):
        print(f"  [{i}] \"{name}\" fg=({fg[0]},{fg[1]},{fg[2]}) bg=({bg[0]},{bg[1]},{bg[2]})")


def main():
    parser = argparse.ArgumentParser(description='Convert nick.txt to FPGA nick.bin')
    parser.add_argument('input', help='nick.txt file')
    parser.add_argument('-o', '--output', default='build/nick.bin')
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    nicks = parse_nick_file(args.input)
    if not nicks:
        print("Error: no nicks found", file=sys.stderr)
        sys.exit(1)
    build_nick_bin(nicks, args.output)


if __name__ == '__main__':
    main()
