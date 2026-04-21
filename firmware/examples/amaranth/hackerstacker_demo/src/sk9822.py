#!/usr/bin/env python3
"""SK9822 RGB LED driver with RAM-based framebuffer.

Usage: python3 src/sk9822.py path/to/output.v

This generates a module that:
- Stores LED colors in block RAM (8x16 grid = 128 LEDs, 384 bytes)
- Autonomously refreshes the SK9822 strip from RAM
- Provides write interface for other modules to update colors
- Has a global brightness control

Interface:
- Write to framebuffer via wr_* signals (wr_en, wr_x, wr_y, wr_r, wr_g, wr_b)
- Set brightness via wr_brightness_* signals (wr_brightness_en, wr_brightness)
- Autonomous refresh: Continuously sends data to SK9822 strip

Helper class usage in your modules (pattern.py, game.py, etc.):
    from sk9822 import SK9822Writer
    
    writer = SK9822Writer(width=8, height=16)
    
    # To write a pixel:
    with m.If(condition):
        m.d.sync += writer.set_led(x=3, y=5, r=255, g=0, b=0)
    
    # To clear all:
    with m.If(clear_screen):
        m.d.sync += writer.set_led(x=x_counter, y=y_counter, r=0, g=0, b=0)
"""
import sys
from amaranth import Module, Signal, Mux
from amaranth.lib.memory import Memory
from amaranth.back import verilog


class SK9822Writer:
    """Helper class for writing to SK9822 framebuffer.
    
    This creates the write signals and provides convenient methods
    for your modules (pattern, game, nick, etc.) to write pixels.
    
    Usage in your module:
        writer = SK9822Writer(width=8, height=16)
        
        # In your elaborate function:
        with m.If(update_pixel):
            m.d.sync += writer.set_led(x=3, y=5, r=255, g=0, b=0)
    
    The writer.signals list contains all signals to wire to sk9822_controller.
    """
    
    def __init__(self, width=8, height=16, name_prefix=""):
        """Create write interface signals.
        
        Args:
            width: Grid width (default 8)
            height: Grid height (default 16)
            name_prefix: Optional prefix for signal names (e.g., "pattern_")
        """
        self.width = width
        self.height = height
        
        # Create the write signals
        self.wr_en = Signal(name=f"{name_prefix}wr_en")
        self.wr_x = Signal(range(width), name=f"{name_prefix}wr_x")
        self.wr_y = Signal(range(height), name=f"{name_prefix}wr_y")
        self.wr_r = Signal(8, name=f"{name_prefix}wr_r")
        self.wr_g = Signal(8, name=f"{name_prefix}wr_g")
        self.wr_b = Signal(8, name=f"{name_prefix}wr_b")
        
        # List of all signals for easy port connection
        self.signals = [
            self.wr_en, self.wr_x, self.wr_y,
            self.wr_r, self.wr_g, self.wr_b
        ]
    
    def set_led(self, x, y, r, g, b):
        """Return statements to write a pixel.
        
        This returns a list of signal assignments that you can use in:
            m.d.sync += writer.set_led(...)
            m.d.comb += writer.set_led(...)
        
        Args:
            x: X coordinate (0 to width-1) - can be Signal or int
            y: Y coordinate (0 to height-1) - can be Signal or int
            r: Red value (0-255) - can be Signal or int
            g: Green value (0-255) - can be Signal or int
            b: Blue value (0-255) - can be Signal or int
        
        Returns:
            List of signal assignments
        """
        return [
            self.wr_en.eq(1),
            self.wr_x.eq(x),
            self.wr_y.eq(y),
            self.wr_r.eq(r),
            self.wr_g.eq(g),
            self.wr_b.eq(b),
        ]
    
    def clear(self):
        """Return statements to disable writing.
        
        Use this when your module is not writing:
            m.d.sync += writer.clear()
        """
        return [self.wr_en.eq(0)]


def make_sk9822_controller(width=8, height=16, default_brightness=1):
    """Create SK9822 LED controller with RAM framebuffer.
    
    Runs at 2 MHz SPI clock for good EMI/signal integrity balance.
    - SPI clock: 2 MHz (16MHz system clock / 8)
    - Frame rate: ~238 fps for 128 LEDs (imperceptible to human eye)
    - SK9822 max: 30 MHz (15x safety margin)
    
    Args:
        width: Grid width (default 8)
        height: Grid height (default 16)
        default_brightness: Initial brightness 0-31 (default 1)
    
    Returns:
        (module, ports) tuple
    """
    m = Module()
    
    num_leds = width * height
    
    # External interface ports
    led_data = Signal(name="led_data")  # MOSI/data line
    led_clk = Signal(name="led_clk")    # SCLK/clock line
    
    # Write interface for setting LED colors
    wr_en = Signal(name="wr_en")        # Write enable
    wr_x = Signal(range(width), name="wr_x")      # X coordinate (0-7)
    wr_y = Signal(range(height), name="wr_y")     # Y coordinate (0-15)
    wr_r = Signal(8, name="wr_r")       # Red (0-255)
    wr_g = Signal(8, name="wr_g")       # Green (0-255)
    wr_b = Signal(8, name="wr_b")       # Blue (0-255)
    
    # Brightness control
    wr_brightness_en = Signal(name="wr_brightness_en")  # Brightness write enable
    wr_brightness = Signal(5, name="wr_brightness")     # New brightness (0-31)
    brightness = Signal(5, reset=default_brightness, name="brightness")

    # Extra dimming (right-shift of R/G/B) 0..7
    wr_extra_dim_en = Signal(name="wr_extra_dim_en")
    wr_extra_dim = Signal(3, name="wr_extra_dim")
    extra_dim = Signal(3, reset=0, name="extra_dim")

    # Update brightness and extra_dim registers
    with m.If(wr_brightness_en):
        m.d.sync += brightness.eq(wr_brightness)
    with m.If(wr_extra_dim_en):
        m.d.sync += extra_dim.eq(wr_extra_dim)
    
    # Framebuffer: 3 separate memories for R, G, B
    # Each memory is num_leds x 8 bits
    # Using separate memories allows parallel read of all 3 color channels
    mem_r = Memory(shape=8, depth=num_leds, init=[])
    mem_g = Memory(shape=8, depth=num_leds, init=[])
    mem_b = Memory(shape=8, depth=num_leds, init=[])
    m.submodules.mem_r = mem_r
    m.submodules.mem_g = mem_g
    m.submodules.mem_b = mem_b
    
    # Write port - synchronous write
    wr_port_r = mem_r.write_port()
    wr_port_g = mem_g.write_port()
    wr_port_b = mem_b.write_port()
    
    # Read port - synchronous read for refresh
    rd_port_r = mem_r.read_port(domain="sync", transparent_for=())
    rd_port_g = mem_g.read_port(domain="sync", transparent_for=())
    rd_port_b = mem_b.read_port(domain="sync", transparent_for=())
    
    # Calculate linear address from x, y
    # Physical LED chain on bare_metal board (16x8, 128 LEDs):
    #   LED0 = bottom-right, LED7 = top-right (column goes bottom-to-top)
    #   LED8 = one column left of LED0, LED127 = top-left
    #   led_index = (15 - physical_col) * 8 + physical_row
    #
    # Game modules use 8-wide x 16-tall logical grid.
    # Rotate 90° so game-y (0-15) maps to physical columns (right-to-left)
    # and game-x (0-7) maps to physical rows (bottom-to-top).
    wr_addr = Signal(range(num_leds))
    m.d.comb += wr_addr.eq(((height - 1 - wr_y) * width) + wr_x)
    
    # Connect write ports
    m.d.comb += [
        wr_port_r.addr.eq(wr_addr),
        wr_port_r.data.eq(wr_r),
        wr_port_r.en.eq(wr_en),
        
        wr_port_g.addr.eq(wr_addr),
        wr_port_g.data.eq(wr_g),
        wr_port_g.en.eq(wr_en),
        
        wr_port_b.addr.eq(wr_addr),
        wr_port_b.data.eq(wr_b),
        wr_port_b.en.eq(wr_en),
    ]
    
    # Clock divider for 2 MHz SPI (good EMI and signal integrity)
    # 16MHz system clock / 8 = 2 MHz SPI clock
    # Frame rate calculation for 128 LEDs:
    #   Bits per frame: 32 + (128 * 32) + 64 = 4192 bits
    #   System cycles: 4192 * 2 * 8 = 67,072 cycles
    #   Frame rate = 16MHz / 67,072 = ~238.5 fps
    #
    # Result: Instant visual updates, 15x safety margin below SK9822 limit
    clk_div = Signal(3)  # 3-bit counter for divide-by-8
    m.d.sync += clk_div.eq(clk_div + 1)
    
    # Frame state machine
    # Total bits per frame:
    # - Start frame: 32 bits of 0
    # - LED data: num_leds * 32 bits
    # - End frame: 64 bits of 1 (SK9822 needs extra clocks)
    
    bits_per_frame = 32 + (num_leds * 32) + 64
    bit_counter = Signal(range(bits_per_frame))
    
    # Current LED being sent (for read address)
    led_index = Signal(range(num_leds))
    
    # Current bit within 32-bit LED frame
    bit_in_led = Signal(5)
    
    # LED color values (read from RAM, 1 cycle latency)
    red = Signal(8)
    green = Signal(8)
    blue = Signal(8)
    
    # Connect read ports to current LED index
    m.d.comb += [
        rd_port_r.addr.eq(led_index),
        rd_port_g.addr.eq(led_index),
        rd_port_b.addr.eq(led_index),
    ]
    
    # Latch read data (compensate for 1-cycle read latency)
    m.d.sync += [
        red.eq(rd_port_r.data),
        green.eq(rd_port_g.data),
        blue.eq(rd_port_b.data),
    ]
    
    # Build 32-bit LED frame: [111][5-bit brightness][8-bit blue][8-bit green][8-bit red]
    # Ensure brightness never exceeds 5 (safety clamp) and apply extra_dim
    safe_brightness = Signal(5)
    m.d.comb += safe_brightness.eq(Mux(brightness > 5, 5, brightness))

    # Apply right-shift dimming controlled by extra_dim before packing
    red_sh = Signal(8)
    green_sh = Signal(8)
    blue_sh = Signal(8)
    m.d.comb += [
        red_sh.eq(red >> extra_dim),
        green_sh.eq(green >> extra_dim),
        blue_sh.eq(blue >> extra_dim),
    ]

    led_frame = Signal(32)
    m.d.comb += led_frame.eq(
        (0b111 << 29) |
        (safe_brightness << 24) |
        (blue_sh << 16) |
        (green_sh << 8) |
        red_sh
    )
    
    # SPI output logic
    # Compute which LED we're currently sending (needed for memory read address)
    bit_offset = Signal(range(bits_per_frame))
    m.d.comb += bit_offset.eq(bit_counter - 32)
    m.d.comb += led_index.eq(bit_offset >> 5)  # Which LED (divide by 32)
    m.d.comb += bit_in_led.eq(31 - (bit_offset & 0x1F))  # Which bit (MSB first)
    
    # Generate SPI clock and data when divider reaches 0
    with m.If(clk_div == 0):
        # Clock toggles each time divider wraps
        m.d.sync += led_clk.eq(~led_clk)
        
        # Update data on rising edge of our clock (when led_clk goes high)
        with m.If(~led_clk):
            # Determine what bit to send
            with m.If(bit_counter < 32):
                # Start frame: send 0
                m.d.sync += led_data.eq(0)
            with m.Elif(bit_counter < (32 + num_leds * 32)):
                # LED data - send bit from led_frame
                m.d.sync += led_data.eq((led_frame >> bit_in_led) & 1)
            with m.Else():
                # End frame: send 1
                m.d.sync += led_data.eq(1)
            
            # Increment bit counter
            with m.If(bit_counter == (bits_per_frame - 1)):
                m.d.sync += bit_counter.eq(0)
            with m.Else():
                m.d.sync += bit_counter.eq(bit_counter + 1)
    
    # Define ports for the module
    ports = [
        led_data, led_clk,
        wr_en, wr_x, wr_y, wr_r, wr_g, wr_b,
        wr_brightness_en, wr_brightness,
        wr_extra_dim_en, wr_extra_dim
    ]
    
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/sk9822.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    
    # Configure: 8x16 grid = 128 LEDs, brightness=1, 2MHz SPI clock (divide-by-8)
    # Result: ~238 fps frame rate for instant visual updates with good EMI characteristics
    m, ports = make_sk9822_controller(width=8, height=16, default_brightness=1)
    
    v = verilog.convert(m, name="sk9822_controller", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
