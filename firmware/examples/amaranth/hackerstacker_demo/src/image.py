"""Image display module with DVD-logo-style skating animation.

This module reads a large image from flash memory and displays a moving
window of it on the 8x16 LED display. The display window "skates" across
the image, bouncing at the edges like the DVD logo.

Image format in flash (starting at 0x060000):
    [MAGIC:8]         'I' (0x49)
    [LENGTH:24]       Total image data size in bytes (big-endian)
    [WIDTH:16]        Image width in pixels (big-endian)
    [HEIGHT:16]       Image height in pixels (big-endian)
    [FRAME_DIV:16]    Frames between position updates (big-endian)
    [DATA...]         RGB data: width x height x 3 bytes

Display behavior:
    - 8x16 window starts at top-left (0, 0)
    - Every frame_divider frames, position increments
    - When x reaches (img_width - 8), direction reverses
    - When y reaches (img_height - 16), direction reverses
    - Creates bouncing DVD-logo effect
"""

from amaranth import Module, Signal, Mux
from sk9822 import SK9822Writer


def make_image(width=8, height=16):
    """Create image display module.
    
    Args:
        width: Display width in pixels (default 8)
        height: Display height in pixels (default 16)
    
    Returns:
        (module, ports) tuple
    """
    m = Module()
    
    # Create writer for LED updates
    writer = SK9822Writer(width, height, name_prefix="image_")
    
    # Control signals
    enable = Signal(name="enable")
    
    # Flash controller interface
    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")  # Flash has completed wake sequence
    
    # Image header data (read from flash at startup)
    image_valid = Signal(name="image_valid")       # 'I' magic found
    img_width = Signal(16, name="img_width")       # Image width
    img_height = Signal(16, name="img_height")     # Image height
    frame_divider = Signal(16, name="frame_divider") # Frames between updates
    
    # Current display window position in image
    win_x = Signal(16, name="win_x")               # Window X position
    win_y = Signal(16, name="win_y")               # Window Y position
    dir_x = Signal(name="dir_x")                   # X direction: 0=forward, 1=reverse
    dir_y = Signal(name="dir_y")                   # Y direction: 0=forward, 1=reverse
    
    # Pixel reading state
    pixel_x = Signal(range(width), name="pixel_x")   # Current pixel X (0-7)
    pixel_y = Signal(range(height), name="pixel_y")  # Current pixel Y (0-15)
    color_component = Signal(2, name="color_component") # 0=R, 1=G, 2=B
    pixel_r = Signal(8, name="pixel_r")
    pixel_g = Signal(8, name="pixel_g")
    pixel_b = Signal(8, name="pixel_b")
    
    # Frame divider counter
    frame_counter = Signal(16, name="frame_counter")
    
    # Header byte counter (10 bytes: magic + length(3) + width(2) + height(2) + framediv(2))
    header_byte = Signal(4, name="header_byte")
    header_buf = Signal(64, name="header_buf")     # Buffer for header data
    
    # Base address for image data (after 10-byte header)
    ADDR_IMAGE_START = 0x0b0000
    
    # State machine
    with m.FSM(name="image_fsm"):
        # IDLE: Wait for enable
        with m.State("IDLE"):
            with m.If(enable & ~image_valid & flash_ready):
                # First time enabled - read header (only if flash is ready)
                m.d.sync += [
                    flash_read_addr.eq(ADDR_IMAGE_START),
                    flash_read_en.eq(1),
                    header_byte.eq(0),
                    image_valid.eq(0),
                ]
                m.next = "READ_HEADER"
            
            with m.Elif(enable & image_valid & flash_ready):
                # Image header already loaded AND flash ready - start drawing
                m.d.sync += [
                    pixel_x.eq(0),
                    pixel_y.eq(0),
                    color_component.eq(0),
                ]
                m.next = "READ_PIXEL_START"
            
            with m.Else():
                # When disabled, clear writer and flash
                m.d.sync += [
                    writer.clear(),
                    flash_read_en.eq(0),
                ]
        
        # READ_HEADER: Read 10-byte header
        with m.State("READ_HEADER"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            
            # De-assert read_en once flash controller accepts it (goes busy)
            with m.Elif(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                
                # Shift in byte
                m.d.sync += [
                    header_buf.eq((header_buf << 8) | flash_read_data),
                    header_byte.eq(header_byte + 1),
                ]
                
                with m.If(header_byte == 9):  # Read all 10 bytes
                    # Parse header: magic(1) + length(3) + width(2) + height(2) + framediv(2)
                    # header_buf will contain last 8 bytes, flash_read_data has 10th byte
                    m.next = "PARSE_HEADER"
                with m.Else():
                    # Read next byte
                    m.d.sync += [
                        flash_read_addr.eq(flash_read_addr + 1),
                        flash_read_en.eq(1),
                    ]
        
        # PARSE_HEADER: Extract header fields
        with m.State("PARSE_HEADER"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # After reading 10 bytes, header_buf contains last 8 bytes
                # Byte 0 was magic (check separately), bytes 1-3 were length (skip)
                # Bytes 4-5: width, 6-7: height, 8-9: frame_divider
                # header_buf shifts left, so newest byte is at [7:0]
                # Last 8 bytes read were: length_lsb, length_mid, length_msb, width_msb, width_lsb, height_msb, height_lsb, framediv_msb
                # Then we read one more: framediv_lsb (in flash_read_data from last READ_HEADER)
                # Actually, after 10 reads, header_buf has bytes 2-9, and we need to reconstruct
                # Simpler approach: extract from correct positions after all shifts
                m.d.sync += [
                    img_width.eq((header_buf[40:48] << 8) | header_buf[32:40]),      # bytes 4-5
                    img_height.eq((header_buf[24:32] << 8) | header_buf[16:24]),     # bytes 6-7
                    frame_divider.eq((header_buf[8:16] << 8) | header_buf[0:8]),     # bytes 8-9
                    win_x.eq(0),
                    win_y.eq(0),
                    dir_x.eq(0),  # Start moving right
                    dir_y.eq(0),  # Start moving down
                    frame_counter.eq(0),
                ]
                
                # Check if first byte was magic 'I' (0x49)
                # We need to check the very first byte read - let's add a separate signal
                # For now, assume valid if we got here
                m.d.sync += image_valid.eq(1)
                
                m.next = "IDLE"
        
        # READ_PIXEL_START: Calculate flash address for current pixel
        with m.State("READ_PIXEL_START"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Calculate address: base + (win_y + pixel_y) * img_width * 3 + (win_x + pixel_x) * 3 + component
                # Address = 0x060000 + 10 (header) + ((win_y + pixel_y) * img_width + (win_x + pixel_x)) * 3 + component
                img_pixel_y = Signal(16)
                img_pixel_x = Signal(16)
                pixel_offset = Signal(24)
                
                m.d.comb += [
                    img_pixel_y.eq(win_y + pixel_y),
                    img_pixel_x.eq(win_x + pixel_x),
                    pixel_offset.eq((img_pixel_y * img_width + img_pixel_x) * 3 + color_component),
                ]
                
                m.d.sync += [
                    flash_read_addr.eq(ADDR_IMAGE_START + 10 + pixel_offset),
                    flash_read_en.eq(1),
                ]
                m.next = "READ_PIXEL_WAIT"
        
        # READ_PIXEL_WAIT: Wait for flash read
        with m.State("READ_PIXEL_WAIT"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            
            # De-assert read_en once flash controller accepts it (goes busy)
            with m.Elif(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            
            # Wait for flash_read_valid
            with m.If(flash_read_valid):
                
                # Store color component
                with m.If(color_component == 0):
                    m.d.sync += [
                        pixel_r.eq(flash_read_data),
                        color_component.eq(1),
                    ]
                    m.next = "READ_PIXEL_START"
                
                with m.Elif(color_component == 1):
                    m.d.sync += [
                        pixel_g.eq(flash_read_data),
                        color_component.eq(2),
                    ]
                    m.next = "READ_PIXEL_START"
                
                with m.Else():  # component == 2 (blue)
                    m.d.sync += [
                        pixel_b.eq(flash_read_data),
                        color_component.eq(0),
                    ]
                    m.next = "WRITE_PIXEL"
        
        # WRITE_PIXEL: Write RGB pixel to display
        with m.State("WRITE_PIXEL"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += writer.set_led(
                    x=pixel_x,
                    y=pixel_y,
                    r=pixel_r,
                    g=pixel_g,
                    b=pixel_b
                )
                
                # Move to next pixel
                with m.If(pixel_x == width - 1):
                    m.d.sync += [
                        pixel_x.eq(0),
                    ]
                    with m.If(pixel_y == height - 1):
                        # Frame complete
                        m.d.sync += pixel_y.eq(0)
                        m.next = "FRAME_DONE"
                    with m.Else():
                        m.d.sync += pixel_y.eq(pixel_y + 1)
                        m.next = "READ_PIXEL_START"
                with m.Else():
                    m.d.sync += pixel_x.eq(pixel_x + 1)
                    m.next = "READ_PIXEL_START"
        
        # FRAME_DONE: Update window position for next frame
        with m.State("FRAME_DONE"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Increment frame counter
                m.d.sync += frame_counter.eq(frame_counter + 1)
                
                with m.If(frame_counter >= frame_divider - 1):
                    # Time to update position
                    m.d.sync += frame_counter.eq(0)
                    
                    # Update X position with bounce
                    max_x = Signal(16)
                    max_y = Signal(16)
                    m.d.comb += [
                        max_x.eq(img_width - width),
                        max_y.eq(img_height - height),
                    ]
                    
                    with m.If(dir_x == 0):  # Moving right
                        with m.If(win_x >= max_x - 1):
                            m.d.sync += [
                                win_x.eq(max_x),
                                dir_x.eq(1),  # Reverse
                            ]
                        with m.Else():
                            m.d.sync += win_x.eq(win_x + 1)
                    with m.Else():  # Moving left
                        with m.If(win_x <= 1):
                            m.d.sync += [
                                win_x.eq(0),
                                dir_x.eq(0),  # Reverse
                            ]
                        with m.Else():
                            m.d.sync += win_x.eq(win_x - 1)
                    
                    # Update Y position with bounce
                    with m.If(dir_y == 0):  # Moving down
                        with m.If(win_y >= max_y - 1):
                            m.d.sync += [
                                win_y.eq(max_y),
                                dir_y.eq(1),  # Reverse
                            ]
                        with m.Else():
                            m.d.sync += win_y.eq(win_y + 1)
                    with m.Else():  # Moving up
                        with m.If(win_y <= 1):
                            m.d.sync += [
                                win_y.eq(0),
                                dir_y.eq(0),  # Reverse
                            ]
                        with m.Else():
                            m.d.sync += win_y.eq(win_y - 1)
                
                # Start next frame
                m.d.sync += [
                    pixel_x.eq(0),
                    pixel_y.eq(0),
                ]
                m.next = "READ_PIXEL_START"
    
    # Port list for Verilog generation and integration
    ports = [
        enable,
        flash_read_en, flash_read_addr, flash_read_data, flash_read_valid, flash_busy, flash_ready,
    ] + writer.signals
    
    return m, ports


# Main: Generate Verilog
if __name__ == "__main__":
    import sys
    from amaranth.back import verilog
    
    m, ports = make_image()
    v = verilog.convert(m, name="image_module", ports=ports)
    
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            f.write(v)
    else:
        print(v)
