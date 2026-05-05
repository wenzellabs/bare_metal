#!/usr/bin/env python3
"""Demo/test module that writes rainbow pattern to SK9822 framebuffer.

This module generates moving rainbow patterns and writes them to the LED
framebuffer. Short press cycles through display modes:

0 = diagonal rainbow (hue based on LED index, original)
1 = horizontal rainbow scroll (hue based on X + offset)
2 = vertical rainbow scroll (hue based on Y + offset)
3 = h-zigzag rainbow scroll (every 2nd column reversed)
4 = v-zigzag rainbow scroll (every 2nd row reversed)
"""
import sys
from amaranth import Module, Signal, Mux
from amaranth.back import verilog


NUM_RAINBOW_MODES = 10


def make_rainbow_writer(width=8, height=16):
    """Create a module that writes rainbow pattern to SK9822 framebuffer.
    
    Returns module with signals to connect to sk9822_controller write interface.
    """
    m = Module()
    
    num_leds = width * height
    
    # Input: enable signal
    enable = Signal(name="enable")
    short_press = Signal(name="short_press")
    
    # Display mode (cycles on short_press)
    display_mode = Signal(4, name="display_mode")
    
    with m.If(short_press):
        with m.If(display_mode >= NUM_RAINBOW_MODES - 1):
            m.d.sync += display_mode.eq(0)
        with m.Else():
            m.d.sync += display_mode.eq(display_mode + 1)
    
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
    
    # Compute hue based on display mode
    led_index = Signal(range(num_leds))
    m.d.comb += led_index.eq((write_y * width) + write_x)
    
    hue_h = (write_x << 5)   # horizontal: 0,32,64,...,224
    hue_v = (write_y << 4)   # vertical: 0,16,32,...,240
    
    # Zigzag variants
    hue_hzig = Signal(8)
    hue_vzig = Signal(8)
    m.d.comb += [
        hue_hzig.eq(Mux(write_x[0], 255 - hue_v, hue_v)),
        hue_vzig.eq(Mux(write_y[0], 255 - hue_h, hue_h)),
    ]
    
    hue = Signal(8)
    base_mode = Signal(3)
    m.d.comb += base_mode.eq(display_mode >> 1)

    with m.Switch(base_mode):
        with m.Case(0):  # Diagonal (original LED index)
            m.d.comb += hue.eq(led_index[:8] + rainbow_offset)
        with m.Case(1):  # Horizontal scroll
            m.d.comb += hue.eq(hue_h + rainbow_offset)
        with m.Case(2):  # Vertical scroll
            m.d.comb += hue.eq(hue_v + rainbow_offset)
        with m.Case(3):  # H-zigzag scroll
            m.d.comb += hue.eq(hue_hzig + rainbow_offset)
        with m.Case(4):  # V-zigzag scroll
            m.d.comb += hue.eq(hue_vzig + rainbow_offset)
        with m.Default():
            m.d.comb += hue.eq(led_index[:8] + rainbow_offset)
    
    is_trans = Signal()
    m.d.comb += is_trans.eq(display_mode[0] == 0) # Even modes are trans

    # Convert hue to RGB (6-segment rainbow)
    hue_x6 = Signal(11)
    m.d.comb += hue_x6.eq(hue * 6)
    
    segment = Signal(3)
    m.d.comb += segment.eq(hue_x6 >> 8)
    
    # Transgender flag logic based on the 6 segments (0&5: blue, 1&4: pink, 2&3: white)
    trans_r = Signal(8)
    trans_g = Signal(8)
    trans_b = Signal(8)
    with m.Switch(segment):
        with m.Case(0, 5):  # Blue (highly saturated, half brightness)
            m.d.comb += [trans_r.eq(0), trans_g.eq(64), trans_b.eq(128)]
        with m.Case(1, 4):  # Pink (highly saturated, half brightness)
            m.d.comb += [trans_r.eq(128), trans_g.eq(0), trans_b.eq(64)]
        with m.Case(2, 3, 6, 7):  # White (include 6,7 just in case)
            m.d.comb += [trans_r.eq(255), trans_g.eq(255), trans_b.eq(255)]
    
    segment_pos = Signal(8)
    m.d.comb += segment_pos.eq(hue_x6[:8])
    
    # RGB calculation based on segment
    m.d.comb += [wr_r.eq(hue), wr_g.eq(0), wr_b.eq(0)]
    
    ports = [enable, short_press, wr_en, wr_x, wr_y, wr_r, wr_g, wr_b]
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
