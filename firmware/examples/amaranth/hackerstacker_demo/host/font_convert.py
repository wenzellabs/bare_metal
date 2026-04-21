#!/usr/bin/env python3
"""Font converter: TTF to font.bin for FPGA flash at 0x080000.

Binary format - see notes.txt for details.
FPGA glyph lookup: addr = offset_table[font] + (char_code << slot_shift)
No multiplier needed!

Usage:
    python3 host/font_convert.py fonts/04B_30__.TTF:16 fonts/04B_03B_.TTF:8 -o build/font.bin
"""

import argparse
import math
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

FLASH_FONT_BASE = 0x080000
MAX_FONTS = 8
FONT_FILE_HEADER_SIZE = 8 + 4 * MAX_FONTS  # 40 bytes


def next_power_of_2(n):
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def render_font(ttf_path, pixel_size):
    font = ImageFont.truetype(ttf_path, pixel_size)
    name = os.path.splitext(os.path.basename(ttf_path))[0][:16]
    height = pixel_size
    orientation = 'H' if height <= 8 else 'V'
    bytes_per_col = math.ceil(height / 8)

    max_width = 0
    for c in range(32, 127):
        advance = int(font.getlength(chr(c)))
        bbox = font.getbbox(chr(c))
        w = bbox[2] - bbox[0] if bbox else 0
        max_width = max(max_width, advance, w)
    if max_width == 0:
        max_width = pixel_size // 2
    width = max_width

    raw_glyph_size = width * bytes_per_col
    slot_size = next_power_of_2(raw_glyph_size)
    slot_shift = int(math.log2(slot_size))

    glyphs = []
    for c in range(256):
        ch = chr(c) if 32 <= c < 127 else ' '
        img = Image.new('1', (width, height), 0)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), ch, font=font, fill=1)
        glyph_data = bytearray(raw_glyph_size)
        for col in range(width):
            for byte_row in range(bytes_per_col):
                byte_val = 0
                for bit in range(8):
                    row = byte_row * 8 + bit
                    if row < height and img.getpixel((col, row)):
                        byte_val |= (1 << bit)
                glyph_data[col * bytes_per_col + byte_row] = byte_val
        glyphs.append(glyph_data)

    print(f"    {name}: orient={orientation} {width}x{height} "
          f"raw={raw_glyph_size}B slot={slot_size}B shift={slot_shift}")
    return {
        'name': name, 'orient': orientation,
        'height': height, 'width': width,
        'glyphs': glyphs,
        'slot_size': slot_size, 'slot_shift': slot_shift,
    }


def build_font_bin(font_specs, output_path):
    fonts = []
    for ttf_path, pixel_size in font_specs:
        print(f"  Rendering {ttf_path} @ {pixel_size}px...")
        fonts.append(render_font(ttf_path, pixel_size))

    num_fonts = len(fonts)
    assert num_fonts <= MAX_FONTS

    out = bytearray()
    out += struct.pack('>BBH', ord('F'), 3, num_fonts)
    out += b'\x00' * 4
    offset_table_pos = len(out)
    out += b'\x00' * (4 * MAX_FONTS)
    assert len(out) == FONT_FILE_HEADER_SIZE

    for i, f in enumerate(fonts):
        glyph_data_addr = FLASH_FONT_BASE + len(out) + 24
        struct.pack_into('>I', out, offset_table_pos + i * 4, glyph_data_addr)
        hdr = bytearray(24)
        hdr[0] = ord('f')
        hdr[1] = 3
        nb = f['name'].encode('ascii')[:16]
        hdr[2:2 + len(nb)] = nb
        hdr[0x12] = ord(f['orient'])
        hdr[0x13] = f['height']
        hdr[0x14] = f['width']
        hdr[0x15] = 255
        hdr[0x16] = f['slot_shift']
        hdr[0x17] = 0
        out += hdr
        for glyph in f['glyphs']:
            slot = bytearray(f['slot_size'])
            slot[:len(glyph)] = glyph
            out += slot

    with open(output_path, 'wb') as fp:
        fp.write(out)
    print(f"Wrote {output_path} ({len(out)} bytes, {num_fonts} fonts)")
    for i, f in enumerate(fonts):
        addr = struct.unpack_from('>I', out, offset_table_pos + i * 4)[0]
        print(f"  [{i}] {f['name']:16s} {f['orient']} {f['width']}x{f['height']} "
              f"shift={f['slot_shift']} glyph_data@0x{addr:06x}")


def main():
    parser = argparse.ArgumentParser(description='Convert TTF fonts to FPGA font.bin')
    parser.add_argument('fonts', nargs='+', help='font:size, e.g. fonts/foo.TTF:16')
    parser.add_argument('-o', '--output', default='build/font.bin')
    args = parser.parse_args()
    font_specs = []
    for spec in args.fonts:
        parts = spec.rsplit(':', 1)
        if len(parts) != 2:
            print(f"Error: expected font:size, got {specrm /home/wenzel/CODE/bare_metal/firmware/examples/amaranth/hackerstacker_demo/host/font_convert.py}", file=sys.stderr)
            sys.exit(1)
        font_specs.append((parts[0], int(parts[1])))
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    build_font_bin(font_specs, args.output)


if __name__ == '__main__':
    main()
