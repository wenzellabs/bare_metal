#!/usr/bin/env python3
"""Convert font definition to indexed flash format for LED display.

This tool converts the 16-segment font definition to an indexed lookup
table in flash. Each of the 256 possible char codes gets a fixed 16-byte
slot, enabling O(1) lookup via address arithmetic on the FPGA
(no linear search needed).

Flash format (at 0x050000):
    Slot 0 = Header (16 bytes):
        [0x00] MAGIC:8        'F' (0x46)
        [0x01] BITS_PER_CHAR:8 Number of bits used per glyph (16 for 16-seg, 128 for 8x16 bitmap)
        [0x02] CHARS_USED:8   Number of populated glyph slots (informational)
        [0x03] RESERVED:5     Reserved bytes (zeros)
        [0x08] FONT_NAME:8    Font name (ASCII, null-padded)

    Slots 1-255 = Glyph data (16 bytes each):
        Each char code 0x01-0xFF has a 16-byte slot at:
            offset = char_code x 16
        For 16-segment font: first 2 bytes = segment pattern (big-endian),
                             remaining 14 bytes = 0x00
        For future 8x16 bitmap: all 16 bytes used (128 bits)

    Char code 0x00 (NUL) has no glyph - its slot IS the header.
    This is fine because NUL is never a printable character.

    Total size: 256 x 16 = 4096 bytes

FPGA address calculation (pure wiring, zero LUTs, zero adders):
    glyph_addr = 0x050 : char_code[7:0] : 0000
    i.e. flash_addr[23:12] = 0x050
         flash_addr[11:4]  = char_code
         flash_addr[3:0]   = byte within slot
"""

import sys
import struct
from font import FONT


SLOT_SIZE = 16       # bytes per glyph slot
NUM_SLOTS = 256      # slot 0 = header, slots 1-255 = glyphs
FONT_NAME = "16seg"  # default font name


def create_flash_font(output_file, font_name=FONT_NAME):
    """Convert font definition to indexed flash format.

    Args:
        output_file: Path to output binary file
        font_name: Font name string (max 8 chars, null-padded)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Build lookup: char_code -> segment_pattern
        glyph_map = {}
        for char, segments in FONT:
            char_code = ord(char) & 0xFF
            glyph_map[char_code] = segments

        chars_used = len(glyph_map)
        bits_per_char = 16  # 16-segment font
        total_size = NUM_SLOTS * SLOT_SIZE  # 256 x 16 = 4096

        print(f"Converting {chars_used} glyphs to indexed format: {output_file}")
        print(f"  Bits per char: {bits_per_char}")
        print(f"  Slot size: {SLOT_SIZE} bytes")
        print(f"  Slot 0: header (NUL char not printable)")
        print(f"  Slots 1-255: glyph data")
        print(f"  Total: {total_size} bytes")
        print(f"  Font name: \"{font_name}\"")

        with open(output_file, 'wb') as f:
            # === Slot 0: Header (16 bytes) ===
            # NUL (char code 0) is never printed, so its slot doubles as header
            header = bytearray(SLOT_SIZE)
            header[0] = ord('F')           # magic
            header[1] = bits_per_char      # bits_per_char
            header[2] = chars_used & 0xFF  # chars_used
            # header[3:8] = reserved (zeros)

            # font name (8 bytes, null-padded)
            name_bytes = font_name.encode('ascii')[:8]
            header[8:8 + len(name_bytes)] = name_bytes

            f.write(header)

            # === Slots 1-255: Glyph data (16 bytes each) ===
            for char_code in range(1, NUM_SLOTS):
                slot = bytearray(SLOT_SIZE)
                if char_code in glyph_map:
                    segments = glyph_map[char_code]
                    # Reverse bit order: bit 0 <-> bit 15, etc.
                    # Physical LED chain runs opposite to our bit numbering
                    reversed_seg = int(f'{segments:016b}'[::-1], 2)
                    # Store as big-endian 16-bit in first 2 bytes
                    slot[0] = (reversed_seg >> 8) & 0xFF
                    slot[1] = reversed_seg & 0xFF
                f.write(slot)

        # Print some stats
        print(f"  Populated slots: {chars_used}/{NUM_SLOTS}")
        print(f"  Char range: 0x{min(glyph_map.keys()):02X} - 0x{max(glyph_map.keys()):02X}")
        print(f"  Created {output_file} ({total_size} bytes)")

        # Verify a known glyph
        m_code = ord('m')
        if m_code in glyph_map:
            m_offset = m_code * SLOT_SIZE
            m_seg = glyph_map[m_code]
            print(f"  Verify: 'm' (0x{m_code:02X}) at offset 0x{m_offset:04X}, pattern=0b{m_seg:016b}")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 host/font_convert.py output.bin [font_name]")
        print()
        print("Arguments:")
        print("  output.bin       Output binary file for flash")
        print("  font_name        Optional font name (max 8 chars, default: '16seg')")
        print()
        print("Flash format: 256 x 16-byte slots = 4096 bytes (slot 0 = header)")
        print("Char codes 0x01-0xFF get direct slots. NUL (0x00) = header.")
        print("FPGA lookup: addr = 0x050 : char_code : 0x0 (pure wiring)")
        print()
        print("Example:")
        print("  python3 host/font_convert.py build/font.bin")
        print("  tinyprog -a 0x050000 build/font.bin")
        sys.exit(1)

    output_file = sys.argv[1]
    font_name = sys.argv[2] if len(sys.argv) > 2 else FONT_NAME

    success = create_flash_font(output_file, font_name)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
