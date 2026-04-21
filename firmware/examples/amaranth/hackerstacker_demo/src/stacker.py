#!/usr/bin/env python3
"""Hacker-Stacker game module.

A single-button stacking game on the 8x16 LED display.

Gameplay:
    - A brick bounces left<->right on the bottom row.
    - Press the button to freeze it.
    - A new brick (same width) appears on the next row, bouncing again.
    - When freezing, any overhanging blocks (not aligned with the
      brick below) are trimmed off, so the brick can get shorter.
    - Speed increases each row.
    - The goal is to stack 16 rows perfectly aligned.
    - If the brick is trimmed to zero width, the game is lost.
    - After win/loss, the game restarts.

Brick color cycles through a palette so each row is visually distinct.
"""
import sys
from amaranth import Module, Signal, Mux, Cat
from amaranth.back import verilog
from sk9822 import SK9822Writer


# Row color palette (R, G, B) - one per row, visually distinct
ROW_COLORS = [
    (0xFF, 0x00, 0x00),  # row 0:  red
    (0xFF, 0x80, 0x00),  # row 1:  orange
    (0xFF, 0xFF, 0x00),  # row 2:  yellow
    (0x00, 0xFF, 0x00),  # row 3:  green
    (0x00, 0xFF, 0x80),  # row 4:  spring
    (0x00, 0xFF, 0xFF),  # row 5:  cyan
    (0x00, 0x80, 0xFF),  # row 6:  azure
    (0x00, 0x00, 0xFF),  # row 7:  blue
    (0x80, 0x00, 0xFF),  # row 8:  violet
    (0xFF, 0x00, 0xFF),  # row 9:  magenta
    (0xFF, 0x00, 0x80),  # row 10: rose
    (0xFF, 0x40, 0x40),  # row 11: coral
    (0x80, 0xFF, 0x00),  # row 12: lime
    (0x00, 0xFF, 0x40),  # row 13: emerald
    (0x40, 0x40, 0xFF),  # row 14: periwinkle
    (0xFF, 0xFF, 0xFF),  # row 15: white (victory row!)
]

INITIAL_BRICK_WIDTH = 6
RAINBOW_DURATION = 160_000_000  # 10 seconds at 16 MHz
SCORE_DISPLAY_TIME = 2**25      # ~2 seconds at 16 MHz


def make_stacker(width=8, height=16):
    """Create hacker-stacker game module.

    Args:
        width:  display width in pixels  (default 8)
        height: display height in pixels (default 16)

    Returns:
        (module, ports) tuple
    """
    m = Module()

    # LED writer
    writer = SK9822Writer(width, height, name_prefix="stacker_")

    # --- external interface ---
    enable = Signal(name="enable")
    short_press = Signal(name="short_press")  # button input (active-high pulse)
    cheat_en = Signal(name="cheat_en")  # backdoor! Win at row 8 instead of 16

    # --- game state ---
    # Per-row bitmask: for each row, 8 bits saying which columns are occupied
    # We store these in individual signals (iCE40 has no large async-read RAM
    # that is convenient here, and 16x8 = 128 FFs is fine).
    row_mask = [Signal(width, name=f"row_mask_{i}") for i in range(height)]

    current_row = Signal(range(height + 1), name="current_row")  # which row the player is on (0-15; 16 = win)
    brick_pos = Signal(range(width), name="brick_pos")      # left edge of current brick
    brick_width = Signal(range(width + 1), name="brick_width")  # width of current brick (1-8; 0 = game over)
    direction = Signal(name="direction")  # 0 = moving right, 1 = moving left

    # Timing: speed counter.  Brick moves once every (speed_limit) ticks of
    # a base ~60 Hz timer.  speed_limit decreases each row for faster play.
    # Base timer: 12 MHz / 2^17 ~ 92 Hz (~25% faster than original 16 MHz / 2^18)
    base_timer = Signal(17, name="base_timer")
    base_tick = Signal(name="base_tick")
    m.d.sync += base_timer.eq(base_timer + 1)
    m.d.comb += base_tick.eq(base_timer == 0)

    speed_counter = Signal(8, name="speed_counter")
    speed_limit = Signal(8, name="speed_limit")  # counts of base_tick between moves

    # Display refresh helpers
    draw_x = Signal(range(width), name="draw_x")
    draw_y = Signal(range(height), name="draw_y")

    # Overlap computation after button press
    old_mask = Signal(width, name="old_mask")
    new_mask = Signal(width, name="new_mask")
    overlap = Signal(width, name="overlap")

    # Flash timer for game-over / win animations
    flash_timer = Signal(28, name="flash_timer")

    # Restart delay (pause before new game)
    restart_timer = Signal(26, name="restart_timer")  # ~4 seconds at 16 MHz

    # Winner score: number of blocks in the last brick at time of win
    win_score = Signal(range(width + 1), name="win_score")

    # Font renderer interface (shared with nick via board_top mux)
    font_char_code = Signal(8, name="font_char_code")
    font_render_enable = Signal(name="font_render_enable")
    font_render_done = Signal(name="font_render_done")
    font_segment_pattern = Signal(64, name="font_segment_pattern")
    font_active = Signal(name="font_active")  # tells board_top we need font/flash

    # Score rendering state
    score_segment = Signal(64, name="score_segment")  # latched segment pattern
    score_disp_y = Signal(range(8), name="score_disp_y")
    score_disp_x = Signal(range(width), name="score_disp_x")

    # Helper: build current brick bitmask from brick_pos & brick_width
    # e.g. pos=2 width=3 -> 0b00011100
    cur_brick_mask = Signal(width, name="cur_brick_mask")
    m.d.comb += cur_brick_mask.eq(0)
    for w in range(width + 1):
        for p in range(width):
            with m.If((brick_width == w) & (brick_pos == p)):
                mask_val = 0
                for b in range(w):
                    if p + b < width:
                        mask_val |= (1 << (p + b))
                m.d.comb += cur_brick_mask.eq(mask_val)

    # --- FSM ---
    with m.FSM(name="stacker_fsm"):

        # -- IDLE ------------------------------------------------------
        with m.State("IDLE"):
            m.d.sync += writer.clear()
            with m.If(enable):
                # Reset game state
                m.d.sync += [
                    current_row.eq(0),
                    brick_width.eq(INITIAL_BRICK_WIDTH),
                    brick_pos.eq(0),
                    direction.eq(0),
                    speed_counter.eq(0),
                    speed_limit.eq(12),  # start slow (~5 moves/s)
                ]
                for i in range(height):
                    m.d.sync += row_mask[i].eq(0)
                m.next = "DRAW"

        # -- DRAW ------------------------------------------------------
        # Render entire display: frozen rows + current moving brick
        with m.State("DRAW"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Determine pixel color
                # Is this pixel part of a frozen row?
                frozen_bit = Signal(name="frozen_bit")
                active_bit = Signal(name="active_bit")

                # Check frozen rows (combinational mux on draw_y)
                m.d.comb += frozen_bit.eq(0)
                for i in range(height):
                    with m.If(draw_y == i):
                        m.d.comb += frozen_bit.eq(row_mask[i].bit_select(draw_x, 1))

                # Check if this pixel is part of the currently moving brick
                m.d.comb += active_bit.eq(0)
                with m.If(draw_y == current_row):
                    m.d.comb += active_bit.eq(cur_brick_mask.bit_select(draw_x, 1))

                # Pick color
                # Frozen pixels get their row color
                # Active (moving) brick gets current_row color
                # Empty pixels are black
                pixel_r = Signal(8, name="pixel_r")
                pixel_g = Signal(8, name="pixel_g")
                pixel_b = Signal(8, name="pixel_b")
                m.d.comb += [pixel_r.eq(0), pixel_g.eq(0), pixel_b.eq(0)]

                with m.If(frozen_bit):
                    for i in range(height):
                        with m.If(draw_y == i):
                            r, g, b = ROW_COLORS[i]
                            m.d.comb += [pixel_r.eq(r), pixel_g.eq(g), pixel_b.eq(b)]
                with m.Elif(active_bit):
                    for i in range(height):
                        with m.If(current_row == i):
                            r, g, b = ROW_COLORS[i]
                            m.d.comb += [pixel_r.eq(r), pixel_g.eq(g), pixel_b.eq(b)]

                m.d.sync += writer.set_led(x=draw_x, y=draw_y, r=pixel_r, g=pixel_g, b=pixel_b)

                # Advance through all pixels
                with m.If(draw_x == width - 1):
                    m.d.sync += draw_x.eq(0)
                    with m.If(draw_y == height - 1):
                        m.d.sync += draw_y.eq(0)
                        m.next = "PLAY"
                    with m.Else():
                        m.d.sync += draw_y.eq(draw_y + 1)
                with m.Else():
                    m.d.sync += draw_x.eq(draw_x + 1)

        # -- PLAY ------------------------------------------------------
        # Wait for base_tick, move brick, check for button
        with m.State("PLAY"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Button press -> freeze
                with m.If(short_press):
                    m.next = "FREEZE"
                with m.Elif(base_tick):
                    with m.If(speed_counter >= speed_limit):
                        m.d.sync += speed_counter.eq(0)
                        # Move brick
                        with m.If(direction == 0):
                            # Moving right
                            with m.If(brick_pos + brick_width >= width):
                                # Bounce: start moving left
                                m.d.sync += [
                                    direction.eq(1),
                                    brick_pos.eq(brick_pos - 1),
                                ]
                            with m.Else():
                                m.d.sync += brick_pos.eq(brick_pos + 1)
                        with m.Else():
                            # Moving left
                            with m.If(brick_pos == 0):
                                # Bounce: start moving right
                                m.d.sync += [
                                    direction.eq(0),
                                    brick_pos.eq(brick_pos + 1),
                                ]
                            with m.Else():
                                m.d.sync += brick_pos.eq(brick_pos - 1)
                        # Redraw after move
                        m.d.sync += [draw_x.eq(0), draw_y.eq(0)]
                        m.next = "DRAW"
                    with m.Else():
                        m.d.sync += speed_counter.eq(speed_counter + 1)

        # -- FREEZE ----------------------------------------------------
        # Button was pressed: compute overlap, freeze the row
        with m.State("FREEZE"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                with m.If(current_row == 0):
                    # First row: no overlap check, just freeze as-is
                    for i in range(height):
                        with m.If(current_row == i):
                            m.d.sync += row_mask[i].eq(cur_brick_mask)

                    m.d.sync += [
                        current_row.eq(1),
                        brick_pos.eq(0),
                        direction.eq(0),
                        speed_counter.eq(0),
                        # Speed up slightly for next row
                        speed_limit.eq(speed_limit - 1),
                    ]
                    # Clamp speed_limit to minimum of 1
                    with m.If(speed_limit <= 1):
                        m.d.sync += speed_limit.eq(1)
                    m.d.sync += [draw_x.eq(0), draw_y.eq(0)]
                    m.next = "DRAW"
                with m.Else():
                    # Compute overlap with row below
                    m.next = "COMPUTE_OVERLAP"

        # -- COMPUTE_OVERLAP -------------------------------------------
        with m.State("COMPUTE_OVERLAP"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                # Read the row below
                m.d.comb += old_mask.eq(0)
                for i in range(height):
                    with m.If(current_row - 1 == i):
                        m.d.comb += old_mask.eq(row_mask[i])

                # Overlap = bits present in BOTH current brick AND row below
                m.d.comb += overlap.eq(cur_brick_mask & old_mask)

                with m.If(overlap == 0):
                    # No overlap at all -> game over
                    m.d.sync += flash_timer.eq(0)
                    m.next = "GAME_OVER"
                with m.Else():
                    # Freeze only the overlapping part
                    for i in range(height):
                        with m.If(current_row == i):
                            m.d.sync += row_mask[i].eq(overlap)

                    # Compute new brick width and position from overlap mask
                    # Find lowest set bit (new position) and count bits (new width)
                    # We do this with a priority encoder + popcount
                    new_pos = Signal(range(width), name="new_pos")
                    new_w = Signal(range(width + 1), name="new_w")

                    # Lowest set bit = new position
                    m.d.comb += new_pos.eq(0)
                    for bit in range(width - 1, -1, -1):
                        with m.If(overlap[bit]):
                            m.d.comb += new_pos.eq(bit)

                    # Popcount = new width (sum of set bits in overlap)
                    popcount_expr = overlap[0]
                    for bit in range(1, width):
                        popcount_expr = popcount_expr + overlap[bit]
                    m.d.comb += new_w.eq(popcount_expr)

                    next_row = Signal(range(height + 1), name="next_row")
                    m.d.comb += next_row.eq(current_row + 1)

                    target_height = Signal(range(height + 1), name="target_height")
                    m.d.comb += target_height.eq(Mux(cheat_en, 8, height))

                    with m.If(next_row >= target_height):
                        # Stacked all required rows -> win!
                        m.d.sync += [
                            current_row.eq(next_row),
                            flash_timer.eq(0),
                            win_score.eq(new_w),  # capture score
                        ]
                        m.next = "WIN"
                    with m.Else():
                        m.d.sync += [
                            current_row.eq(next_row),
                            brick_pos.eq(new_pos),
                            brick_width.eq(new_w),
                            direction.eq(0),
                            speed_counter.eq(0),
                        ]
                        # Speed up: reduce speed_limit, clamp to 1
                        with m.If(speed_limit <= 1):
                            m.d.sync += speed_limit.eq(1)
                        with m.Else():
                            m.d.sync += speed_limit.eq(speed_limit - 1)

                        m.d.sync += [draw_x.eq(0), draw_y.eq(0)]
                        m.next = "DRAW"

        # -- GAME_OVER -------------------------------------------------
        # Flash the frozen rows red/off for a bit, then restart
        with m.State("GAME_OVER"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += flash_timer.eq(flash_timer + 1)

                # Flash: draw everything red or black based on timer bit 22 (~4 Hz)
                flash_on = Signal(name="flash_on")
                m.d.comb += flash_on.eq(flash_timer[22])

                pixel_r2 = Signal(8, name="pixel_r2")
                m.d.comb += pixel_r2.eq(Mux(flash_on, 0xFF, 0))

                frozen_bit2 = Signal(name="frozen_bit2")
                m.d.comb += frozen_bit2.eq(0)
                for i in range(height):
                    with m.If(draw_y == i):
                        m.d.comb += frozen_bit2.eq(row_mask[i].bit_select(draw_x, 1))

                with m.If(frozen_bit2):
                    m.d.sync += writer.set_led(x=draw_x, y=draw_y, r=pixel_r2, g=0, b=0)
                with m.Else():
                    m.d.sync += writer.set_led(x=draw_x, y=draw_y, r=0, g=0, b=0)

                # Scan all pixels
                with m.If(draw_x == width - 1):
                    m.d.sync += draw_x.eq(0)
                    with m.If(draw_y == height - 1):
                        m.d.sync += draw_y.eq(0)
                        # After ~4 seconds, restart
                        with m.If(flash_timer[25]):
                            m.next = "IDLE"
                    with m.Else():
                        m.d.sync += draw_y.eq(draw_y + 1)
                with m.Else():
                    m.d.sync += draw_x.eq(draw_x + 1)

        # -- WIN -------------------------------------------------------
        # Rainbow flash celebration, then restart
        with m.State("WIN"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += flash_timer.eq(flash_timer + 1)

                # Draw rows in their colors, but pulse brightness using timer
                frozen_bit3 = Signal(name="frozen_bit3")
                m.d.comb += frozen_bit3.eq(0)
                for i in range(height):
                    with m.If(draw_y == i):
                        m.d.comb += frozen_bit3.eq(row_mask[i].bit_select(draw_x, 1))

                win_r = Signal(8, name="win_r")
                win_g = Signal(8, name="win_g")
                win_b = Signal(8, name="win_b")
                m.d.comb += [win_r.eq(0), win_g.eq(0), win_b.eq(0)]

                # Cycle colors based on flash_timer to animate
                with m.If(frozen_bit3):
                    for i in range(height):
                        with m.If(draw_y == i):
                            r, g, b = ROW_COLORS[i]
                            # Blink between row color and white
                            with m.If(flash_timer[22]):
                                m.d.comb += [win_r.eq(r), win_g.eq(g), win_b.eq(b)]
                            with m.Else():
                                m.d.comb += [win_r.eq(0xFF), win_g.eq(0xFF), win_b.eq(0xFF)]

                m.d.sync += writer.set_led(x=draw_x, y=draw_y, r=win_r, g=win_g, b=win_b)

                # Scan all pixels
                with m.If(draw_x == width - 1):
                    m.d.sync += draw_x.eq(0)
                    with m.If(draw_y == height - 1):
                        m.d.sync += draw_y.eq(0)
                        with m.If(flash_timer[25]):
                            # White blinking done -> rainbow flag
                            m.d.sync += [
                                flash_timer.eq(0),
                                draw_x.eq(0),
                                draw_y.eq(0),
                            ]
                            m.next = "WIN_RAINBOW"
                    with m.Else():
                        m.d.sync += draw_y.eq(draw_y + 1)
                with m.Else():
                    m.d.sync += draw_x.eq(draw_x + 1)

        # -- WIN_RAINBOW -----------------------------------------------
        # Wave a rainbow flag for ~10 seconds
        with m.State("WIN_RAINBOW"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += flash_timer.eq(flash_timer + 1)

                # Compute rainbow hue from row + column wave + time
                rb_hue = Signal(8, name="rb_hue")
                m.d.comb += rb_hue.eq(
                    (draw_y << 4) + (draw_x << 2) + flash_timer[17:25]
                )

                # HSV-to-RGB (6-segment rainbow)
                rb_hue_x6 = Signal(11, name="rb_hue_x6")
                m.d.comb += rb_hue_x6.eq(rb_hue * 6)

                rb_seg = Signal(3, name="rb_seg")
                m.d.comb += rb_seg.eq(rb_hue_x6[8:11])

                rb_pos = Signal(8, name="rb_pos")
                m.d.comb += rb_pos.eq(rb_hue_x6[0:8])

                rb_r = Signal(8, name="rb_r")
                rb_g = Signal(8, name="rb_g")
                rb_b = Signal(8, name="rb_b")
                m.d.comb += [rb_r.eq(0), rb_g.eq(0), rb_b.eq(0)]

                with m.Switch(rb_seg):
                    with m.Case(0):  # Red -> Yellow
                        m.d.comb += [rb_r.eq(255), rb_g.eq(rb_pos), rb_b.eq(0)]
                    with m.Case(1):  # Yellow -> Green
                        m.d.comb += [rb_r.eq(255 - rb_pos), rb_g.eq(255), rb_b.eq(0)]
                    with m.Case(2):  # Green -> Cyan
                        m.d.comb += [rb_r.eq(0), rb_g.eq(255), rb_b.eq(rb_pos)]
                    with m.Case(3):  # Cyan -> Blue
                        m.d.comb += [rb_r.eq(0), rb_g.eq(255 - rb_pos), rb_b.eq(255)]
                    with m.Case(4):  # Blue -> Magenta
                        m.d.comb += [rb_r.eq(rb_pos), rb_g.eq(0), rb_b.eq(255)]
                    with m.Case(5):  # Magenta -> Red
                        m.d.comb += [rb_r.eq(255), rb_g.eq(0), rb_b.eq(255 - rb_pos)]

                m.d.sync += writer.set_led(
                    x=draw_x, y=draw_y, r=rb_r, g=rb_g, b=rb_b
                )

                # Scan all pixels
                with m.If(draw_x == width - 1):
                    m.d.sync += draw_x.eq(0)
                    with m.If(draw_y == height - 1):
                        m.d.sync += draw_y.eq(0)
                        # Check if 10 seconds elapsed
                        with m.If(flash_timer >= RAINBOW_DURATION):
                            m.d.sync += [
                                flash_timer.eq(0),
                                draw_x.eq(0),
                                draw_y.eq(0),
                            ]
                            m.next = "WIN_SCORE_CLEAR"
                    with m.Else():
                        m.d.sync += draw_y.eq(draw_y + 1)
                with m.Else():
                    m.d.sync += draw_x.eq(draw_x + 1)

        # -- WIN_SCORE_CLEAR -------------------------------------------
        # Clear display before rendering score
        with m.State("WIN_SCORE_CLEAR"):
            m.d.comb += font_active.eq(1)
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += writer.set_led(
                    x=draw_x, y=draw_y, r=0, g=0, b=0
                )
                with m.If(draw_x == width - 1):
                    m.d.sync += draw_x.eq(0)
                    with m.If(draw_y == height - 1):
                        m.d.sync += draw_y.eq(0)
                        m.next = "WIN_SCORE_RENDER"
                    with m.Else():
                        m.d.sync += draw_y.eq(draw_y + 1)
                with m.Else():
                    m.d.sync += draw_x.eq(draw_x + 1)

        # -- WIN_SCORE_RENDER ------------------------------------------
        # Request font pattern for score digit ('0' + win_score)
        with m.State("WIN_SCORE_RENDER"):
            m.d.comb += font_active.eq(1)
            with m.If(~enable):
                m.d.sync += font_render_enable.eq(0)
                m.next = "IDLE"
            with m.Else():
                m.d.sync += [
                    font_char_code.eq(0x30 + win_score),  # ASCII '0' + score
                    font_render_enable.eq(1),
                ]
                m.next = "WIN_SCORE_WAIT"

        # -- WIN_SCORE_WAIT --------------------------------------------
        # Wait for font renderer to return segment pattern
        with m.State("WIN_SCORE_WAIT"):
            m.d.comb += font_active.eq(1)
            with m.If(~enable):
                m.d.sync += font_render_enable.eq(0)
                m.next = "IDLE"
            with m.Else():
                with m.If(font_render_done):
                    m.d.sync += [
                        font_render_enable.eq(0),
                        score_segment.eq(font_segment_pattern),
                        score_disp_x.eq(0),
                        score_disp_y.eq(0),
                    ]
                    m.next = "WIN_SCORE_DRAW"

        # -- WIN_SCORE_DRAW --------------------------------------------
        # Render score digit segments to display
        with m.State("WIN_SCORE_DRAW"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                seg_bit = Signal(name="seg_bit")
                # Font format is 8 bytes per char (8 cols).
                # So bit index = (score_disp_y * 8) + score_disp_x. Pure wiring.
                bit_idx = Signal(6, name="bit_idx")
                m.d.comb += bit_idx.eq(Cat(score_disp_x[:3], score_disp_y[:3]))
                
                m.d.comb += seg_bit.eq(
                    score_segment.bit_select(bit_idx, 1)
                )

                # Render centered 8x8 on 8x16 display
                display_x = Signal(range(width), name="display_x")
                display_y = Signal(range(height), name="display_y")
                m.d.comb += [
                    display_x.eq(7 - score_disp_x),
                    display_y.eq(score_disp_y + 4)
                ]

                with m.If(seg_bit):
                    m.d.sync += writer.set_led(
                        x=display_x, y=display_y,
                        r=0xFF, g=0xFF, b=0xFF
                    )
                with m.Else():
                    m.d.sync += writer.set_led(
                        x=display_x, y=display_y,
                        r=0, g=0, b=0
                    )

                with m.If(score_disp_y == 7):
                    m.d.sync += score_disp_y.eq(0)
                    with m.If(score_disp_x == width - 1):
                        # All segments drawn, show score
                        m.d.sync += flash_timer.eq(0)
                        m.next = "WIN_SCORE_SHOW"
                    with m.Else():
                        m.d.sync += score_disp_x.eq(score_disp_x + 1)
                with m.Else():
                    m.d.sync += score_disp_y.eq(score_disp_y + 1)

        # -- WIN_SCORE_SHOW --------------------------------------------
        # Display score for a few seconds, then restart
        with m.State("WIN_SCORE_SHOW"):
            with m.If(~enable):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += flash_timer.eq(flash_timer + 1)
                with m.If(flash_timer >= SCORE_DISPLAY_TIME):
                    m.next = "IDLE"

    # Font active default (0 unless overridden in WIN_SCORE_* states)
    # Already set via comb in the states above; Amaranth defaults undriven comb to 0.

    # --- ports ---
    ports = [
        enable, short_press, cheat_en,
        font_char_code, font_render_enable, font_render_done,
        font_segment_pattern, font_active,
    ] + writer.signals

    return m, ports


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 src/stacker.py path/to/output.v")
        sys.exit(1)

    out = sys.argv[1]
    m, ports = make_stacker(width=8, height=16)

    v = verilog.convert(m, name="stacker_module", ports=ports)

    with open(out, "w") as f:
        f.write(v)

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
