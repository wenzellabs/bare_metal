"""SPI Flash Controller for AT25SF081.

This module provides read and write access to the external SPI flash memory.
It implements the standard SPI protocol for flash commands.

Commands supported:
- 0x03: Read Data
- 0x0b: Fast Read (with dummy byte)
- 0x06: Write Enable
- 0x20: Sector Erase (4 KB)
- 0x02: Page Program (up to 256 bytes)
- 0x05: Read Status Register

Interface:
    Inputs:
        - read_en: Pulse to start read operation
        - read_addr[23:0]: Address to read from
        - write_en: Pulse to start write operation
        - write_addr[23:0]: Address to write to
        - write_data[7:0]: Data to write
        - erase_en: Pulse to erase 4KB sector
        - erase_addr[23:0]: Sector address (4KB aligned)
    
    Outputs:
        - read_data[7:0]: Data read from flash
        - read_valid: Pulse when read_data is valid
        - busy: Controller is performing an operation
        - flash_cs: Chip select (active low)
        - flash_clk: SPI clock
        - flash_mosi: Master out, slave in
    
    Bidirectional:
        - flash_miso: Master in, slave out (input only in this design)
"""

from amaranth import Module, Signal, ClockDomain
from amaranth.build import Platform


def make_flash_controller(sys_clk_freq=16_000_000, spi_clk_freq=2_000_000):
    """Create SPI flash controller module with multi-client support.
    
    Args:
        sys_clk_freq: System clock frequency in Hz (default 16 MHz)
        spi_clk_freq: SPI clock frequency in Hz (default 2 MHz)
    
    Returns:
        (module, ports) tuple
    """
    m = Module()
    
    # Calculate SPI clock divider
    clk_div_val = sys_clk_freq // (2 * spi_clk_freq)
    clk_div = Signal(range(clk_div_val + 1), name="clk_div")
    
    # Multi-client interface (4 clients: nick=0, image=1, video=2, game=3)
    client_active = Signal(4, name="client_active")  # One-hot selection
    
    # Per-client signals
    nick_flash_read_en = Signal(name="nick_flash_read_en")
    nick_flash_read_addr = Signal(24, name="nick_flash_read_addr")
    nick_flash_read_data = Signal(8, name="nick_flash_read_data")
    nick_flash_read_valid = Signal(name="nick_flash_read_valid")
    nick_flash_busy = Signal(name="nick_flash_busy")
    nick_flash_ready = Signal(name="nick_flash_ready")
    
    image_flash_read_en = Signal(name="image_flash_read_en")
    image_flash_read_addr = Signal(24, name="image_flash_read_addr")
    image_flash_read_data = Signal(8, name="image_flash_read_data")
    image_flash_read_valid = Signal(name="image_flash_read_valid")
    image_flash_busy = Signal(name="image_flash_busy")
    image_flash_ready = Signal(name="image_flash_ready")
    
    # Internal muxed signals (feed into flash FSM)
    read_en = Signal(name="read_en")
    read_addr = Signal(24, name="read_addr")
    read_data = Signal(8, name="read_data")
    read_valid = Signal(name="read_valid")
    
    # Client multiplexer
    with m.Switch(client_active):
        with m.Case(0b0001):  # Nick (client 0)
            m.d.comb += [
                read_en.eq(nick_flash_read_en),
                read_addr.eq(nick_flash_read_addr),
                nick_flash_read_data.eq(read_data),
                nick_flash_read_valid.eq(read_valid),
            ]
        with m.Case(0b0010):  # Image (client 1)
            m.d.comb += [
                read_en.eq(image_flash_read_en),
                read_addr.eq(image_flash_read_addr),
                image_flash_read_data.eq(read_data),
                image_flash_read_valid.eq(read_valid),
            ]
        with m.Default():  # Default to image
            m.d.comb += [
                read_en.eq(image_flash_read_en),
                read_addr.eq(image_flash_read_addr),
                image_flash_read_data.eq(read_data),
                image_flash_read_valid.eq(read_valid),
            ]
    
    # Legacy write/erase interface (single client for now)
    write_en = Signal(name="write_en")
    write_addr = Signal(24, name="write_addr")
    write_data = Signal(8, name="write_data")
    write_done = Signal(name="write_done")
    
    erase_en = Signal(name="erase_en")
    erase_addr = Signal(24, name="erase_addr")
    erase_done = Signal(name="erase_done")
    
    busy = Signal(name="busy")
    
    # Broadcast busy and ready to all clients
    m.d.comb += [
        nick_flash_busy.eq(busy),
        image_flash_busy.eq(busy),
    ]
    
    # SPI pins
    flash_cs = Signal(reset=1, name="flash_cs")    # Active low, default high
    flash_clk = Signal(name="flash_clk")
    flash_mosi = Signal(name="flash_mosi")
    flash_miso = Signal(name="flash_miso")  # Input from flash
    
    # Internal signals
    spi_clk_edge = Signal(name="spi_clk_edge")  # Pulse on SPI clock edge
    bit_counter = Signal(6, name="bit_counter")  # Up to 40 bits (cmd + addr + data)
    shift_reg = Signal(32, name="shift_reg")     # Shift register for TX/RX
    byte_data = Signal(8, name="byte_data")      # Received byte
    init_counter = Signal(20, reset=0, name="init_counter")  # Power-on delay counter
    flash_ready = Signal(reset=0, name="flash_ready")  # Flash has been woken up
    
    # Broadcast flash_ready to all clients
    m.d.comb += [
        nick_flash_ready.eq(flash_ready),
        image_flash_ready.eq(flash_ready),
    ]
    
    # Generate SPI clock - just toggle every cycle when busy
    # Output on clock=1, sample on clock=0 (like picorv32 spimemio)
    with m.If(busy):
        m.d.sync += flash_clk.eq(~flash_clk)
    with m.Else():
        m.d.sync += flash_clk.eq(0)
    
    # State machine
    with m.FSM(name="flash_fsm", reset="INIT"):
        # INIT: Wait then send wake-up command
        with m.State("INIT"):
            m.d.sync += [
                busy.eq(0),
                flash_cs.eq(1),
                read_valid.eq(0),
                init_counter.eq(init_counter + 1),
            ]
            
            # Wait for power-on, then send 0xAB wake
            with m.If(init_counter[16]):
                m.d.sync += [
                    busy.eq(1),
                    flash_cs.eq(0),
                    shift_reg.eq((0xAB << 24) << 1),  # Shift left so first bit ready
                    flash_mosi.eq((0xAB >> 7) & 1),  # Set first bit (MSB of 0xAB = 1)
                    bit_counter.eq(8),
                ]
                m.next = "WAKE_CMD"
        
        # WAKE_CMD: Send 0xAB command (8 bits)
        with m.State("WAKE_CMD"):
            with m.If(flash_clk):
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
            
            # After 8 bits, release CS and wait
            with m.If((bit_counter == 1) & flash_clk):
                m.d.sync += [
                    flash_cs.eq(1),
                    busy.eq(0),
                    init_counter.eq(0),
                ]
                m.next = "WAKE_WAIT"
        
        # WAKE_WAIT: Wait for tRES1 (3us min, we wait 16us)
        with m.State("WAKE_WAIT"):
            m.d.sync += init_counter.eq(init_counter + 1)
            with m.If(init_counter[8]):  # 256 cycles = 16us
                m.d.sync += flash_ready.eq(1)
                m.next = "IDLE"
        
        # IDLE: Wait for command
        with m.State("IDLE"):
            # Clear busy flag and status signals
            m.d.sync += [
                flash_cs.eq(1),
                read_valid.eq(0),
                write_done.eq(0),
                erase_done.eq(0),
            ]
            
            with m.If(read_en & flash_ready):
                m.d.sync += [
                    busy.eq(1),
                    flash_cs.eq(0),
                    shift_reg.eq(((0x0B << 24) | read_addr) << 1),  # Shift left so first bit is ready
                    flash_mosi.eq((0x0B >> 7) & 1),  # Set first bit (MSB of 0x0B = 0)
                    bit_counter.eq(32),  # 8 bits cmd + 24 bits address
                ]
                m.next = "READ_CMD"
            
            with m.Elif(write_en & flash_ready):
                # First send write enable command
                m.d.sync += [
                    busy.eq(1),
                    flash_cs.eq(0),
                    shift_reg.eq(0x06 << 24),  # CMD_WRITE_ENABLE
                    bit_counter.eq(8),
                ]
                m.next = "WRITE_ENABLE"
            
            with m.Elif(erase_en):
                # First send write enable command
                m.d.sync += [
                    busy.eq(1),
                    flash_cs.eq(0),
                    shift_reg.eq(0x06 << 24),  # CMD_WRITE_ENABLE
                    bit_counter.eq(8),
                ]
                m.next = "ERASE_ENABLE"
        
        # READ_CMD: Send read command and address (32 bits total)
        with m.State("READ_CMD"):
            # When clock is high, shift out next bit (after rising edge clocked previous bit)
            with m.If(flash_clk):
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
            
            # Check for completion (after decrement on NEXT cycle)
            with m.If((bit_counter == 1) & flash_clk):
                m.d.sync += bit_counter.eq(8)
                m.next = "READ_DUMMY"
        
        # READ_DUMMY: Send dummy byte for Fast Read (0x0B requires this)
        with m.State("READ_DUMMY"):
            # Clock out 8 dummy bits (don't care about MOSI value)
            with m.If(flash_clk):
                m.d.sync += bit_counter.eq(bit_counter - 1)
            
            # After 8 dummy clocks, start reading data
            with m.If((bit_counter == 1) & flash_clk):
                m.d.sync += bit_counter.eq(8)
                m.next = "READ_DATA"
        
        # READ_DATA: Receive data byte (8 bits)
        # SPI Mode 0: flash outputs data on falling edge of SCK,
        # we sample on the NEXT rising edge.  Since flash_clk toggles
        # every system clock, sample when flash_clk is HIGH (one cycle
        # after the falling edge gives the flash time to drive MISO).
        with m.State("READ_DATA"):
            # Sample when clock is HIGH (rising edge has passed)
            with m.If(flash_clk):
                m.d.sync += [
                    shift_reg.eq((shift_reg << 1) | flash_miso),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                # Check if we just sampled the last bit
                with m.If(bit_counter == 1):
                    m.d.sync += [
                        read_data.eq((shift_reg << 1) | flash_miso),  # Include this bit
                        read_valid.eq(1),
                        flash_cs.eq(1),
                        busy.eq(0),
                    ]
                    m.next = "IDLE"
        
        # WRITE_ENABLE: Send write enable command
        with m.State("WRITE_ENABLE"):
            with m.If(spi_clk_edge & flash_clk):  # Shift on falling edge
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                with m.If(bit_counter == 1):
                    m.d.sync += flash_cs.eq(1)
                    m.next = "WRITE_ENABLE_WAIT"
        
        # WRITE_ENABLE_WAIT: De-assert CS before next command
        with m.State("WRITE_ENABLE_WAIT"):
            m.d.sync += [
                flash_cs.eq(0),
                shift_reg.eq((0x02 << 24) | write_addr),  # CMD_PAGE_PROGRAM + address
                bit_counter.eq(32),
            ]
            m.next = "WRITE_CMD"
        
        # WRITE_CMD: Send page program command and address
        with m.State("WRITE_CMD"):
            with m.If(spi_clk_edge & flash_clk):  # Shift on falling edge
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                with m.If(bit_counter == 1):
                    m.d.sync += [
                        shift_reg.eq(write_data << 24),
                        bit_counter.eq(8),
                    ]
                    m.next = "WRITE_DATA"
        
        # WRITE_DATA: Send data byte
        with m.State("WRITE_DATA"):
            with m.If(spi_clk_edge & flash_clk):  # Shift on falling edge
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                with m.If(bit_counter == 1):
                    m.d.sync += [
                        flash_cs.eq(1),
                        write_done.eq(1),
                    ]
                    m.next = "IDLE"
        
        # ERASE_ENABLE: Send write enable command before erase
        with m.State("ERASE_ENABLE"):
            with m.If(spi_clk_edge & flash_clk):  # Shift on falling edge
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                with m.If(bit_counter == 1):
                    m.d.sync += flash_cs.eq(1)
                    m.next = "ERASE_WAIT"
        
        # ERASE_WAIT: De-assert CS before erase command
        with m.State("ERASE_WAIT"):
            m.d.sync += [
                flash_cs.eq(0),
                shift_reg.eq((0x20 << 24) | erase_addr),  # CMD_SECTOR_ERASE + address
                bit_counter.eq(32),
            ]
            m.next = "ERASE_CMD"
        
        # ERASE_CMD: Send sector erase command
        with m.State("ERASE_CMD"):
            with m.If(spi_clk_edge & flash_clk):  # Shift on falling edge
                m.d.sync += [
                    flash_mosi.eq(shift_reg[31]),
                    shift_reg.eq(shift_reg << 1),
                    bit_counter.eq(bit_counter - 1),
                ]
                
                with m.If(bit_counter == 1):
                    m.d.sync += [
                        flash_cs.eq(1),
                        erase_done.eq(1),
                    ]
                    m.next = "IDLE"
    
    # Port list for Verilog conversion
    ports = [
        # Multi-client interface
        client_active,
        # Nick client
        nick_flash_read_en, nick_flash_read_addr, nick_flash_read_data, nick_flash_read_valid,
        nick_flash_busy, nick_flash_ready,
        # Image client
        image_flash_read_en, image_flash_read_addr, image_flash_read_data, image_flash_read_valid,
        image_flash_busy, image_flash_ready,
        # Legacy write/erase
        write_en, write_addr, write_data, write_done,
        erase_en, erase_addr, erase_done,
        # SPI pins
        flash_cs, flash_clk, flash_mosi, flash_miso,
    ]
    
    return m, ports


# Main: Generate Verilog
if __name__ == "__main__":
    import sys
    from amaranth.back import verilog
    
    m, ports = make_flash_controller()
    v = verilog.convert(m, name="flash_controller", ports=ports)
    
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            f.write(v)
    else:
        print(v)
