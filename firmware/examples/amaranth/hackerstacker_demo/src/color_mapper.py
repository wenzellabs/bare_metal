import sys
from amaranth import Module, Signal
from amaranth.back import verilog

def make_color_mapper():
    """Create a standalone module that maps 8-bit hue or colors to RGB.
    
    Inputs:
        hue (8-bit): raw hue value
        mode (2-bit): 0 = off, 1 = raw (passthrough), 2 = rainbow, 3 = trans
        raw_r, raw_g, raw_b (8-bit): raw color data
        
    Outputs:
        rgb_r, rgb_g, rgb_b (8-bit)
    """
    m = Module()
    
    hue = Signal(8, name="hue")
    mode = Signal(2, name="mode")
    raw_r = Signal(8, name="raw_r")
    raw_g = Signal(8, name="raw_g")
    raw_b = Signal(8, name="raw_b")
    
    rgb_r = Signal(8, name="rgb_r")
    rgb_g = Signal(8, name="rgb_g")
    rgb_b = Signal(8, name="rgb_b")
    
    # --- Rainbow Logic ---
    hue_x6 = Signal(11)
    m.d.comb += hue_x6.eq(hue * 6)
    
    segment = Signal(3)
    m.d.comb += segment.eq(hue_x6 >> 8)
    
    seg_pos = Signal(8)
    m.d.comb += seg_pos.eq(hue_x6[:8])
    
    rising = seg_pos
    falling = Signal(8)
    m.d.comb += falling.eq(255 - seg_pos)
    
    rbw_r = Signal(8)
    rbw_g = Signal(8)
    rbw_b = Signal(8)
    
    with m.Switch(segment):
        with m.Case(0):
            m.d.comb += [rbw_r.eq(255), rbw_g.eq(rising), rbw_b.eq(0)]
        with m.Case(1):
            m.d.comb += [rbw_r.eq(falling), rbw_g.eq(255), rbw_b.eq(0)]
        with m.Case(2):
            m.d.comb += [rbw_r.eq(0), rbw_g.eq(255), rbw_b.eq(rising)]
        with m.Case(3):
            m.d.comb += [rbw_r.eq(0), rbw_g.eq(falling), rbw_b.eq(255)]
        with m.Case(4):
            m.d.comb += [rbw_r.eq(rising), rbw_g.eq(0), rbw_b.eq(255)]
        with m.Case(5):
            m.d.comb += [rbw_r.eq(255), rbw_g.eq(0), rbw_b.eq(falling)]
            
    # --- Trans Logic ---
    trans_r = Signal(8)
    trans_g = Signal(8)
    trans_b = Signal(8)
    
    with m.If(hue < 48):          # 3/16 blue
        m.d.comb += [
            trans_r.eq(0x00),
            trans_g.eq(0x40),
            trans_b.eq(0x80),
        ]
    with m.Elif(hue < 96):        # 3/16 pink
        m.d.comb += [
            trans_r.eq(0x80),
            trans_g.eq(0x00),
            trans_b.eq(0x40),
        ]
    with m.Elif(hue < 160):       # 4/16 white
        m.d.comb += [
            trans_r.eq(0xFF),
            trans_g.eq(0xFF),
            trans_b.eq(0xFF),
        ]
    with m.Elif(hue < 208):       # 3/16 pink
        m.d.comb += [
            trans_r.eq(0x80),
            trans_g.eq(0x00),
            trans_b.eq(0x40),
        ]
    with m.Else():                # 3/16 blue
        m.d.comb += [
            trans_r.eq(0x00),
            trans_g.eq(0x40),
            trans_b.eq(0x80),
        ]
            
    # --- Output Mux ---
    with m.Switch(mode):
        with m.Case(1): # Pass-through literal RGB
            m.d.comb += [rgb_r.eq(raw_r), rgb_g.eq(raw_g), rgb_b.eq(raw_b)]
        with m.Case(2): # Rainbow 
            m.d.comb += [rgb_r.eq(rbw_r), rgb_g.eq(rbw_g), rgb_b.eq(rbw_b)]
        with m.Case(3): # Trans flag
            m.d.comb += [rgb_r.eq(trans_r), rgb_g.eq(trans_g), rgb_b.eq(trans_b)]
        with m.Default(): # Off (Black)
            m.d.comb += [rgb_r.eq(0), rgb_g.eq(0), rgb_b.eq(0)]
            
    ports = [hue, mode, raw_r, raw_g, raw_b, rgb_r, rgb_g, rgb_b]
    return m, ports

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/color_mapper.py path/to/output.v")
        sys.exit(1)
        
    out = sys.argv[1]
    m, ports = make_color_mapper()
    v = verilog.convert(m, name="color_mapper", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)

if __name__ == "__main__":
    main()