"""Image display module with DVD-logo-style skating animation.

This module reads images from flash memory and displays a moving
window on the 8x16 LED display. Supports multiple concatenated images.

Image format in flash (starting at ADDR_IMAGE_START):
    Per image (concatenated):
        [MAGIC:8]         'I' (0x49)
        [LENGTH:24]       Image data size in bytes (big-endian)
        [WIDTH:16]        Image width in pixels (big-endian)
        [HEIGHT:16]       Image height in pixels (big-endian)
        [FRAME_DIV:16]    Frames between position updates (big-endian)
        [DATA...]         RGB data: width x height x 3 bytes

    After the last image, the next byte won't be 'I', so it wraps to start.
    short_press cycles to the next image.
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
    short_press = Signal(name="short_press")  # Button press to advance to next image
    
    # Flash controller interface
    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")
    
    # Image header data
    image_valid = Signal(name="image_valid")
    img_width = Signal(16, name="img_width")
    img_height = Signal(16, name="img_height")
    frame_divider = Signal(16, name="frame_divider")
    
    # Multi-image tracking
    ADDR_IMAGE_START = 0x0b0000
    current_image_addr = Signal(24, reset=ADDR_IMAGE_START, name="current_image_addr")
    next_image_addr = Signal(24, name="next_image_addr")  # computed from header length
    img_data_length = Signal(24, name="img_data_length")  # from header
    
    # Current display window position in image
    win_x = Signal(16, name="win_x")
    win_y = Signal(16, name="win_y")
    dir_x = Signal(name="dir_x")
    dir_y = Signal(name="dir_y")
    
    # Pixel reading state
    pixel_x = Signal(range(width), name="pixel_x")
    pixel_y = Signal(range(height), name="pixel_y")
    color_component = Signal(2, name="color_component")
    pixel_r = Signal(8, name="pixel_r")
    pixel_g = Signal(8, name="pixel_g")
    pixel_b = Signal(8, name="pixel_b")
    
    # Frame divider counter
    frame_counter = Signal(16, name="frame_counter")
    
    # Header reading
    header_byte = Signal(4, name="header_byte")
    header_buf = Signal(72, name="header_buf")  # 9 bytes after magic
    
    # Advance request (latched from short_press, cleared when acted on)
    advance_request = Signal(name="advance_request")
    
    # Latch short_press into advance_request (set on press, clear on use)
    with m.If(short_press):
        m.d.sync += advance_request.eq(1)
    
    with m.FSM(name="image_fsm"):
        with m.State("IDLE"):
            with m.If(enable & flash_ready):
                m.d.sync += [
                    flash_read_addr.eq(current_image_addr),
                    flash_read_en.eq(1),
                    header_byte.eq(0),
                    image_valid.eq(0),
                ]
                m.next = "READ_HEADER"
            with m.Else():
                m.d.sync += [
                    writer.clear(),
                    flash_read_en.eq(0),
                ]
        
        with m.State("READ_HEADER"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            
            with m.Elif(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            
            with m.If(flash_read_valid):
                # First byte: check magic
                with m.If(header_byte == 0):
                    with m.If(flash_read_data == ord('I')):
                        m.d.sync += [
                            header_buf.eq(0),
                            header_byte.eq(1),
                            flash_read_addr.eq(flash_read_addr + 1),
                            flash_read_en.eq(1),
                        ]
                    with m.Else():
                        # Not 'I' - wrap to start
                        m.d.sync += [
                            current_image_addr.eq(ADDR_IMAGE_START),
                            flash_read_addr.eq(ADDR_IMAGE_START),
                            flash_read_en.eq(1),
                            header_byte.eq(0),
                        ]
                with m.Else():
                    m.d.sync += [
                        header_buf.eq((header_buf << 8) | flash_read_data),
                        header_byte.eq(header_byte + 1),
                    ]
                    
                    with m.If(header_byte == 9):
                        m.next = "PARSE_HEADER"
                    with m.Else():
                        m.d.sync += [
                            flash_read_addr.eq(flash_read_addr + 1),
                            flash_read_en.eq(1),
                        ]
        
        with m.State("PARSE_HEADER"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # header_buf is 72 bits with 9 bytes (1-9) shifted in, newest at LSB
                # byte1 at [71:64], byte2 at [63:56], ..., byte9 at [7:0]
                # bytes 1-3: length(24), 4-5: width(16), 6-7: height(16), 8-9: framediv(16)
                m.d.sync += [
                    img_data_length[16:24].eq(header_buf[64:72]),
                    img_data_length[8:16].eq(header_buf[56:64]),
                    img_data_length[0:8].eq(header_buf[48:56]),
                    img_width.eq((header_buf[40:48] << 8) | header_buf[32:40]),
                    img_height.eq((header_buf[24:32] << 8) | header_buf[16:24]),
                    frame_divider.eq((header_buf[8:16] << 8) | header_buf[0:8]),
                    win_x.eq(0),
                    win_y.eq(0),
                    dir_x.eq(0),
                    dir_y.eq(0),
                    frame_counter.eq(0),
                    image_valid.eq(1),
                ]
                m.next = "CALC_NEXT"
        
        with m.State("CALC_NEXT"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Now img_data_length is valid
                m.d.sync += [
                    next_image_addr.eq(current_image_addr + 10 + img_data_length),
                    pixel_x.eq(0),
                    pixel_y.eq(0),
                    color_component.eq(0),
                    advance_request.eq(0),  # clear any pending advance
                ]
                m.next = "READ_PIXEL_START"
        
        with m.State("READ_PIXEL_START"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                img_pixel_y = Signal(16)
                img_pixel_x = Signal(16)
                pixel_offset = Signal(24)
                
                m.d.comb += [
                    img_pixel_y.eq(win_y + pixel_y),
                    img_pixel_x.eq(win_x + pixel_x),
                    pixel_offset.eq((img_pixel_y * img_width + img_pixel_x) * 3 + color_component),
                ]
                
                m.d.sync += [
                    flash_read_addr.eq(current_image_addr + 10 + pixel_offset),
                    flash_read_en.eq(1),
                ]
                m.next = "READ_PIXEL_WAIT"
        
        with m.State("READ_PIXEL_WAIT"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            
            with m.Elif(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            
            with m.If(flash_read_valid):
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
                
                with m.Else():
                    m.d.sync += [
                        pixel_b.eq(flash_read_data),
                        color_component.eq(0),
                    ]
                    m.next = "WRITE_PIXEL"
        
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
                
                with m.If(pixel_x == width - 1):
                    m.d.sync += pixel_x.eq(0)
                    with m.If(pixel_y == height - 1):
                        m.d.sync += pixel_y.eq(0)
                        m.next = "FRAME_DONE"
                    with m.Else():
                        m.d.sync += pixel_y.eq(pixel_y + 1)
                        m.next = "READ_PIXEL_START"
                with m.Else():
                    m.d.sync += pixel_x.eq(pixel_x + 1)
                    m.next = "READ_PIXEL_START"
        
        with m.State("FRAME_DONE"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Check for advance request (button press)
                with m.If(advance_request):
                    m.d.sync += [
                        advance_request.eq(0),
                        current_image_addr.eq(next_image_addr),
                        image_valid.eq(0),
                    ]
                    m.next = "IDLE"  # will re-enter and read next header
                with m.Else():
                    m.d.sync += frame_counter.eq(frame_counter + 1)
                    
                    with m.If(frame_counter >= frame_divider - 1):
                        m.d.sync += frame_counter.eq(0)
                        
                        max_x = Signal(16)
                        max_y = Signal(16)
                        m.d.comb += [
                            max_x.eq(img_width - width),
                            max_y.eq(img_height - height),
                        ]
                        
                        with m.If(dir_x == 0):
                            with m.If(win_x >= max_x - 1):
                                m.d.sync += [win_x.eq(max_x), dir_x.eq(1)]
                            with m.Else():
                                m.d.sync += win_x.eq(win_x + 1)
                        with m.Else():
                            with m.If(win_x <= 1):
                                m.d.sync += [win_x.eq(0), dir_x.eq(0)]
                            with m.Else():
                                m.d.sync += win_x.eq(win_x - 1)
                        
                        with m.If(dir_y == 0):
                            with m.If(win_y >= max_y - 1):
                                m.d.sync += [win_y.eq(max_y), dir_y.eq(1)]
                            with m.Else():
                                m.d.sync += win_y.eq(win_y + 1)
                        with m.Else():
                            with m.If(win_y <= 1):
                                m.d.sync += [win_y.eq(0), dir_y.eq(0)]
                            with m.Else():
                                m.d.sync += win_y.eq(win_y - 1)
                    
                    m.d.sync += [
                        pixel_x.eq(0),
                        pixel_y.eq(0),
                    ]
                    m.next = "READ_PIXEL_START"
    
    ports = [
        enable,
        short_press,
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
