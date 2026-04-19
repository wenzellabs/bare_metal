#!/usr/bin/env python3
"""Nickname display module.

This module reads nickname data from flash memory and displays it statically
on the 8x16 LED display.

Nickname format in flash (starting at 0x0fec00):
    [MAGIC:8]         'N' (0x4E)
    [LENGTH:24]       Total nickname data size in bytes (big-endian)
    [COUNT:16]        Number of nicknames (big-endian)
    [DATA...]         Nicknames:
                        [NAME_LEN:8]  Length of nickname (1-32)
                        [NAME:...]    ASCII characters
                        [COLOR_R:8]   Red component (0-255)
                        [COLOR_G:8]   Green component (0-255)
                        [COLOR_B:8]   Blue component (0-255)

Display behavior:
    - Reads all nicknames from flash
    - Displays each nickname statically for ~2 seconds
    - Cycles through nicknames sequentially
    - Truncates nicknames to MAX_DISPLAY_CHARS
"""

# Display configuration
MAX_DISPLAY_CHARS = 6  # Maximum characters to display (adjust for larger displays)

import sys
from amaranth import Module, Signal, Mux
from amaranth.back import verilog
from sk9822 import SK9822Writer


def make_nick(width=8, height=16):
    """Create nickname display module.
    
    Args:
        width: Display width in pixels (default 8)
        height: Display height in pixels (default 16)
    
    Returns:
        (module, ports) tuple
    """
    m = Module()
    
    # Create writer for LED updates
    writer = SK9822Writer(width, height, name_prefix="nick_")
    
    # Control signals
    enable = Signal(name="enable")
    short_press = Signal(name="short_press")  # Button press to advance to next nick
    
    # Internal flash control (driven by FSM)
    fsm_flash_read_en = Signal(name="fsm_flash_read_en")
    fsm_flash_read_addr = Signal(24, name="fsm_flash_read_addr")
    
    # Flash controller interface (for nickname data) - OUTPUTS to flash controller
    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")
    
    # Font renderer interface
    font_char_code = Signal(8, name="font_char_code")
    font_render_enable = Signal(name="font_render_enable")
    font_render_done = Signal(name="font_render_done")
    font_busy = Signal(name="font_busy")
    font_segment_pattern = Signal(16, name="font_segment_pattern")
    
    # Font renderer flash access (output from nick's internal mux)
    font_flash_read_en = Signal(name="font_flash_read_en")
    font_flash_read_addr = Signal(24, name="font_flash_read_addr")
    font_flash_read_valid = Signal(name="font_flash_read_valid")
    font_flash_busy = Signal(name="font_flash_busy")
    font_flash_ready = Signal(name="font_flash_ready")
    
    # Flash address for nickname data
    ADDR_NICK_START = 0x0a0000
    
    # Header data
    nick_valid = Signal(name="nick_valid")         # 'N' magic found
    nick_count = Signal(16, name="nick_count")     # Number of nicknames
    
    # Current nickname being displayed
    current_nick = Signal(16, name="current_nick") # Index of current nickname
    nick_len = Signal(8, name="nick_len")          # Length of current nickname
    nick_color_r = Signal(8, reset=0, name="nick_color_r")    # Red component (will be loaded from flash)
    nick_color_g = Signal(8, reset=0, name="nick_color_g")    # Green component (will be loaded from flash)
    nick_color_b = Signal(8, reset=0, name="nick_color_b")    # Blue component (will be loaded from flash)
    color_loaded = Signal(reset=0, name="color_loaded")     # Flag: colors have been read from flash
    
    # Address tracking for multi-nick support
    next_nick_addr = Signal(24, name="next_nick_addr")  # Flash address of next nickname to read
    
    # Display timing - switch nicks every ~2 seconds
    display_timer = Signal(26, name="display_timer")  # Timer for nick display duration
    DISPLAY_TIME = 2**25  # ~2.097 seconds at 16MHz (33,554,432 cycles)
    
    # Character buffer for current nickname (max 32 chars)
    char_lookup_addr = Signal(5, name="char_lookup_addr")  # Separate signal for comb reads
    
    # Write port signals - directly driven by comb logic so writes happen
    # on the same posedge that data arrives (no 1-cycle delay)
    char_wr_addr_comb = Signal(5, name="char_wr_addr_comb")
    char_wr_data_comb = Signal(8, name="char_wr_data_comb")
    char_wr_en_comb = Signal(name="char_wr_en_comb")
    
    # Counter for write address (registered, tracks how many chars stored)
    char_store_count = Signal(5, name="char_store_count")
    
    # Simple RAM for character storage
    from amaranth.lib.memory import Memory
    char_buffer = Memory(shape=8, depth=32, init=[])
    m.submodules.char_buffer = char_buffer
    char_wr_port = char_buffer.write_port()
    char_rd_port = char_buffer.read_port(domain="sync", transparent_for=())
    
    m.d.comb += [
        char_wr_port.addr.eq(char_wr_addr_comb),
        char_wr_port.data.eq(char_wr_data_comb),
        char_wr_port.en.eq(char_wr_en_comb),
        char_rd_port.addr.eq(char_lookup_addr),
    ]
    
    # Read result from character buffer
    char_read = Signal(8, name="char_read")
    m.d.comb += char_read.eq(char_rd_port.data)
    
    # State machine for nickname display
    # States: IDLE, READ_HEADER, READ_COUNT, FIND_NICK, READ_NICK_LEN, READ_NICK_DATA, 
    #         READ_COLOR, DISPLAY, SCROLL_WAIT
    header_byte = Signal(3, name="header_byte")
    read_count = Signal(8, name="read_count")
    skip_count = Signal(16, name="skip_count")
    color_component = Signal(2, name="color_component")  # 0=R, 1=G, 2=B
    
    # Display rendering signals
    disp_x = Signal(4, name="disp_x")
    disp_y = Signal(5, name="disp_y")
    char_idx = Signal(5, name="char_idx")
    
    # Debug: latch low nibble of 1st nick character's ASCII code from flash
    debug_font_nibble = Signal(4, name="debug_font_nibble")
    
    with m.FSM(name="nick_fsm"):
        # IDLE: Wait for enable, read header if needed, then render
        with m.State("IDLE"):
            with m.If(enable & ~color_loaded & flash_ready):
                # First time or after reset - read header to get colors
                m.d.sync += [
                    fsm_flash_read_addr.eq(ADDR_NICK_START),
                    fsm_flash_read_en.eq(1),
                    header_byte.eq(0),
                ]
                m.next = "READ_HEADER"
            
            with m.Elif(enable & color_loaded):
                # Colors already loaded, go directly to rendering
                m.d.sync += [
                    char_idx.eq(0),
                    disp_x.eq(0),
                    disp_y.eq(0),
                    char_lookup_addr.eq(0),
                ]
                m.next = "RENDER_INIT"
            
            with m.Else():
                # When disabled, ensure flash is released and display state is reset
                # NOTE: DO NOT reset color_loaded or colors - keep them persistent!
                m.d.sync += [
                    writer.clear(),
                    disp_x.eq(0),
                    disp_y.eq(0),
                    fsm_flash_read_en.eq(0),  # Ensure flash is released
                    # nick_valid.eq(0),   # REMOVED - don't reset, keep colors
                    # color_loaded.eq(0), # REMOVED - keep colors loaded
                ]
        
        # READ_HEADER: Read 5-byte header (magic + length + count)
        with m.State("READ_HEADER"):
            with m.If(~enable):
                m.d.sync += fsm_flash_read_en.eq(0)
                m.next = "IDLE"
            
            m.d.sync += writer.clear()
            
            # Deassert read_en once flash goes busy
            with m.If(flash_busy):
                m.d.sync += fsm_flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                with m.If(header_byte == 0):
                    # Check magic byte 'N'
                    with m.If(flash_read_data == ord('N')):
                        m.d.sync += [
                            header_byte.eq(1),
                            fsm_flash_read_addr.eq(flash_read_addr + 1),
                            fsm_flash_read_en.eq(1),  # Start next read immediately
                        ]
                    with m.Else():
                        # Invalid magic, go back to IDLE
                        m.next = "IDLE"
                
                with m.Elif((header_byte >= 1) & (header_byte <= 3)):
                    # Skip length bytes (we don't need them)
                    m.d.sync += [
                        header_byte.eq(header_byte + 1),
                        fsm_flash_read_addr.eq(flash_read_addr + 1),
                        fsm_flash_read_en.eq(1),  # Start next read immediately
                    ]
                
                with m.Elif(header_byte == 4):
                    # First byte of count (high byte)
                    m.d.sync += [
                        nick_count[8:16].eq(flash_read_data),
                        header_byte.eq(5),
                        fsm_flash_read_addr.eq(flash_read_addr + 1),
                        fsm_flash_read_en.eq(1),  # Start next read immediately
                    ]
                
                with m.Else():  # header_byte == 5
                    # Second byte of count (low byte)
                    m.d.sync += [
                        nick_count[0:8].eq(flash_read_data),
                        nick_valid.eq(1),
                        current_nick.eq(0),
                        next_nick_addr.eq(ADDR_NICK_START + 6),  # First nickname starts after header
                    ]
                    m.next = "FIND_NICK"
        
        # FIND_NICK: Navigate to the nickname we want to display
        with m.State("FIND_NICK"):
            with m.If(~enable):
                m.next = "IDLE"
            
            m.d.sync += writer.clear()
            
            # Check if we've cycled through all nicknames
            with m.If((current_nick >= nick_count) | (nick_count == 0)):
                # Wrap back to first nickname
                m.d.sync += [
                    current_nick.eq(0),
                    next_nick_addr.eq(ADDR_NICK_START + 6),  # First nickname after header
                    fsm_flash_read_addr.eq(ADDR_NICK_START + 6),  # Use constant directly
                    fsm_flash_read_en.eq(1),
                ]
            with m.Else():
                # Read the nickname at next_nick_addr
                m.d.sync += [
                    fsm_flash_read_addr.eq(next_nick_addr),
                    fsm_flash_read_en.eq(1),
                ]
            m.next = "READ_NICK_LEN"
        
        # READ_NICK_LEN: Read the length of the nickname
        with m.State("READ_NICK_LEN"):
            with m.If(~enable):
                m.d.sync += fsm_flash_read_en.eq(0)
                m.next = "IDLE"
            
            m.d.sync += writer.clear()
            
            # Deassert read_en once flash goes busy
            with m.If(flash_busy):
                m.d.sync += fsm_flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                m.d.sync += [
                    nick_len.eq(flash_read_data),
                    read_count.eq(0),
                    char_store_count.eq(0),
                    fsm_flash_read_addr.eq(flash_read_addr + 1),
                    fsm_flash_read_en.eq(1),  # Start next read immediately
                ]
                m.next = "READ_NICK_DATA"
        
        # READ_NICK_DATA: Read nickname characters into buffer
        with m.State("READ_NICK_DATA"):
            with m.If(~enable):
                m.d.sync += [
                    fsm_flash_read_en.eq(0),
                ]
                m.next = "IDLE"
            
            m.d.sync += writer.clear()
            
            # Deassert read_en once flash goes busy
            with m.If(flash_busy):
                m.d.sync += fsm_flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                # Store character in buffer (up to MAX_DISPLAY_CHARS) - COMBINATIONAL write so it
                # happens on THIS posedge (no 1-cycle delay)
                with m.If(char_store_count < MAX_DISPLAY_CHARS):
                    m.d.comb += [
                        char_wr_en_comb.eq(1),
                        char_wr_addr_comb.eq(char_store_count),
                        char_wr_data_comb.eq(flash_read_data),
                    ]
                    m.d.sync += char_store_count.eq(char_store_count + 1)
                
                m.d.sync += [
                    read_count.eq(read_count + 1),
                    fsm_flash_read_addr.eq(flash_read_addr + 1),
                ]
                
                # Check if this was the last character
                with m.If(read_count == nick_len - 1):
                    # All characters read, move to color reading
                    m.d.sync += [
                        color_component.eq(0),
                        fsm_flash_read_en.eq(1),  # Start color read immediately
                    ]
                    m.next = "READ_COLOR"
                with m.Else():
                    # More characters to read
                    m.d.sync += fsm_flash_read_en.eq(1)  # Start next read immediately
        
        # READ_COLOR: Read RGB color bytes
        with m.State("READ_COLOR"):
            with m.If(~enable):
                m.d.sync += [
                    fsm_flash_read_en.eq(0),
                ]
                m.next = "IDLE"
            
            m.d.sync += [
                writer.clear(),
            ]
            
            # Deassert read_en once flash goes busy
            with m.If(flash_busy):
                m.d.sync += fsm_flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                with m.If(color_component == 0):
                    m.d.sync += [
                        nick_color_r.eq(flash_read_data),
                        color_component.eq(1),
                        fsm_flash_read_addr.eq(flash_read_addr + 1),
                        fsm_flash_read_en.eq(1),  # Start next read immediately
                    ]
                with m.Elif(color_component == 1):
                    m.d.sync += [
                        nick_color_g.eq(flash_read_data),
                        color_component.eq(2),
                        fsm_flash_read_addr.eq(flash_read_addr + 1),
                        fsm_flash_read_en.eq(1),  # Start next read immediately
                    ]
                with m.Else():  # color_component == 2
                    m.d.sync += [
                        nick_color_b.eq(flash_read_data),
                        color_loaded.eq(1),  # Mark colors as loaded
                        display_timer.eq(0),  # Start display timer
                        char_idx.eq(0),
                        # Update next_nick_addr to point to next nickname (current addr + 1)
                        next_nick_addr.eq(flash_read_addr + 1),
                        # Update nick_len to reflect actual displayed chars (min of nick_len and MAX_DISPLAY_CHARS)
                    ]
                    # Clamp displayed length to MAX_DISPLAY_CHARS
                    with m.If(nick_len > MAX_DISPLAY_CHARS):
                        m.d.sync += nick_len.eq(MAX_DISPLAY_CHARS)
                    m.next = "RENDER_INIT"
        
        # RENDER_INIT: Initialize rendering state
        with m.State("RENDER_INIT"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Reset ALL rendering state when entering mode
                # This ensures clean slate regardless of previous mode state
                m.d.sync += [
                    # Position and indexing
                    char_idx.eq(0),
                    disp_x.eq(0),
                    disp_y.eq(0),
                    char_lookup_addr.eq(0),
                    # Font rendering interface
                    font_render_enable.eq(0),
                    font_char_code.eq(0),
                ]
                m.next = "CLEAR_DISPLAY"
        
        # CLEAR_DISPLAY: Write black to all LEDs to clear leftover data from other modes
        with m.State("CLEAR_DISPLAY"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Write black pixel at current position
                m.d.sync += writer.set_led(x=disp_x, y=disp_y, r=0, g=0, b=0)
                
                # Move to next position
                with m.If(disp_y == height - 1):
                    # End of column, move to next column
                    with m.If(disp_x == width - 1):
                        # All LEDs cleared, start rendering
                        m.d.sync += [
                            disp_x.eq(0),
                            disp_y.eq(0),
                            char_idx.eq(0),
                        ]
                        m.next = "FETCH_CHAR"
                    with m.Else():
                        m.d.sync += [
                            disp_x.eq(disp_x + 1),
                            disp_y.eq(0),
                        ]
                with m.Else():
                    m.d.sync += disp_y.eq(disp_y + 1)
        
        # FETCH_CHAR: Read character from buffer and request font pattern
        with m.State("FETCH_CHAR"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Check if we've rendered all characters
                with m.If(char_idx >= nick_len):
                    # All characters rendered, go to display
                    m.d.sync += [
                        disp_x.eq(0),
                        disp_y.eq(0),
                    ]
                    m.next = "DISPLAY"
                with m.Else():
                    # Set up character buffer read address
                    m.d.sync += char_lookup_addr.eq(char_idx)
                    m.next = "WAIT_CHAR"
        
        # WAIT_CHAR: Wait one cycle for sync memory read to produce data
        with m.State("WAIT_CHAR"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # char_read is now valid (1 cycle after addr was set)
                m.next = "RENDER_FONT"
        
        # RENDER_FONT: Request font pattern from font_render module
        with m.State("RENDER_FONT"):
            with m.If(~enable):
                m.d.sync += font_render_enable.eq(0)
                m.next = "IDLE"
            with m.Else():
                # Start font lookup on first cycle
                with m.If(~font_render_enable):
                    m.d.sync += [
                        font_char_code.eq(char_read),
                        font_render_enable.eq(1),
                        disp_y.eq(0),
                    ]
                
                # Wait for font_render to complete
                with m.If(font_render_done):
                    m.d.sync += [
                        font_render_enable.eq(0),
                        disp_y.eq(0),
                    ]
                    # Debug: latch segment pattern nibble for 1st char
                    with m.If(char_idx == 0):
                        m.d.sync += debug_font_nibble.eq(font_segment_pattern[8:12])
                    m.next = "RENDER_SEGMENTS"
        
        # RENDER_SEGMENTS: Write 16 LEDs based on segment pattern
        with m.State("RENDER_SEGMENTS"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Each character occupies one x position (digit)
                # 16 y positions correspond to 16 segments
                segment_bit = Signal(name="segment_bit")
                m.d.comb += segment_bit.eq(font_segment_pattern.bit_select(disp_y, 1))
                
                # Set LED based on segment bit
                with m.If(segment_bit):
                    m.d.sync += writer.set_led(
                        x=char_idx,
                        y=disp_y,
                        r=nick_color_r,
                        g=nick_color_g,
                        b=nick_color_b
                    )
                with m.Else():
                    m.d.sync += writer.set_led(x=char_idx, y=disp_y, r=0, g=0, b=0)
                
                # Move to next segment
                with m.If(disp_y == height - 1):
                    # All segments written for this character
                    m.next = "NEXT_CHAR"
                with m.Else():
                    m.d.sync += disp_y.eq(disp_y + 1)
        
        # NEXT_CHAR: Move to next character
        with m.State("NEXT_CHAR"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += char_idx.eq(char_idx + 1)
                m.next = "FETCH_CHAR"
        
        # DISPLAY: Show rendered nickname for ~2 seconds, then cycle to next
        with m.State("DISPLAY"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Increment display timer
                m.d.sync += display_timer.eq(display_timer + 1)
                
                # Check if it's time to switch to next nickname
                with m.If((display_timer >= DISPLAY_TIME) | short_press):
                    m.d.sync += [
                        display_timer.eq(0),
                        current_nick.eq(current_nick + 1),
                    ]
                    m.next = "FIND_NICK"
    
    # Flash multiplexing between nick's FSM and font_render:
    # - When font_flash_read_en is asserted, font_render controls flash
    # - Otherwise, nick's FSM controls flash
    # - font_flash_read_valid/busy/ready come from flash controller back to font_render
    
    # Forward flash status to font_render (it always sees these)
    m.d.comb += [
        font_flash_read_valid.eq(flash_read_valid),
        font_flash_busy.eq(flash_busy),
        font_flash_ready.eq(flash_ready),
    ]
    
    # Multiplex flash control: font_render takes priority when it asserts read_en
    from amaranth.hdl import Mux
    m.d.comb += [
        flash_read_en.eq(Mux(font_flash_read_en, font_flash_read_en, fsm_flash_read_en)),
        flash_read_addr.eq(Mux(font_flash_read_en, font_flash_read_addr, fsm_flash_read_addr)),
    ]
    
    # Port list for Verilog generation
    ports = [
        enable,
        short_press,
        flash_read_en, flash_read_addr, flash_read_data, flash_read_valid, flash_busy, flash_ready,
        font_char_code, font_render_enable, font_render_done, font_busy, font_segment_pattern,
        font_flash_read_en, font_flash_read_addr, font_flash_read_valid, font_flash_busy, font_flash_ready,
        debug_font_nibble,
    ] + writer.signals
    
    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/nick.py path/to/output.v")
        sys.exit(1)
    
    out = sys.argv[1]
    m, ports = make_nick(width=8, height=16)
    
    v = verilog.convert(m, name="nick_module", ports=ports)
    
    with open(out, "w") as f:
        f.write(v)
    
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
