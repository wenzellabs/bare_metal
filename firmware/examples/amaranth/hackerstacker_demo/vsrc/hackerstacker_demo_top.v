// Top module for bare_metal (iCE40UP5K-SG48) - hacker stacker demo
// - SK9822 LED controller with 8x16 framebuffer
// - Button handler with mode switching
// - Multi-client SPI flash controller
// - hackerstacker game, nick, pattern, rainbow, and image display modules

module hackerstacker_demo(
    input clk_12M,// 12MHz oscillator
    // buttons
    input btn_ok,           // Button
    input btn_up,           // Up button (brightness+)
    input btn_down,         // Down button (brightness-)
    input btn_left,         // Left button (scroll mode)
    input btn_right,        // Right button (font switch)
    // LED matrix
    output led_di,          // SK9822 data (MOSI)
    output led_ci,          // SK9822 clock (SCLK)
    output led_power_on,    // enable RGB LED power
    // Debug LEDs (active-high white LEDs)
    output led_pinky,       // pinky finger
    output led_middle,      // Ortsteil pommesgabel mitte
    output led_index,       // index finger
    // SPI Flash pins
    output spi_csn_flash,   // Flash chip select (F7)
    output spi_clk,         // Flash clock (G7)
    output spi_mosi,        // Flash MOSI (G6)
    input spi_miso,         // Flash MISO (H7)
    output spi_wp,          // Flash WP# (active low) - must be HIGH
    output spi_hold,        // Flash HOLD# (active low) - must be HIGH
    // PMOD pins for button/switch testing
    input pmod_a_n,
    input pmod_a_p,
    input pmod_2,
    input pmod_8,
    input pmod_b_p,
    input pmod_b_n,
    input pmod_4,
    input pmod_10
);
    
    // Enable LED power at start
    assign led_power_on = 1'b1;
    
    // SPI flash: deassert WP# and HOLD# (active-low, drive HIGH to disable)
    assign spi_wp   = 1'b1;
    assign spi_hold = 1'b1;
    
    // 0x4E = 0100_1110 -> bits[2:0] = 110 -> pinky=1(off), middle=on, index=off
    // 0xFF = all 1s -> all off (all LEDs dark)
    // 0x00 = all 0s -> all on
    
    // Button handler signals
    wire short_press, long_press;
    
    button_handler u_button (
        .clk(clk_12M),
        .rst(1'b0),
        .btn_in(btn_ok),
        .short_press(short_press),
        .long_press(long_press)
    );
    
    // Brightness control via btn_up / btn_down
    // Simple debounce + edge detect for each button
    reg [17:0] up_deb_cnt, dn_deb_cnt;
    reg up_stable, dn_stable, up_prev, dn_prev;
    wire up_press = up_stable & ~up_prev;
    wire dn_press = dn_stable & ~dn_prev;
    reg [4:0] brightness_reg;  // 1-31, reset to 1
    reg brightness_wr;
    reg [2:0] extra_dim_reg; // 0-7 extra right-shift dimming
    reg extra_dim_wr;

    initial begin
        brightness_reg = 5'd1;
        extra_dim_reg = 3'd0;
        up_stable = 1'b1;   // Match active-low idle state (buttons have pull-ups)
        dn_stable = 1'b1;
        up_prev = 1'b1;
        dn_prev = 1'b1;
        brightness_wr = 1'b0;
        extra_dim_wr = 1'b0;
    end

    always @(posedge clk_12M) begin
        // Debounce btn_up (~21ms at 12MHz)
        if (btn_up != up_stable) begin
            up_deb_cnt <= up_deb_cnt + 1;
            if (&up_deb_cnt) up_stable <= btn_up;
        end else
            up_deb_cnt <= 0;

        // Debounce btn_down
        if (btn_down != dn_stable) begin
            dn_deb_cnt <= dn_deb_cnt + 1;
            if (&dn_deb_cnt) dn_stable <= btn_down;
        end else
            dn_deb_cnt <= 0;

        up_prev <= up_stable;
        dn_prev <= dn_stable;

        brightness_wr <= 1'b0;
        extra_dim_wr <= 1'b0;
        if (up_press) begin
            // If extra_dim is active, decrease it first (brighten via filter)
            if (extra_dim_reg > 3'd0) begin
                extra_dim_reg <= extra_dim_reg - 1;
                extra_dim_wr <= 1'b1;
            end else if (brightness_reg < 5'd5) begin
                // Increase global brightness up to 5
                brightness_reg <= brightness_reg + 1;
                brightness_wr <= 1'b1;
            end
        end

        if (dn_press) begin
            // First decrease global brightness down to 1
            if (brightness_reg > 5'd1) begin
                brightness_reg <= brightness_reg - 1;
                brightness_wr <= 1'b1;
            end else if (extra_dim_reg < 3'd7) begin
                // If at minimum brightness, increase extra_dim (further dimming)
                extra_dim_reg <= extra_dim_reg + 1;
                extra_dim_wr <= 1'b1;
            end
        end
    end

    // Debounce btn_left and btn_right (for nick font/mode switching)
    reg [17:0] left_deb_cnt, right_deb_cnt;
    reg left_stable, right_stable, left_prev, right_prev;
    wire left_press = left_stable & ~left_prev;
    wire right_press = right_stable & ~right_prev;

    initial begin
        left_stable = 1'b1;
        right_stable = 1'b1;
        left_prev = 1'b1;
        right_prev = 1'b1;
    end

    always @(posedge clk_12M) begin
        if (btn_left != left_stable) begin
            left_deb_cnt <= left_deb_cnt + 1;
            if (&left_deb_cnt) left_stable <= btn_left;
        end else
            left_deb_cnt <= 0;

        if (btn_right != right_stable) begin
            right_deb_cnt <= right_deb_cnt + 1;
            if (&right_deb_cnt) right_stable <= btn_right;
        end else
            right_deb_cnt <= 0;

        left_prev <= left_stable;
        right_prev <= right_stable;
    end
    
    // Main menu state machine
    wire [2:0] current_mode;  // 0=stacker, 1=nick, 2=image, 3=pattern, 4=rainbow
    wire stacker_enable;      // Enable signal for stacker module
    wire nick_enable;         // Enable signal for nick module
    wire pattern_enable;      // Enable signal for pattern module
    wire rainbow_enable;      // Enable signal for rainbow module
    wire image_enable;        // Enable signal for image module
    wire [4:0] pattern_display; // Display mode selector (0-18)
    
    mainmenu u_mainmenu (
        .clk(clk_12M),
        .rst(1'b0),
        .short_press(short_press),
        .long_press(long_press),
        .current_mode(current_mode),
        .stacker_enable(stacker_enable),
        .nick_enable(nick_enable),
        .pattern_enable(pattern_enable),
        .rainbow_enable(rainbow_enable),
        .image_enable(image_enable),
        .clock_display(pattern_display)
    );
    
    // Multi-client flash controller
    // client_active: one-hot encoding {2'b00, image, nick}
    // Nick's flash client is also enabled when stacker needs font rendering
    wire stacker_font_active;  // declared here, driven by stacker_module
    wire [3:0] client_active = {2'b00, image_enable, nick_enable | stacker_font_active};

    // Nick's own flash signals (output from nick module)
    wire nick_own_read_en;
    wire [23:0] nick_own_read_addr;
    // Shared flash responses (from flash controller, go to nick AND font_render)
    wire [7:0] nick_flash_read_data;
    wire nick_flash_read_valid;
    wire nick_flash_busy;
    wire nick_flash_ready;
    // Font render flash signals (for stacker score display)
    wire font_flash_read_en;
    wire [23:0] font_flash_read_addr;
    // External mux: font_render takes flash when stacker_font_active
    wire nick_flash_read_en = stacker_font_active ? font_flash_read_en : nick_own_read_en;
    wire [23:0] nick_flash_read_addr = stacker_font_active ? font_flash_read_addr : nick_own_read_addr;
    
    // Image flash interface
    wire image_flash_read_en;
    wire [23:0] image_flash_read_addr;
    wire [7:0] image_flash_read_data;
    wire image_flash_read_valid;
    wire image_flash_busy;
    wire image_flash_ready;
    
    flash_controller u_flash (
        .clk(clk_12M),
        .rst(1'b0),
        // Multi-client interface
        .client_active(client_active),
        // Nick client
        .nick_flash_read_en(nick_flash_read_en),
        .nick_flash_read_addr(nick_flash_read_addr),
        .nick_flash_read_data(nick_flash_read_data),
        .nick_flash_read_valid(nick_flash_read_valid),
        .nick_flash_busy(nick_flash_busy),
        .nick_flash_ready(nick_flash_ready),
        // Image client
        .image_flash_read_en(image_flash_read_en),
        .image_flash_read_addr(image_flash_read_addr),
        .image_flash_read_data(image_flash_read_data),
        .image_flash_read_valid(image_flash_read_valid),
        .image_flash_busy(image_flash_busy),
        .image_flash_ready(image_flash_ready),
        // Legacy write/erase
        .write_en(1'b0),
        .write_addr(24'h0),
        .write_data(8'h0),
        .write_done(),
        .erase_en(1'b0),
        .erase_addr(24'h0),
        .erase_done(),
        // SPI pins
        .flash_cs(spi_csn_flash),
        .flash_clk(spi_clk),
        .flash_mosi(spi_mosi),
        .flash_miso(spi_miso)
    );
    
    // Nick module write signals
    wire nick_wr_en;
    wire [2:0] nick_wr_x;
    wire [3:0] nick_wr_y;
    wire [7:0] nick_wr_r, nick_wr_g, nick_wr_b;
    
    // Font renderer signals (used by stacker only; nick uses pre-rendered bitmaps)
    wire [7:0] stacker_font_char_code;
    wire stacker_font_render_enable;
    // Shared outputs from font_render
    wire font_render_done;
    wire font_busy;
    wire [63:0] font_segment_pattern;
    
    font_render u_font_render (
        .clk(clk_12M),
        .rst(1'b0),
        .char_code(stacker_font_char_code),
        .render_enable(stacker_font_render_enable),
        .render_done(font_render_done),
        .busy(font_busy),
        .segment_pattern(font_segment_pattern),
        .flash_read_en(font_flash_read_en),
        .flash_read_addr(font_flash_read_addr),
        .flash_read_data(nick_flash_read_data),
        .flash_read_valid(nick_flash_read_valid),
        .flash_busy(nick_flash_busy),
        .flash_ready(nick_flash_ready)
    );
    
    nick_module u_nick (
        .clk(clk_12M),
        .rst(1'b0),
        .enable(nick_enable),
        .short_press(short_press),
        .btn_right(right_press),
        .btn_left(left_press),
        // Flash interface (nick's own requests; muxed externally with font_render)
        .flash_read_en(nick_own_read_en),
        .flash_read_addr(nick_own_read_addr),
        .flash_read_data(nick_flash_read_data),
        .flash_read_valid(nick_flash_read_valid),
        .flash_busy(nick_flash_busy),
        .flash_ready(nick_flash_ready),
        // LED write interface
        .nick_wr_en(nick_wr_en),
        .nick_wr_x(nick_wr_x),
        .nick_wr_y(nick_wr_y),
        .nick_wr_r(nick_wr_r),
        .nick_wr_g(nick_wr_g),
        .nick_wr_b(nick_wr_b)
    );

    // Stacker game module write signals
    wire stacker_wr_en;
    wire [2:0] stacker_wr_x;
    wire [3:0] stacker_wr_y;
    wire [7:0] stacker_wr_r, stacker_wr_g, stacker_wr_b;

    stacker_module u_stacker (
        .clk(clk_12M),                                                                                                  
        .rst(1'b0),
        .enable(stacker_enable),
        .short_press(short_press),
        .cheat_en(pmod_in_state == 8'b10110111), // Backdoor: Win at row 8 when PMOD pins for idx 3 and 6 are LOW, others HIGH
        // Font renderer interface (for score display)
        .font_char_code(stacker_font_char_code),
        .font_render_enable(stacker_font_render_enable),
        .font_render_done(font_render_done),
        .font_segment_pattern(font_segment_pattern),
        .font_active(stacker_font_active),
        // LED write interface
        .stacker_wr_en(stacker_wr_en),
        .stacker_wr_x(stacker_wr_x),
        .stacker_wr_y(stacker_wr_y),
        .stacker_wr_r(stacker_wr_r),
        .stacker_wr_g(stacker_wr_g),
        .stacker_wr_b(stacker_wr_b)
    );

    // Pattern module write signals
    wire pattern_wr_en;
    wire [2:0] pattern_wr_x;
    wire [3:0] pattern_wr_y;
    wire [7:0] pattern_wr_r, pattern_wr_g, pattern_wr_b;
    
    pattern_module u_pattern (
        .clk(clk_12M),
        .rst(1'b0),
        .enable(pattern_enable),
        .display_mode(pattern_display),
        .pattern_wr_en(pattern_wr_en),
        .pattern_wr_x(pattern_wr_x),
        .pattern_wr_y(pattern_wr_y),
        .pattern_wr_r(pattern_wr_r),
        .pattern_wr_g(pattern_wr_g),
        .pattern_wr_b(pattern_wr_b)
    );
    
    // Rainbow module write signals
    wire rainbow_wr_en;
    wire [2:0] rainbow_wr_x;
    wire [3:0] rainbow_wr_y;
    wire [7:0] rainbow_wr_r, rainbow_wr_g, rainbow_wr_b;
    
    rainbow_module u_rainbow (
        .clk(clk_12M),
        .rst(1'b0),
        .enable(rainbow_enable),
        .short_press(short_press),
        .wr_en(rainbow_wr_en),
        .wr_x(rainbow_wr_x),
        .wr_y(rainbow_wr_y),
        .wr_r(rainbow_wr_r),
        .wr_g(rainbow_wr_g),
        .wr_b(rainbow_wr_b)
    );
    
    // Image module write signals
    wire image_wr_en;
    wire [2:0] image_wr_x;
    wire [3:0] image_wr_y;
    wire [7:0] image_wr_r, image_wr_g, image_wr_b;
    
    image_module u_image (
        .clk(clk_12M),
        .rst(1'b0),
        .enable(image_enable),
        .short_press(short_press),
        .flash_read_en(image_flash_read_en),
        .flash_read_addr(image_flash_read_addr),
        .flash_read_data(image_flash_read_data),
        .flash_read_valid(image_flash_read_valid),
        .flash_busy(image_flash_busy),
        .flash_ready(image_flash_ready),
        .image_wr_en(image_wr_en),
        .image_wr_x(image_wr_x),
        .image_wr_y(image_wr_y),
        .image_wr_r(image_wr_r),
        .image_wr_g(image_wr_g),
        .image_wr_b(image_wr_b)
    );
    
    // Multiplexer: select active module's write signals based on current_mode
    // Mode 0=nick, 1=pattern, 2=rainbow, 3=image
    wire wr_en;
    wire [2:0] wr_x;
    wire [3:0] wr_y;
    wire [7:0] wr_r, wr_g, wr_b;
    
    // Multiplex LED outputs based on current mode
    // Mode 0: stacker, Mode 1: nick, Mode 2: image, Mode 3: pattern, Mode 4: rainbow
    assign wr_en = (current_mode == 3'd0) ? stacker_wr_en :
                   (current_mode == 3'd1) ? nick_wr_en :
                   (current_mode == 3'd2) ? image_wr_en :
                   (current_mode == 3'd3) ? pattern_wr_en :
                   rainbow_wr_en;
    assign wr_x  = (current_mode == 3'd0) ? stacker_wr_x :
                   (current_mode == 3'd1) ? nick_wr_x :
                   (current_mode == 3'd2) ? image_wr_x :
                   (current_mode == 3'd3) ? pattern_wr_x :
                   rainbow_wr_x;
    assign wr_y  = (current_mode == 3'd0) ? stacker_wr_y :
                   (current_mode == 3'd1) ? nick_wr_y :
                   (current_mode == 3'd2) ? image_wr_y :
                   (current_mode == 3'd3) ? pattern_wr_y :
                   rainbow_wr_y;
    
    // Wire pre-mapped RGB data directly from modules that don't use color mapping
    wire [7:0] raw_wr_r  = (current_mode == 3'd0) ? stacker_wr_r :
                           (current_mode == 3'd1) ? nick_wr_r :
                           (current_mode == 3'd2) ? image_wr_r :
                           (current_mode == 3'd3) ? pattern_wr_r :
                           rainbow_wr_r;
    wire [7:0] raw_wr_g  = (current_mode == 3'd0) ? stacker_wr_g :
                           (current_mode == 3'd1) ? nick_wr_g :
                           (current_mode == 3'd2) ? image_wr_g :
                           (current_mode == 3'd3) ? pattern_wr_g :
                           rainbow_wr_g;
    wire [7:0] raw_wr_b  = (current_mode == 3'd0) ? stacker_wr_b :
                           (current_mode == 3'd1) ? nick_wr_b :
                           (current_mode == 3'd2) ? image_wr_b :
                           (current_mode == 3'd3) ? pattern_wr_b :
                           rainbow_wr_b;

    // Use raw data acting as the direct 'hue' input to the mapper in states 3 and 4 
    wire [7:0] mapper_hue = raw_wr_r; // Reusing Red bus line as hue data line

    // State 1: raw rgb, State 2: rainbow hue, State 3: trans hue 
    // pattern modes (0-1: checkerboards (raw), 18: knight tile (raw)) use raw directly via mode 1. 2-17 are either 2 or 3
    // rainbow mode (0-9). even modes trans, odd modes rainbow.
    wire is_rainbow_state = (current_mode == 3'd4);
    wire is_pattern_state = (current_mode == 3'd3);
    
    wire [1:0] mapper_mode = 
        (is_rainbow_state) ? ((pattern_display[0] == 1'b0) ? 2'd3 : 2'd2) :
        (is_pattern_state) ? (
            (pattern_display < 2 || pattern_display == 18) ? 2'd1 :
            (pattern_display[0] == 1'b0) ? 2'd3 : 2'd2
        ) : 2'd1; // Default passthrough

    color_mapper u_color_mapper (
        .hue(mapper_hue),
        .mode(mapper_mode),
        .raw_r(raw_wr_r),
        .raw_g(raw_wr_g),
        .raw_b(raw_wr_b),
        .rgb_r(wr_r),
        .rgb_g(wr_g),
        .rgb_b(wr_b)
    );
    
    // PMOD inputs state
    wire [7:0] pmod_in_state = {pmod_10, pmod_4, pmod_b_n, pmod_b_p, pmod_8, pmod_2, pmod_a_p, pmod_a_n};
    
    // Instantiate SK9822 controller with RAM framebuffer
    sk9822_controller u_sk9822 (
        .clk(clk_12M),
        .rst(1'b0),
        .led_data(led_di),
        .led_clk(led_ci),
        .wr_en(wr_en),
        .wr_x(wr_x),
        .wr_y(wr_y),
        .wr_r(wr_r),
        .wr_g(wr_g),
        .wr_b(wr_b),
        .wr_brightness_en(brightness_wr),
        .wr_brightness(brightness_reg),
        .wr_extra_dim_en(extra_dim_wr),
        .wr_extra_dim(extra_dim_reg)
    );
    
    // turn off white LEDs
    assign led_pinky = 1'b1;  // active-low, drive HIGH to turn off
    assign led_middle = 1'b1;
    assign led_index = 1'b1;

endmodule
