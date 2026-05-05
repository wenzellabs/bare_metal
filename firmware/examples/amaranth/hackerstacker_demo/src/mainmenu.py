#!/usr/bin/env python3
"""Main menu state machine for mode switching.

Handles button inputs and coordinates between different display modules.
- Long press: cycles through modes (stacker -> nick -> image -> pattern -> rainbow)
- Short press: action within current mode (e.g. stacker button, pattern cycle)
"""
import sys
from amaranth import Module, Signal
from amaranth.back import verilog


def make_mainmenu(num_pattern_modes=19):
    """Create main menu state machine.
    
    Args:
        num_pattern_modes: Number of display modes in pattern module (default 4)
    
    Returns:
        (module, ports) tuple
    """
    m = Module()
    
    # Inputs from button handler
    short_press = Signal(name="short_press")
    long_press = Signal(name="long_press")
    
    # Outputs to control modules
    current_mode = Signal(3, reset=0, name="current_mode")  # 0=stacker, 1=nick, 2=image, 3=pattern, 4=rainbow
    stacker_enable = Signal(name="stacker_enable")     # Enable signal for stacker module
    nick_enable = Signal(name="nick_enable")           # Enable signal for nick module
    pattern_enable = Signal(name="pattern_enable")     # Enable signal for pattern module
    rainbow_enable = Signal(name="rainbow_enable")     # Enable signal for rainbow module
    image_enable = Signal(name="image_enable")         # Enable signal for image module
    pattern_display = Signal(5, name="clock_display")  # Which pattern (0-18)
    
    # State machine logic
    with m.If(long_press):
        # Cycle through modes: stacker(0) -> nick(1) -> image(2) -> pattern(3) -> rainbow(4)
        with m.If(current_mode == 4):
            m.d.sync += current_mode.eq(0)
        with m.Else():
            m.d.sync += current_mode.eq(current_mode + 1)
    
    with m.If(short_press):
        # Cycle through pattern display modes
        with m.If(pattern_display == (num_pattern_modes - 1)):
            m.d.sync += pattern_display.eq(0)
        with m.Else():
            m.d.sync += pattern_display.eq(pattern_display + 1)
    
    # Enable signals based on current mode
    m.d.comb += [
        stacker_enable.eq(current_mode == 0),
        nick_enable.eq(current_mode == 1),
        image_enable.eq(current_mode == 2),
        pattern_enable.eq(current_mode == 3),
        rainbow_enable.eq(current_mode == 4),
    ]
    
    # Export ports
    ports = [
        short_press, long_press,
        current_mode, stacker_enable, nick_enable, pattern_enable, rainbow_enable, image_enable, pattern_display
    ]
    
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/mainmenu.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    m, ports = make_mainmenu(num_pattern_modes=19)
    
    v = verilog.convert(m, name="mainmenu", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
