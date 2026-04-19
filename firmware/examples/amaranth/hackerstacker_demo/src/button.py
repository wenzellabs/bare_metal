#!/usr/bin/env python3
"""Button input handler with short/long press detection.

Detects:
- short_press: Falling edge (button pressed)
- long_press: Held for 512ms (at 16MHz: 2^23 cycles = 524ms)

Note: long_press always has a preceding short_press (this is expected behavior).
The long_press signal pulses HIGH when the timer expires (not on release).
"""
import sys
from amaranth import Module, Signal
from amaranth.back import verilog


def make_button_handler():
    """Create button handler with debounce and long-press detection.
    
    Returns:
        (module, ports) tuple
        
    Ports:
        btn_in: Input from button (active low, needs pull-up)
        short_press: Pulses high for 1 cycle on button press
        long_press: Pulses high for 1 cycle after 512ms hold
    """
    m = Module()
    
    # Input/output signals
    btn_in = Signal(name="btn_in")           # Button input (active low)
    short_press = Signal(name="short_press") # Pulse on press
    long_press = Signal(name="long_press")   # Pulse after long hold
    
    # Synchronizer for async input (prevent metastability)
    btn_sync1 = Signal()
    btn_sync2 = Signal()
    m.d.sync += [
        btn_sync1.eq(btn_in),
        btn_sync2.eq(btn_sync1),
    ]
    
    # Debounce: require stable for 2^16 clocks = ~4ms at 16MHz
    debounce_counter = Signal(16)
    btn_stable = Signal()
    btn_state = Signal(reset=1)  # Start high (pull-up, not pressed)
    
    # Debounce logic
    with m.If(btn_sync2 == btn_state):
        # Stable - reset counter
        m.d.sync += debounce_counter.eq(0)
    with m.Else():
        # Different - count up
        with m.If(debounce_counter == (2**16 - 1)):
            # Debounced - update state
            m.d.sync += [
                btn_state.eq(btn_sync2),
                debounce_counter.eq(0),
            ]
            m.d.comb += btn_stable.eq(1)
        with m.Else():
            m.d.sync += debounce_counter.eq(debounce_counter + 1)
    
    # Edge detection
    btn_prev = Signal()
    m.d.sync += btn_prev.eq(btn_state)
    
    falling_edge = Signal()
    rising_edge = Signal()
    m.d.comb += [
        falling_edge.eq(btn_prev & ~btn_state),  # 1 -> 0 (pressed)
        rising_edge.eq(~btn_prev & btn_state),   # 0 -> 1 (released)
    ]
    
    # Short press: detect falling edge
    m.d.sync += short_press.eq(falling_edge)
    
    # Long press timer: 2^23 cycles = 8,388,608 cycles = 524ms at 16MHz
    # (This is close to 500ms and divides evenly by 2)
    long_press_timer = Signal(23)
    long_press_armed = Signal()  # Button held long enough
    
    with m.If(falling_edge):
        # Button pressed - start timer
        m.d.sync += [
            long_press_timer.eq(0),
            long_press_armed.eq(0),
        ]
    with m.Elif(~btn_state):  # Button still held
        with m.If(long_press_timer == (2**23 - 1)):
            # Timer expired - arm long press
            m.d.sync += long_press_armed.eq(1)
        with m.Else():
            m.d.sync += long_press_timer.eq(long_press_timer + 1)
    with m.Elif(btn_state):  # Button released
        # Reset everything
        m.d.sync += [
            long_press_timer.eq(0),
            long_press_armed.eq(0),
        ]
    
    # Long press pulses when timer expires (not on release)
    m.d.sync += long_press.eq((long_press_timer == (2**23 - 1)) & ~long_press_armed)
    
    ports = [btn_in, short_press, long_press]
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/button.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    m, ports = make_button_handler()
    
    v = verilog.convert(m, name="button_handler", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
