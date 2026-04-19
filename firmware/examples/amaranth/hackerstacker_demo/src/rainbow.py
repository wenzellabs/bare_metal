#!/usr/bin/env python3
"""Demo/test module that writes rainbow pattern to SK9822 framebuffer.

This module demonstrates how to use the SK9822 controller's write interface.
It generates a moving rainbow pattern and writes it to the LED framebuffer.
"""
import sys
from amaranth import Module, Signal
from amaranth.back import verilog


def make_rainbow_writer(width=8, height=16):
    """Create a module that writes rainbow pattern to SK9822 framebuffer.
    
    Returns module with signals to connect to sk9822_controller write interface.
    """
    m = Module()
    
    num_leds = width * height
    
    # Input: enable signal
    enable = Signal(name="enable")
    
    # Outputs: connect to sk9822_controller write interface
    wr_en = Signal(name="wr_en")
    wr_x = Signal(range(width), name="wr_x")
    wr_y = Signal(range(height), name="wr_y")
    wr_r = Signal(8, name="wr_r")
    wr_g = Signal(8, name="wr_g")
    wr_b = Signal(8, name="wr_b")
    
    # Animation timer - update rainbow position
    anim_counter = Signal(20)
    anim_update = Signal()
    
    with m.If(enable):
        m.d.sync += anim_counter.eq(anim_counter + 1)
    m.d.comb += anim_update.eq(anim_counter == 0)
    
    # Rainbow offset for animation
    rainbow_offset = Signal(8)
    
    with m.If(anim_update & enable):
        m.d.sync += rainbow_offset.eq(rainbow_offset + 1)
    
    # Write state machine - iterate through all LEDs
    write_x = Signal(range(width))
    write_y = Signal(range(height))
    writing = Signal()  # Currently in write cycle
    
    # Start writing when animation updates and module is enabled
    with m.If(anim_update & ~writing & enable):
        m.d.sync += [
            writing.eq(1),
            write_x.eq(0),
            write_y.eq(0),
        ]
    
    # Write one LED per clock when writing
    with m.If(writing):
        m.d.sync += wr_en.eq(1)
        
        # Increment position
        with m.If(write_x == (width - 1)):
            m.d.sync += [
                write_x.eq(0),
                write_y.eq(write_y + 1),
            ]
            # Done when we've written all rows
            with m.If(write_y == (height - 1)):
                m.d.sync += writing.eq(0)
        with m.Else():
            m.d.sync += write_x.eq(write_x + 1)
    with m.Else():
        m.d.sync += wr_en.eq(0)
    
    # Connect write coordinates
    m.d.comb += [
        wr_x.eq(write_x),
        wr_y.eq(write_y),
    ]
    
    # Compute rainbow color for current position
    # Use linear LED index for hue
    led_index = Signal(range(num_leds))
    m.d.comb += led_index.eq((write_y * width) + write_x)
    
    hue = Signal(8)
    m.d.comb += hue.eq(led_index[:8] + rainbow_offset)
    
    # Convert hue to RGB (6-segment rainbow, each segment gets 256/6 = ~42.67 hue values)
    # We'll use integer division: 256/6 = 42 with remainder, so segments are slightly unequal
    # Multiply hue by 6, then take top bits to get segment (0-5)
    hue_x6 = Signal(11)  # hue * 6 needs 11 bits (max 255*6 = 1530)
    m.d.comb += hue_x6.eq(hue * 6)
    
    segment = Signal(3)
    m.d.comb += segment.eq(hue_x6 >> 8)  # Divide by 256 to get segment 0-5
    
    segment_pos = Signal(8)
    m.d.comb += segment_pos.eq(hue_x6[:8])  # Bottom 8 bits = position within segment
    
    # RGB calculation based on segment
    with m.Switch(segment):
        with m.Case(0):  # Red to Yellow
            m.d.comb += [
                wr_r.eq(255),
                wr_g.eq(segment_pos),
                wr_b.eq(0),
            ]
        with m.Case(1):  # Yellow to Green
            m.d.comb += [
                wr_r.eq(255 - segment_pos),
                wr_g.eq(255),
                wr_b.eq(0),
            ]
        with m.Case(2):  # Green to Cyan
            m.d.comb += [
                wr_r.eq(0),
                wr_g.eq(255),
                wr_b.eq(segment_pos),
            ]
        with m.Case(3):  # Cyan to Blue
            m.d.comb += [
                wr_r.eq(0),
                wr_g.eq(255 - segment_pos),
                wr_b.eq(255),
            ]
        with m.Case(4):  # Blue to Magenta
            m.d.comb += [
                wr_r.eq(segment_pos),
                wr_g.eq(0),
                wr_b.eq(255),
            ]
        with m.Case(5):  # Magenta to Red
            m.d.comb += [
                wr_r.eq(255),
                wr_g.eq(0),
                wr_b.eq(255 - segment_pos),
            ]
    
    ports = [enable, wr_en, wr_x, wr_y, wr_r, wr_g, wr_b]
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/rainbow.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    m, ports = make_rainbow_writer(width=8, height=16)
    
    v = verilog.convert(m, name="rainbow_module", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
