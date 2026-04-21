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


def make_font_render(base_addr=0x080858, shift=3, bytes_to_read=8):
    """Create font renderer module.

    Returns:
        (module, ports) tuple
    """
    m = Module()

    # Control interface
    char_code = Signal(8, name="char_code")           # ASCII character to look up
    render_enable = Signal(name="render_enable")      # Pulse to start lookup
    render_done = Signal(name="render_done")          # Pulse when pattern is ready
    busy = Signal(name="busy")                        # Lookup in progress

    # Output
    segment_pattern = Signal(bytes_to_read * 8, name="segment_pattern")  # Segment pattern

    # Flash controller interface
    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")

    # Internal
    byte_idx = Signal(4, name="byte_idx")
    render_enable_prev = Signal(name="render_enable_prev")  # For edge detection
    render_enable_rising = Signal(name="render_enable_rising")

    # Edge detect: only trigger on 0->1 transition of render_enable
    m.d.sync += render_enable_prev.eq(render_enable)
    m.d.comb += render_enable_rising.eq(render_enable & ~render_enable_prev)

    # State machine for font lookup
    with m.FSM(name="font_fsm") as fsm:
        m.d.comb += busy.eq(~fsm.ongoing("IDLE"))

        # IDLE: Wait for render request (rising edge only)
        with m.State("IDLE"):
            m.d.sync += [
                render_done.eq(0),
                flash_read_en.eq(0),
                byte_idx.eq(0),
            ]

            with m.If(render_enable_rising):
                # Optimize adder: upper 12 bits are constant 0x080.
                addr_low = Signal(12)
                m.d.comb += addr_low.eq((base_addr & 0xFFF) + (char_code << shift))
                m.d.sync += [
                    flash_read_addr.eq(Cat(addr_low, Const(base_addr >> 12, 12))),
                    flash_read_en.eq(1),
                ]
                m.next = "READ_BYTE"

        with m.State("READ_BYTE"):
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)

            with m.If(flash_read_valid):
                m.d.sync += segment_pattern.word_select(byte_idx, 8).eq(flash_read_data)
                
                with m.If(byte_idx == bytes_to_read - 1):
                    m.d.sync += [
                        render_done.eq(1),
                    ]
                    m.next = "IDLE"
                with m.Else():
                    m.d.sync += [
                        byte_idx.eq(byte_idx + 1),
                        flash_read_addr.eq(flash_read_addr + 1),
                        flash_read_en.eq(1),
                    ]

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
