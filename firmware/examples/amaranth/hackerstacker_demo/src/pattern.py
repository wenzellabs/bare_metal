#!/usr/bin/env python3
"""Pattern display module for SK9822 LED array.

Displays various patterns.
"""
import sys
from amaranth import Module, Signal, Mux
from amaranth.back import verilog
from sk9822 import SK9822Writer


def make_pattern_module(width=8, height=16):
    """Create pattern display module with multiple test patterns.
    
    Draws patterns based on display_mode:
    0 = checkerboard (black & white)
    1 = checkerboard inverted (white & black)
    2 = rainbow horizontal (hue varies with X)
    3 = rainbow vertical (hue varies with Y)
    """
    m = Module()
    
    # Create writer interface
    writer = SK9822Writer(width=width, height=height, name_prefix="pattern_")
    
    # Enable signal - triggers redraw when this module becomes active
    enable = Signal(name="enable")
    
    # Display mode selector: 0-3 for four patterns
    display_mode = Signal(2, name="display_mode")
    
    # State machine to draw checkerboard
    drawing = Signal()
    draw_x = Signal(range(width))
    draw_y = Signal(range(height))
    
    # Start drawing when enabled and not already drawing
    with m.If(enable & ~drawing):
        m.d.sync += [
            drawing.eq(1),
            draw_x.eq(0),
            draw_y.eq(0),
        ]
    
    # Draw pattern based on mode
    with m.If(drawing):
        # Compute base patterns
        checkerboard = Mux((draw_x + draw_y) & 1, 255, 0)
        checkerboard_inv = Mux((draw_x + draw_y) & 1, 0, 255)
        
        # Rainbow calculation: convert position to hue (0-255), then to RGB
        # For horizontal: use X coordinate scaled to full hue range
        # For vertical: use Y coordinate scaled to full hue range
        hue_h = (draw_x << 5)  # X: 0,32,64,96,128,160,192,224
        hue_v = (draw_y << 4)  # Y: 0,16,32,48,64,80,96,112,128,144,160,176,192,208,224,240
        
        # We'll compute RGB for both and select based on mode
        # Rainbow uses 6 segments across the hue wheel
        # Segment boundaries at hue values: 0, 43, 85, 128, 171, 213, 255
        
        # Helper function to compute RGB from hue (we'll do this inline)
        # For mode 2 (rainbow_h): use hue_h
        # For mode 3 (rainbow_v): use hue_v
        hue = Signal(8)
        
        with m.Switch(display_mode):
            with m.Case(2):  # Rainbow horizontal
                m.d.comb += hue.eq(hue_h)
            with m.Case(3):  # Rainbow vertical
                m.d.comb += hue.eq(hue_v)
            with m.Default():
                m.d.comb += hue.eq(0)
        
        # Rainbow RGB calculation (6-segment HSV to RGB)
        # hue * 6 to get position in extended range
        hue_x6 = Signal(14)  # hue (8-bit) * 6 needs 11 bits, but we use 14 for safety
        m.d.comb += hue_x6.eq(hue * 6)
        
        # Segment index (0-5) is top 3 bits after multiply by 6
        segment = Signal(3)
        m.d.comb += segment.eq(hue_x6 >> 8)
        
        # Position within segment (0-255)
        seg_pos = Signal(8)
        m.d.comb += seg_pos.eq(hue_x6[:8])
        
        # Rising and falling values
        rising = seg_pos
        falling = Signal(8)
        m.d.comb += falling.eq(255 - seg_pos)
        
        # RGB values for rainbow
        rainbow_r = Signal(8)
        rainbow_g = Signal(8)
        rainbow_b = Signal(8)
        
        with m.Switch(segment):
            with m.Case(0):  # Red -> Yellow (R=255, G=rising, B=0)
                m.d.comb += [rainbow_r.eq(255), rainbow_g.eq(rising), rainbow_b.eq(0)]
            with m.Case(1):  # Yellow -> Green (R=falling, G=255, B=0)
                m.d.comb += [rainbow_r.eq(falling), rainbow_g.eq(255), rainbow_b.eq(0)]
            with m.Case(2):  # Green -> Cyan (R=0, G=255, B=rising)
                m.d.comb += [rainbow_r.eq(0), rainbow_g.eq(255), rainbow_b.eq(rising)]
            with m.Case(3):  # Cyan -> Blue (R=0, G=falling, B=255)
                m.d.comb += [rainbow_r.eq(0), rainbow_g.eq(falling), rainbow_b.eq(255)]
            with m.Case(4):  # Blue -> Magenta (R=rising, G=0, B=255)
                m.d.comb += [rainbow_r.eq(rising), rainbow_g.eq(0), rainbow_b.eq(255)]
            with m.Case(5, 6, 7):  # Magenta -> Red (R=255, G=0, B=falling)
                m.d.comb += [rainbow_r.eq(255), rainbow_g.eq(0), rainbow_b.eq(falling)]
        
        # Select pattern based on display_mode
        with m.Switch(display_mode):
            with m.Case(0):  # Checkerboard
                m.d.sync += [
                    writer.wr_en.eq(1),
                    writer.wr_x.eq(draw_x),
                    writer.wr_y.eq(draw_y),
                    writer.wr_r.eq(checkerboard),
                    writer.wr_g.eq(checkerboard),
                    writer.wr_b.eq(checkerboard),
                ]
            with m.Case(1):  # Checkerboard inverted
                m.d.sync += [
                    writer.wr_en.eq(1),
                    writer.wr_x.eq(draw_x),
                    writer.wr_y.eq(draw_y),
                    writer.wr_r.eq(checkerboard_inv),
                    writer.wr_g.eq(checkerboard_inv),
                    writer.wr_b.eq(checkerboard_inv),
                ]
            with m.Case(2):  # Rainbow horizontal
                m.d.sync += [
                    writer.wr_en.eq(1),
                    writer.wr_x.eq(draw_x),
                    writer.wr_y.eq(draw_y),
                    writer.wr_r.eq(rainbow_r),
                    writer.wr_g.eq(rainbow_g),
                    writer.wr_b.eq(rainbow_b),
                ]
            with m.Case(3):  # Rainbow vertical
                m.d.sync += [
                    writer.wr_en.eq(1),
                    writer.wr_x.eq(draw_x),
                    writer.wr_y.eq(draw_y),
                    writer.wr_r.eq(rainbow_r),
                    writer.wr_g.eq(rainbow_g),
                    writer.wr_b.eq(rainbow_b),
                ]
        
        # Move to next pixel
        with m.If(draw_x == (width - 1)):
            m.d.sync += [
                draw_x.eq(0),
                draw_y.eq(draw_y + 1),
            ]
            # When done with all rows, restart from beginning (continuous redraw)
            with m.If(draw_y == (height - 1)):
                m.d.sync += [
                    draw_x.eq(0),
                    draw_y.eq(0),
                    # Keep drawing=1 so we loop continuously
                ]
        with m.Else():
            m.d.sync += draw_x.eq(draw_x + 1)
    with m.Else():
        # Not drawing - disable write
        m.d.sync += writer.clear()
    
    # Export enable, display_mode, and writer signals as module ports
    ports = [enable, display_mode] + writer.signals
    
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/pattern.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    m, ports = make_pattern_module(width=8, height=16)
    
    v = verilog.convert(m, name="pattern_module", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
