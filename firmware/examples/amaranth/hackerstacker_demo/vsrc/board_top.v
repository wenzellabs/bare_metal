// Top module for bare_metal (iCE40UP5K-SG48) - hacker stacker demo
// - SK9822 LED controller with 8x16 framebuffer
// - Button handler with mode switching
// - Multi-client SPI flash controller
// - hackerstacker game, nick, pattern, rainbow, and image display modules

module top(
    input clk_12M,// 12MHz oscillator
    // buttons
    input btn_ok,           // Button
    input btn_up,           // Up button (brightness+)
    input btn_down,         // Down button (brightness-)
    // LED matrix
    output led_di,          // SK9822 data (MOSI)
    output led_ci,          // SK9822 clock (SCLK)
    output led_power_on,    // enable RGB LED power
    // Debug LEDs (active-high white LEDs)
    output led_pinky,       // MSB of mode
    output led_middle,
    output led_index,       // LSB of mode
    // SPI Flash pins
    output spi_csn_flash,   // Flash chip select (F7)
    output spi_clk,         // Flash clock (G7)
    output spi_mosi,        // Flash MOSI (G6)
    input spi_miso,         // Flash MISO (H7)
    output spi_wp,          // Flash WP# (active low) - must be HIGH
    output spi_hold,        // Flash HOLD# (active low) - must be HIGH
);
    
    // Enable LED power at start
    assign led_power_on = 1'b1;
    
    // SPI flash: deassert WP# and HOLD# (active-low, drive HIGH to disable)
    assign spi_wp   = 1'b1;
    assign spi_hold = 1'b1;
    
    // Flash debug on white LEDs (active-low: 0=on, 1=off)
    // Capture first 3 bytes read from nick's flash client
    // Expected: 0x4E ('N'), 0x00, 0x00 from nick header at 0x0A0000
    // Show byte 0 on LEDs: led_pinky=bit2, led_middle=bit1, led_index=bit0
    reg [7:0] dbg_byte0;
    reg dbg_captured;
    always @(posedge clk_12M) begin
        if (nick_flash_read_valid & ~dbg_captured) begin
            dbg_byte0 <= nick_flash_read_data;
            dbg_captured <= 1'b1;
        end
    end
    // 0x4E = 0100_1110 -> bits[2:0] = 110 -> pinky=1(off), middle=on, index=off
    // 0xFF = all 1s -> all off (all LEDs dark)
    // 0x00 = all 0s -> all on
    assign led_index  = dbg_captured ? dbg_byte0[0] : 1'b1;  // off until captured
    assign led_middle = dbg_captured ? dbg_byte0[1] : 1'b1;
    assign led_pinky  = dbg_captured ? dbg_byte0[2] : 1'b1;
    
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

    initial begin
        brightness_reg = 5'd1;
        up_stable = 1'b0;
        dn_stable = 1'b0;
        up_prev = 1'b0;
        dn_prev = 1'b0;
        brightness_wr = 1'b0;
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
        if (up_press && brightness_reg < 5'd9) begin
            brightness_reg <= brightness_reg + 1;
            brightness_wr <= 1'b1;
        end
        if (dn_press && brightness_reg > 5'd1) begin
            brightness_reg <= brightness_reg - 1;
            brightness_wr <= 1'b1;
        end
    end
    
    // Main menu state machine
    wire [2:0] current_mode;  // 0=stacker, 1=nick, 2=image, 3=pattern, 4=rainbow
    wire stacker_enable;      // Enable signal for stacker module
    wire nick_enable;         // Enable signal for nick module
    wire pattern_enable;      // Enable signal for pattern module
    wire rainbow_enable;      // Enable signal for rainbow module
    wire image_enable;        // Enable signal for image module
    wire [3:0] pattern_display; // Display mode selector (0-9)
    
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

    // Nick flash interface
    wire nick_flash_read_en;
    wire [23:0] nick_flash_read_addr;
    wire [7:0] nick_flash_read_data;
    wire nick_flash_read_valid;
    wire nick_flash_busy;
    wire nick_flash_ready;
    
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
    
    // Font renderer signals (shared between nick and stacker modules)
    // Nick's font outputs (renamed to allow muxing)
    wire [7:0] nick_font_char_code;
    wire nick_font_render_enable;
    // Stacker's font outputs
    wire [7:0] stacker_font_char_code;
    wire stacker_font_render_enable;
    // Muxed font_render inputs: stacker takes priority when font_active
    wire [7:0] font_char_code = stacker_font_active ? stacker_font_char_code : nick_font_char_code;
    wire font_render_enable = stacker_font_active ? stacker_font_render_enable : nick_font_render_enable;
    // Shared outputs from font_render (go to both modules)
    wire font_render_done;
    wire font_busy;
    wire [15:0] font_segment_pattern;
    wire font_flash_read_en;
    wire [23:0] font_flash_read_addr;
    wire font_flash_read_valid;
    wire font_flash_busy;
    wire font_flash_ready;
    
    font_render u_font_render (
        .clk(clk_12M),
        .rst(1'b0),
        .char_code(font_char_code),
        .render_enable(font_render_enable),
        .render_done(font_render_done),
        .busy(font_busy),
        .segment_pattern(font_segment_pattern),
        .flash_read_en(font_flash_read_en),
        .flash_read_addr(font_flash_read_addr),
        .flash_read_data(nick_flash_read_data),  // Shares nick flash data bus
        .flash_read_valid(font_flash_read_valid),
        .flash_busy(font_flash_busy),
        .flash_ready(font_flash_ready)
    );
    
    nick_module u_nick (
        .clk(clk_12M),
        .rst(1'b0),
        .enable(nick_enable),
        .short_press(short_press),
        // Font renderer interface (control signals) - nick's outputs go through mux
        .font_char_code(nick_font_char_code),
        .font_render_enable(nick_font_render_enable),
        .font_render_done(font_render_done),
        .font_busy(font_busy),
        .font_segment_pattern(font_segment_pattern),
        // Font renderer flash requests (inputs from font_render)
        .font_flash_read_en(font_flash_read_en),
        .font_flash_read_addr(font_flash_read_addr),
        .font_flash_read_valid(font_flash_read_valid),
        .font_flash_busy(font_flash_busy),
        .font_flash_ready(font_flash_ready),
        // Flash interface (nick's output to flash controller, muxes nick + font requests)
        .flash_read_en(nick_flash_read_en),
        .flash_read_addr(nick_flash_read_addr),
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
        .nick_wr_b(nick_wr_b),
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
    assign wr_r  = (current_mode == 3'd0) ? stacker_wr_r :
                   (current_mode == 3'd1) ? nick_wr_r :
                   (current_mode == 3'd2) ? image_wr_r :
                   (current_mode == 3'd3) ? pattern_wr_r :
                   rainbow_wr_r;
    assign wr_g  = (current_mode == 3'd0) ? stacker_wr_g :
                   (current_mode == 3'd1) ? nick_wr_g :
                   (current_mode == 3'd2) ? image_wr_g :
                   (current_mode == 3'd3) ? pattern_wr_g :
                   rainbow_wr_g;
    assign wr_b  = (current_mode == 3'd0) ? stacker_wr_b :
                   (current_mode == 3'd1) ? nick_wr_b :
                   (current_mode == 3'd2) ? image_wr_b :
                   (current_mode == 3'd3) ? pattern_wr_b :
                   rainbow_wr_b;
    
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
        .wr_brightness(brightness_reg)
    );
    
endmodule
