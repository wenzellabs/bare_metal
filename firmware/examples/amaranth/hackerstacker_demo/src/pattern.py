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
    4 = rainbow h-zigzag (every 2nd column reversed)
    5 = rainbow v-zigzag (every 2nd row reversed)
    6 = angled gradient (1,2): hue = x + 2*y
    7 = angled gradient (2,1): hue = 2*x + y
    8 = angled gradient (1,-2): hue = x - 2*y
    9 = angled gradient (2,-1): hue = 2*x - y
    10 = knight tile inverted 10/11/01 (2×3)
    """
    m = Module()
    
    # Create writer interface
    writer = SK9822Writer(width=width, height=height, name_prefix="pattern_")
    
    # Enable signal - triggers redraw when this module becomes active
    enable = Signal(name="enable")
    
    # Display mode selector: 0-9 for ten patterns
    display_mode = Signal(4, name="display_mode")
    
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
        hue_v = (draw_y << 4)  # Y: 0,16,32,...,240
        
        # Zigzag: reverse every 2nd column (h) or row (v)
        hue_h_rev = Signal(8)
        hue_v_rev = Signal(8)
        m.d.comb += [
            hue_h_rev.eq(Mux(draw_x[0], 255 - hue_v, hue_v)),  # flip Y hue on odd columns
            hue_v_rev.eq(Mux(draw_y[0], 255 - hue_h, hue_h)),  # flip X hue on odd rows
        ]
        
        # Angled gradients (scaled to spread hue across grid)
        # Each uses a different linear combination of x,y
        angled_raw = Signal(16)
        with m.Switch(display_mode):
            with m.Case(6):  # (1,2): x + 2*y, range 0..39, *6 to spread
                m.d.comb += angled_raw.eq((draw_x + (draw_y << 1)) * 6)
            with m.Case(7):  # (2,1): 2*x + y, range 0..30, *8 to spread
                m.d.comb += angled_raw.eq(((draw_x << 1) + draw_y) * 8)
            with m.Case(8):  # (1,-2): x - 2*y + 30 (offset to keep positive), *6
                m.d.comb += angled_raw.eq((draw_x + 30 - (draw_y << 1)) * 6)
            with m.Case(9):  # (2,-1): 2*x - y + 15, *8
                m.d.comb += angled_raw.eq(((draw_x << 1) + 15 - draw_y) * 8)
            with m.Default():
                m.d.comb += angled_raw.eq(0)
        angled_hue = Signal(8)
        m.d.comb += angled_hue.eq(angled_raw[:8])
        
        hue = Signal(8)
        
        with m.Switch(display_mode):
            with m.Case(2):  # Rainbow horizontal
                m.d.comb += hue.eq(hue_h)
            with m.Case(3):  # Rainbow vertical
                m.d.comb += hue.eq(hue_v)
            with m.Case(4):  # H-zigzag
                m.d.comb += hue.eq(hue_h_rev)
            with m.Case(5):  # V-zigzag
                m.d.comb += hue.eq(hue_v_rev)
            with m.Case(6, 7, 8, 9):  # Angled gradient patterns
                m.d.comb += hue.eq(angled_hue)
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
        
        # Knight's move tile patterns (modes 10-14)
        # Compute mod-3 for tiling
        # y mod 3 via conditional subtraction (y is 0-15)
        y_mod3 = Signal(2)
        y_tmp1 = Signal(5)
        y_tmp2 = Signal(5)
        m.d.comb += [
            y_tmp1.eq(Mux(draw_y >= 12, draw_y - 12, draw_y)),
            y_tmp2.eq(Mux(y_tmp1 >= 6, y_tmp1 - 6, y_tmp1)),
            y_mod3.eq(Mux(y_tmp2 >= 3, y_tmp2 - 3, y_tmp2)),
        ]
        # x mod 3 via conditional subtraction (x is 0-7)
        x_mod3 = Signal(2)
        x_tmp = Signal(4)
        m.d.comb += [
            x_tmp.eq(Mux(draw_x >= 6, draw_x - 6, draw_x)),
            x_mod3.eq(Mux(x_tmp >= 3, x_tmp - 3, x_tmp)),
        ]
        
        tile_pixel = Signal()
        with m.Switch(display_mode):
            with m.Case(10):  # 10/11/01 (inverted knight tile)
                m.d.comb += tile_pixel.eq(
                    ~(((draw_x[0]) & (y_mod3 == 0)) |
                      ((~draw_x[0]) & (y_mod3 == 2)))
                )
            with m.Default():
                m.d.comb += tile_pixel.eq(0)
        
        tile_val = Mux(tile_pixel, 255, 0)
        
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
            with m.Case(10):  # Knight tile pattern
                m.d.sync += [
                    writer.wr_en.eq(1),
                    writer.wr_x.eq(draw_x),
                    writer.wr_y.eq(draw_y),
                    writer.wr_r.eq(tile_val),
                    writer.wr_g.eq(tile_val),
                    writer.wr_b.eq(tile_val),
                ]
            with m.Default():  # Rainbow-based modes (2-9)
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
