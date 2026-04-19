#!/usr/bin/env python3
"""Font renderer module for 16-segment display.

This module reads font data from flash memory at address 0x050000 and
returns the 16-bit segment pattern for a requested character.

Indexed font format in flash (starting at 0x050000):
    256 x 16-byte slots = 4096 bytes total.

    Slot 0 (char code 0x00) = Header:
        [0x00] MAGIC:8        'F' (0x46)
        [0x01] BITS_PER_CHAR:8
        [0x02] CHARS_USED:8
        [0x03] RESERVED:5     (zeros)
        [0x08] FONT_NAME:8    (ASCII)

    Slots 1-255 = Glyph data:
        Each char code 0x01-0xFF has a 16-byte slot at:
            offset = char_code x 16
        First 2 bytes = segment pattern (big-endian)

    NUL (0x00) reads the header, which gives garbage segments.
    This is fine - nobody prints NUL.

O(1) lookup with ZERO adders - pure wiring:
    flash_addr[23:12] = 0x050       (constant)
    flash_addr[11:4]  = char_code   (wired directly)
    flash_addr[3:0]   = byte index  (0 for high, 1 for low)

Only 2 flash reads per character (high byte + low byte).

Usage:
    The parent module should:
    1. Set char_code to the ASCII value to render
    2. Pulse render_enable high for 1 cycle
    3. Wait for render_done to pulse high
    4. Read segment_pattern[15:0] - 16 bits for the segments

    Each bit in segment_pattern corresponds to one of the 16 LEDs in a
    Digitus16 digit. Bit=1 means the segment should be lit.
"""

import sys
from amaranth import Module, Signal, Cat, Const
from amaranth.back import verilog


def make_font_render():
    """Create font renderer module.

    Returns:
        (module, ports) tuple
    """
    m = Module()

    # Flash address for font data
    # Font lives at 0x080000, slots are 16 bytes each.
    # Address = {0x080, char_code[7:0], 4'b0000} - pure wiring, zero adders.
    ADDR_FONT_PAGE = 0x080  # upper 12 bits: 0x080000 >> 12 = 0x080

    # Control interface
    char_code = Signal(8, name="char_code")           # ASCII character to look up
    render_enable = Signal(name="render_enable")      # Pulse to start lookup
    render_done = Signal(name="render_done")          # Pulse when pattern is ready
    busy = Signal(name="busy")                        # Lookup in progress

    # Output
    segment_pattern = Signal(16, name="segment_pattern")  # 16-bit segment pattern

    # Flash controller interface
    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")

    # Internal
    segment_high = Signal(8, name="segment_high")     # High byte of segment pattern
    render_enable_prev = Signal(name="render_enable_prev")  # For edge detection
    render_enable_rising = Signal(name="render_enable_rising")

    # Edge detect: only trigger on 0->1 transition of render_enable
    m.d.sync += render_enable_prev.eq(render_enable)
    m.d.comb += render_enable_rising.eq(render_enable & ~render_enable_prev)

    # State machine for font lookup - only 4 states now!
    with m.FSM(name="font_fsm") as fsm:
        m.d.comb += busy.eq(~fsm.ongoing("IDLE"))

        # IDLE: Wait for render request (rising edge only)
        with m.State("IDLE"):
            m.d.sync += [
                render_done.eq(0),
                flash_read_en.eq(0),
            ]

            with m.If(render_enable_rising):
                # Direct indexed lookup - pure wiring, zero adders:
                # addr = {0x050 (12 bits), char_code (8 bits), 0000 (4 bits)}
                m.d.sync += [
                    flash_read_addr.eq(
                        Cat(Const(0, 4), char_code, Const(ADDR_FONT_PAGE, 12))
                    ),
                    flash_read_en.eq(1),
                ]
                m.next = "READ_HIGH"

        # READ_HIGH: Read high byte of segment pattern
        with m.State("READ_HIGH"):
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)

            with m.If(flash_read_valid):
                m.d.sync += [
                    segment_high.eq(flash_read_data),
                    flash_read_addr.eq(flash_read_addr + 1),
                    flash_read_en.eq(1),
                ]
                m.next = "READ_LOW"

        # READ_LOW: Read low byte of segment pattern
        with m.State("READ_LOW"):
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)

            with m.If(flash_read_valid):
                # Combine high and low bytes into 16-bit pattern
                m.d.sync += [
                    segment_pattern[8:16].eq(segment_high),
                    segment_pattern[0:8].eq(flash_read_data),
                    render_done.eq(1),
                ]
                m.next = "IDLE"

    # Port list for Verilog generation
    ports = [
        char_code,
        render_enable,
        render_done,
        busy,
        segment_pattern,
        flash_read_en,
        flash_read_addr,
        flash_read_data,
        flash_read_valid,
        flash_busy,
        flash_ready,
    ]

    return m, ports


if __name__ == "__main__":
    # Generate Verilog
    if len(sys.argv) < 2:
        print("Usage: python3 src/font_render.py <output.v>")
        sys.exit(1)

    m, ports = make_font_render()
    v = verilog.convert(m, name="font_render", ports=ports)

    with open(sys.argv[1], "w") as f:
        f.write(v)

    print(f"Wrote {sys.argv[1]}")
