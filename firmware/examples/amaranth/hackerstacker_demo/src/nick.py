#!/usr/bin/env python3
"""Nick display - reads nick text + font glyphs from flash, renders to LED matrix.

Architecture:
    - Nick data at 0x0a0000 (text + colors)
    - Font data at 0x080000 (pre-rendered glyph bitmaps)
    - At boot: read font header to get offset table + per-font params
    - At display: for each char, lookup glyph in font, render columns
    - No multiplier: glyph_addr = font_offset[F] + (char_code << slot_shift)
"""

import sys
from amaranth import Module, Signal, Cat, Const
from amaranth.back import verilog
from sk9822 import SK9822Writer

DISPLAY_WIDTH = 8
DISPLAY_HEIGHT = 16
MAX_FONTS = 8
MAX_NICK_LEN = 256
SCROLL_STEP_BITS = 19
SCROLL_PAUSE_STEPS = 15


def make_nick(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
    m = Module()
    writer = SK9822Writer(width, height, name_prefix="nick_")

    enable = Signal(name="enable")
    short_press = Signal(name="short_press")
    btn_right = Signal(name="btn_right")
    btn_left = Signal(name="btn_left")

    flash_read_en = Signal(name="flash_read_en")
    flash_read_addr = Signal(24, name="flash_read_addr")
    flash_read_data = Signal(8, name="flash_read_data")
    flash_read_valid = Signal(name="flash_read_valid")
    flash_busy = Signal(name="flash_busy")
    flash_ready = Signal(name="flash_ready")

    ADDR_NICK_START = 0x0a0000
    ADDR_FONT_START = 0x080000

    # Font metadata (loaded at boot)
    num_fonts = Signal(8, name="num_fonts")
    font_offset = [Signal(24, name=f"font_offset_{i}") for i in range(MAX_FONTS)]
    font_orient = [Signal(8, name=f"font_orient_{i}") for i in range(MAX_FONTS)]
    font_height_reg = [Signal(8, name=f"font_height_{i}") for i in range(MAX_FONTS)]
    font_width_reg = [Signal(8, name=f"font_width_{i}") for i in range(MAX_FONTS)]
    font_shift = [Signal(4, name=f"font_shift_{i}") for i in range(MAX_FONTS)]
    fonts_loaded = Signal(name="fonts_loaded")

    # Nick metadata
    num_nicks = Signal(8, name="num_nicks")
    nicks_loaded = Signal(name="nicks_loaded")
    current_nick = Signal(8, name="current_nick")
    current_font = Signal(8, name="current_font")

    nick_fg_r = Signal(8, name="nick_fg_r")
    nick_fg_g = Signal(8, name="nick_fg_g")
    nick_fg_b = Signal(8, name="nick_fg_b")
    nick_bg_r = Signal(8, name="nick_bg_r")
    nick_bg_g = Signal(8, name="nick_bg_g")
    nick_bg_b = Signal(8, name="nick_bg_b")
    nick_strlen = Signal(8, name="nick_strlen")

    # Nick text buffer BRAM
    from amaranth.lib.memory import Memory
    nick_mem = Memory(shape=8, depth=MAX_NICK_LEN, init=[])
    m.submodules.nick_mem = nick_mem
    nm_wr = nick_mem.write_port()
    nm_rd = nick_mem.read_port(domain="sync", transparent_for=())
    nm_wr_addr = Signal(8)
    nm_wr_data = Signal(8)
    nm_wr_en = Signal()
    nm_rd_addr = Signal(8)
    m.d.comb += [
        nm_wr.addr.eq(nm_wr_addr), nm_wr.data.eq(nm_wr_data), nm_wr.en.eq(nm_wr_en),
        nm_rd.addr.eq(nm_rd_addr),
    ]

    # Active font params (latched)
    active_orient = Signal(8, name="active_orient")
    active_width = Signal(8, name="active_width")
    active_height = Signal(8, name="active_height")
    active_shift = Signal(4, name="active_shift")
    active_offset = Signal(24, name="active_offset")

    # Display geometry
    render_cols = Signal(5, name="render_cols")
    render_rows_max = Signal(5, name="render_rows_max")
    nick_pixel_width = Signal(12, name="nick_pixel_width")

    # Rendering state
    char_idx = Signal(8, name="char_idx")
    glyph_col = Signal(12, name="glyph_col")
    display_col = Signal(12, name="display_col")
    render_col = Signal(5, name="render_col")
    render_row = Signal(5, name="render_row")
    col_data_lo = Signal(8, name="col_data_lo")
    col_data_hi = Signal(8, name="col_data_hi")

    # Scrolling
    scroll_offset = Signal(12, name="scroll_offset")
    scroll_dir = Signal()
    scroll_timer = Signal(SCROLL_STEP_BITS + 1)
    scroll_paused = Signal()
    pause_count = Signal(5)
    scroll_max = Signal(12)
    needs_scroll = Signal()
    scroll_mode = Signal(reset=1)

    # FSM counters
    boot_byte = Signal(5, name="boot_byte")
    font_idx = Signal(4, name="font_idx")
    nick_scan_count = Signal(8)
    meta_byte = Signal(4)
    load_count = Signal(8)
    nick_loaded = Signal()

    # Button pending latches
    pending_right = Signal()
    pending_left = Signal()
    consume_right = Signal()
    consume_left = Signal()

    with m.If(~enable | consume_right):
        m.d.sync += pending_right.eq(0)
    with m.Elif(btn_right):
        m.d.sync += pending_right.eq(1)

    with m.If(~enable | consume_left):
        m.d.sync += pending_left.eq(0)
    with m.Elif(btn_left):
        m.d.sync += pending_left.eq(1)

    # ===== FSM =====
    with m.FSM(name="nick_fsm"):

        with m.State("IDLE"):
            with m.If(enable & flash_ready & ~fonts_loaded):
                m.d.sync += [flash_read_addr.eq(ADDR_FONT_START),
                             flash_read_en.eq(1), boot_byte.eq(0)]
                m.next = "FONT_HDR"
            with m.Elif(enable & fonts_loaded & ~nicks_loaded):
                m.d.sync += [flash_read_addr.eq(ADDR_NICK_START),
                             flash_read_en.eq(1), boot_byte.eq(0)]
                m.next = "NICK_HDR"
            with m.Elif(enable & fonts_loaded & nicks_loaded & ~nick_loaded):
                m.next = "FIND_NICK"
            with m.Elif(enable & nick_loaded):
                m.next = "SETUP_RENDER"
            with m.Else():
                m.d.sync += [writer.clear(), flash_read_en.eq(0)]

        # ---- Font header: magic(1) ver(1) num_fonts_hi(1) num_fonts_lo(1) reserved(4) ----
        with m.State("FONT_HDR"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [boot_byte.eq(boot_byte + 1),
                             flash_read_addr.eq(flash_read_addr + 1),
                             flash_read_en.eq(1)]
                with m.Switch(boot_byte):
                    with m.Case(0):
                        with m.If(flash_read_data != ord('F')):
                            m.d.sync += flash_read_en.eq(0)
                            m.next = "IDLE"
                    with m.Case(3):
                        m.d.sync += num_fonts.eq(flash_read_data)
                    with m.Default():
                        with m.If(boot_byte == 7):
                            m.d.sync += [font_idx.eq(0), boot_byte.eq(0)]
                            m.next = "FONT_OFFSETS"

        # ---- Offset table: MAX_FONTS x 4 bytes (32-bit BE) ----
        with m.State("FONT_OFFSETS"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [flash_read_addr.eq(flash_read_addr + 1),
                             flash_read_en.eq(1),
                             boot_byte.eq(boot_byte + 1)]
                with m.Switch(boot_byte[:2]):
                    with m.Case(1):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_offset[i][16:24].eq(flash_read_data)
                    with m.Case(2):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_offset[i][8:16].eq(flash_read_data)
                    with m.Case(3):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_offset[i][0:8].eq(flash_read_data)
                        m.d.sync += boot_byte.eq(0)
                        with m.If(font_idx == MAX_FONTS - 1):
                            m.d.sync += [font_idx.eq(0)]
                            m.next = "FONT_ENTRY_HDR"
                        with m.Else():
                            m.d.sync += font_idx.eq(font_idx + 1)

        # ---- Read font entry headers (24 bytes each) ----
        with m.State("FONT_ENTRY_HDR"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [flash_read_addr.eq(flash_read_addr + 1),
                             flash_read_en.eq(1),
                             boot_byte.eq(boot_byte + 1)]
                with m.Switch(boot_byte):
                    with m.Case(0x12):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_orient[i].eq(flash_read_data)
                    with m.Case(0x13):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_height_reg[i].eq(flash_read_data)
                    with m.Case(0x14):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_width_reg[i].eq(flash_read_data)
                    with m.Case(0x16):
                        for i in range(MAX_FONTS):
                            with m.If(font_idx == i):
                                m.d.sync += font_shift[i].eq(flash_read_data[:4])
                with m.If(boot_byte == 23):
                    m.d.sync += boot_byte.eq(0)
                    with m.If((font_idx + 1) >= num_fonts):
                        m.d.sync += [fonts_loaded.eq(1), flash_read_en.eq(0)]
                        m.next = "IDLE"
                    with m.Else():
                        m.d.sync += [font_idx.eq(font_idx + 1), flash_read_en.eq(0)]
                        m.next = "FONT_ENTRY_SEEK"

        with m.State("FONT_ENTRY_SEEK"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                for i in range(MAX_FONTS):
                    with m.If(font_idx == i):
                        m.d.sync += flash_read_addr.eq(font_offset[i] - 24)
                m.d.sync += [flash_read_en.eq(1), boot_byte.eq(0)]
                m.next = "FONT_ENTRY_HDR"

        # ---- Nick header ----
        with m.State("NICK_HDR"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [boot_byte.eq(boot_byte + 1),
                             flash_read_addr.eq(flash_read_addr + 1),
                             flash_read_en.eq(1)]
                with m.Switch(boot_byte):
                    with m.Case(0):
                        with m.If(flash_read_data != ord('N')):
                            m.d.sync += flash_read_en.eq(0)
                            m.next = "IDLE"
                    with m.Case(3):
                        m.d.sync += num_nicks.eq(flash_read_data)
                    with m.Default():
                        with m.If(boot_byte == 7):
                            m.d.sync += [nicks_loaded.eq(1), flash_read_en.eq(0),
                                         current_nick.eq(0)]
                            m.next = "IDLE"

        # ---- Find current nick ----
        with m.State("FIND_NICK"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(current_nick >= num_nicks):
                    m.d.sync += current_nick.eq(0)
                m.d.sync += [flash_read_addr.eq(ADDR_NICK_START + 8),
                             nick_scan_count.eq(0), meta_byte.eq(0),
                             flash_read_en.eq(1)]
                m.next = "NICK_SCAN"

        # Scan nick entry headers
        with m.State("NICK_SCAN"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [flash_read_addr.eq(flash_read_addr + 1),
                             flash_read_en.eq(1),
                             meta_byte.eq(meta_byte + 1)]
                with m.Switch(meta_byte):
                    with m.Case(4): m.d.sync += nick_fg_r.eq(flash_read_data)
                    with m.Case(5): m.d.sync += nick_fg_g.eq(flash_read_data)
                    with m.Case(6): m.d.sync += nick_fg_b.eq(flash_read_data)
                    with m.Case(7): m.d.sync += nick_bg_r.eq(flash_read_data)
                    with m.Case(8): m.d.sync += nick_bg_g.eq(flash_read_data)
                    with m.Case(9): m.d.sync += nick_bg_b.eq(flash_read_data)
                    with m.Case(11): m.d.sync += nick_strlen.eq(flash_read_data)
                with m.If(meta_byte == 15):
                    with m.If(nick_scan_count >= current_nick):
                        m.d.sync += [load_count.eq(0), flash_read_en.eq(0)]
                        m.next = "NICK_LOAD_TEXT"
                    with m.Else():
                        m.next = "NICK_SKIP"

        with m.State("NICK_SKIP"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.Else():
                m.d.sync += [
                    flash_read_addr.eq(flash_read_addr + ((nick_strlen + 7) & 0xF8)),
                    nick_scan_count.eq(nick_scan_count + 1),
                    meta_byte.eq(0), flash_read_en.eq(1),
                ]
                m.next = "NICK_SCAN"

        with m.State("NICK_LOAD_TEXT"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.Else():
                with m.If(load_count >= nick_strlen):
                    m.d.sync += nick_loaded.eq(1)
                    m.next = "SETUP_RENDER"
                with m.Else():
                    m.d.sync += flash_read_en.eq(1)
                    m.next = "NICK_LOAD_RD"

        with m.State("NICK_LOAD_RD"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                # write full 8-bit load_count into BRAM address (support full 256 length)
                m.d.comb += [nm_wr_en.eq(1), nm_wr_addr.eq(load_count),
                             nm_wr_data.eq(flash_read_data)]
                m.d.sync += [load_count.eq(load_count + 1),
                             flash_read_addr.eq(flash_read_addr + 1)]
                with m.If(load_count >= nick_strlen - 1):
                    m.d.sync += [nick_loaded.eq(1), flash_read_en.eq(0)]
                    m.next = "SETUP_RENDER"
                with m.Else():
                    m.d.sync += flash_read_en.eq(1)

        # ---- Setup rendering ----
        with m.State("SETUP_RENDER"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                for i in range(MAX_FONTS):
                    with m.If(current_font == i):
                        m.d.sync += [
                            active_orient.eq(font_orient[i]),
                            active_height.eq(font_height_reg[i]),
                            active_width.eq(font_width_reg[i]),
                            active_shift.eq(font_shift[i]),
                            active_offset.eq(font_offset[i]),
                        ]
                        with m.If(font_orient[i] == ord('H')):
                            m.d.sync += [render_cols.eq(height),
                                         render_rows_max.eq(width - 1)]
                        with m.Else():
                            m.d.sync += [render_cols.eq(width),
                                         render_rows_max.eq(height - 1)]
                m.d.sync += [scroll_offset.eq(0), scroll_dir.eq(0),
                             scroll_paused.eq(1), pause_count.eq(0),
                             scroll_timer.eq(0), nick_pixel_width.eq(0),
                             char_idx.eq(0)]
                m.next = "CALC_PW_LOOP"

        # Compute nick_pixel_width = nick_strlen * active_width (iterative add)
        with m.State("CALC_PW_LOOP"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(char_idx >= nick_strlen):
                    with m.If(active_orient == ord('H')):
                        with m.If(nick_pixel_width > height):
                            m.d.sync += [needs_scroll.eq(1),
                                         scroll_max.eq(nick_pixel_width - height)]
                        with m.Else():
                            m.d.sync += [needs_scroll.eq(0), scroll_max.eq(0)]
                    with m.Else():
                        with m.If(nick_pixel_width > width):
                            m.d.sync += [needs_scroll.eq(1),
                                         scroll_max.eq(nick_pixel_width - width)]
                        with m.Else():
                            m.d.sync += [needs_scroll.eq(0), scroll_max.eq(0)]
                    m.d.sync += [char_idx.eq(0), glyph_col.eq(0), render_col.eq(0)]
                    m.next = "RENDER_START"
                with m.Else():
                    m.d.sync += [nick_pixel_width.eq(nick_pixel_width + active_width),
                                 char_idx.eq(char_idx + 1)]

        # ---- Render loop ----
        with m.State("RENDER_START"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += display_col.eq(scroll_offset + render_col)
                m.next = "RENDER_CALC_CHAR"

        # Divide display_col by active_width to get char_idx and glyph_col
        with m.State("RENDER_CALC_CHAR"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If((scroll_mode == 1) & (display_col < render_cols)):
                    # Marquee leading blank: draw background
                    m.d.sync += [col_data_lo.eq(0), col_data_hi.eq(0),
                                 render_row.eq(0)]
                    m.next = "RENDER_ROWS"
                with m.Else():
                    with m.If(scroll_mode == 1):
                        m.d.sync += [char_idx.eq(0),
                                     glyph_col.eq(display_col - render_cols)]
                    with m.Else():
                        m.d.sync += [char_idx.eq(0), glyph_col.eq(display_col)]
                    m.next = "RENDER_DIV"

        with m.State("RENDER_DIV"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(glyph_col >= active_width):
                    m.d.sync += [glyph_col.eq(glyph_col - active_width),
                                 char_idx.eq(char_idx + 1)]
                with m.Else():
                    with m.If(char_idx >= nick_strlen):
                        m.d.sync += [col_data_lo.eq(0), col_data_hi.eq(0),
                                     render_row.eq(0)]
                        m.next = "RENDER_ROWS"
                    with m.Else():
                        # read full 8-bit char_idx from BRAM
                        m.d.comb += nm_rd_addr.eq(char_idx)
                        m.next = "RENDER_RD_CHAR"

        # Wait for BRAM read
        with m.State("RENDER_RD_CHAR"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # read full 8-bit char_idx from BRAM
                m.d.comb += nm_rd_addr.eq(char_idx)
                m.next = "RENDER_FETCH"

        # Compute glyph flash addr and start reading
        with m.State("RENDER_FETCH"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.Else():
                char_code_sig = Signal(8, name="fetch_cc")
                m.d.comb += char_code_sig.eq(nm_rd.data)
                shifted = Signal(16, name="shifted")
                for s in [3, 4, 5, 6]:
                    with m.If(active_shift == s):
                        m.d.comb += shifted.eq(char_code_sig << s)
                glyph_base = Signal(24, name="glyph_base")
                m.d.comb += glyph_base.eq(active_offset + shifted[:16])
                col_addr = Signal(24, name="col_addr")
                with m.If(active_height > 8):
                    m.d.comb += col_addr.eq(glyph_base + (glyph_col << 1))
                with m.Else():
                    m.d.comb += col_addr.eq(glyph_base + glyph_col)
                m.d.sync += [flash_read_addr.eq(col_addr), flash_read_en.eq(1)]
                m.next = "RENDER_RD_LO"

        with m.State("RENDER_RD_LO"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += col_data_lo.eq(flash_read_data)
                with m.If(active_height > 8):
                    m.d.sync += [flash_read_addr.eq(flash_read_addr + 1),
                                 flash_read_en.eq(1)]
                    m.next = "RENDER_RD_HI"
                with m.Else():
                    m.d.sync += [col_data_hi.eq(0), render_row.eq(0),
                                 flash_read_en.eq(0)]
                    m.next = "RENDER_ROWS"

        with m.State("RENDER_RD_HI"):
            with m.If(~enable):
                m.d.sync += flash_read_en.eq(0)
                m.next = "IDLE"
            with m.If(flash_busy):
                m.d.sync += flash_read_en.eq(0)
            with m.If(flash_read_valid):
                m.d.sync += [col_data_hi.eq(flash_read_data), render_row.eq(0),
                             flash_read_en.eq(0)]
                m.next = "RENDER_ROWS"

        with m.State("RENDER_ROWS"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                pixel_bit = Signal(name="pixel_bit")
                with m.If(render_row < 8):
                    m.d.comb += pixel_bit.eq(col_data_lo.bit_select(render_row[:3], 1))
                with m.Else():
                    m.d.comb += pixel_bit.eq(col_data_hi.bit_select(render_row[:3], 1))
                display_x = Signal(4, name="display_x")
                display_y = Signal(5, name="display_y")
                with m.If(active_orient == ord('H')):
                    m.d.comb += [display_x.eq(width - 1 - render_row),
                                 display_y.eq(render_col)]
                with m.Else():
                    m.d.comb += [display_x.eq(render_cols - 1 - render_col),
                                 display_y.eq(render_rows_max - render_row)]
                with m.If(pixel_bit):
                    m.d.sync += writer.set_led(x=display_x, y=display_y,
                                              r=nick_fg_r, g=nick_fg_g, b=nick_fg_b)
                with m.Else():
                    m.d.sync += writer.set_led(x=display_x, y=display_y,
                                              r=nick_bg_r, g=nick_bg_g, b=nick_bg_b)
                with m.If(render_row == render_rows_max):
                    m.next = "NEXT_COL"
                with m.Else():
                    m.d.sync += render_row.eq(render_row + 1)

        with m.State("NEXT_COL"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(render_col == render_cols - 1):
                    m.next = "DISPLAY"
                with m.Else():
                    m.d.sync += render_col.eq(render_col + 1)
                    m.next = "RENDER_START"

        # ---- Display: scroll + buttons ----
        with m.State("DISPLAY"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(short_press):
                    m.d.sync += [current_nick.eq(current_nick + 1), nick_loaded.eq(0)]
                    m.next = "FIND_NICK"
                with m.Elif(pending_right | btn_right):
                    m.d.comb += consume_right.eq(1)
                    with m.If((current_font + 1) >= num_fonts):
                        m.d.sync += current_font.eq(0)
                    with m.Else():
                        m.d.sync += current_font.eq(current_font + 1)
                    m.next = "SETUP_RENDER"
                with m.Elif(pending_left | btn_left):
                    m.d.comb += consume_left.eq(1)
                    m.d.sync += [scroll_mode.eq(~scroll_mode),
                                 scroll_offset.eq(0), scroll_dir.eq(0),
                                 scroll_paused.eq(1), pause_count.eq(0),
                                 scroll_timer.eq(0), render_col.eq(0)]
                    m.next = "RENDER_START"
                with m.Elif(needs_scroll):
                    m.d.sync += scroll_timer.eq(scroll_timer + 1)
                    with m.If(scroll_timer == (1 << SCROLL_STEP_BITS)):
                        m.d.sync += scroll_timer.eq(0)
                        with m.If(scroll_paused):
                            with m.If(pause_count >= SCROLL_PAUSE_STEPS):
                                m.d.sync += [scroll_paused.eq(0), pause_count.eq(0)]
                            with m.Else():
                                m.d.sync += pause_count.eq(pause_count + 1)
                        with m.Else():
                            with m.If(scroll_mode == 0):
                                with m.If(scroll_dir == 0):
                                    with m.If(scroll_offset >= scroll_max):
                                        m.d.sync += [scroll_paused.eq(1),
                                                     scroll_dir.eq(1), pause_count.eq(0)]
                                    with m.Else():
                                        m.d.sync += [scroll_offset.eq(scroll_offset + 1),
                                                     render_col.eq(0)]
                                        m.next = "RENDER_START"
                                with m.Else():
                                    with m.If(scroll_offset == 0):
                                        m.d.sync += [scroll_paused.eq(1),
                                                     scroll_dir.eq(0), pause_count.eq(0)]
                                    with m.Else():
                                        m.d.sync += [scroll_offset.eq(scroll_offset - 1),
                                                     render_col.eq(0)]
                                        m.next = "RENDER_START"
                            with m.Else():
                                # Marquee scroll logic
                                with m.If(scroll_offset >= (nick_pixel_width + render_cols + render_cols)):
                                    m.d.sync += [scroll_offset.eq(0), render_col.eq(0)]
                                    m.next = "RENDER_START"
                                with m.Else():
                                    m.d.sync += [scroll_offset.eq(scroll_offset + 1),
                                                 render_col.eq(0)]
                                    m.next = "RENDER_START"

    ports = [
        enable, short_press, btn_right, btn_left,
        flash_read_en, flash_read_addr, flash_read_data,
        flash_read_valid, flash_busy, flash_ready,
    ] + writer.signals
    return m, ports



def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/nick.py path/to/output.v")
        sys.exit(1)
    out = sys.argv[1]
    m, ports = make_nick(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
    v = verilog.convert(m, name="nick_module", ports=ports)
    with open(out, "w") as f:
        f.write(v)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
