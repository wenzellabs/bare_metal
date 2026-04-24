module julia_top (
    input clk_12M,
    inout usbp,
    inout usbn,
    output usb_det,
    input btn_ok,
    input btn_up,
    input btn_down,
    input btn_left,
    input btn_right,
    output led_index,
    output led_middle,
    output led_pinky,
    output spi_mosi,
    input spi_miso,
    output spi_clk,
    output spi_csn_flash,
    output spi_wp,
    output spi_hold,
    output spi_csn_ram,
    output led_di,
    output led_ci,
    output led_power_on
);
    assign usb_det = 1'b0;
    assign led_index = 1'b1;
    assign led_middle = 1'b1;
    assign led_pinky = 1'b1;
    assign led_power_on = 1'b1;

    // SPI default idle states
    assign spi_csn_ram = 1'b1;
    assign spi_csn_flash = 1'b1;
    assign spi_wp = 1'b1;
    assign spi_hold = 1'b1;
    assign spi_clk = 1'b0;
    assign spi_mosi = 1'b0;

    // -- Submodules --
    reg [3:0] wr_x;
    reg [3:0] wr_y;
    reg [7:0] wr_r, wr_g, wr_b;
    reg wr_en;

    sk9822_controller display (
        .clk(clk_12M),
        .rst(1'b0),
        .wr_x(wr_x),
        .wr_y(wr_y),
        .wr_r(wr_r),
        .wr_g(wr_g),
        .wr_b(wr_b),
        .wr_en(wr_en),
        .led_data(led_di),
        .led_clk(led_ci)
    );

    wire done;
    wire p_valid;
    wire [5:0] iter;
    wire [3:0] p_x;
    wire [2:0] p_y;

    reg start_julia;
    reg signed [15:0] c_x = 16'hF99A; // -0.8
    reg signed [15:0] c_y = 16'h0140; // +0.156
    reg signed [15:0] zoom_x = 16'h8000;
    reg signed [15:0] zoom_y = 16'hc000;
    reg signed [15:0] delta_x = 16'h0010;
    reg signed [15:0] delta_y = 16'h0010;

    // Zooming targets
    reg signed [15:0] center_x = 16'h0000;
    reg signed [15:0] center_y = 16'h0000;
    reg signed [15:0] target_x = 16'h0000;
    reg signed [15:0] target_y = 16'h0000;
    
    localparam STATE_ZOOM_IN  = 2'd0;
    localparam STATE_ZOOM_OUT = 2'd1;
    localparam STATE_PAN      = 2'd2;
    reg [1:0] auto_state = STATE_ZOOM_OUT;
    reg [15:0] lfsr = 16'hACE1; // Random number generator

    reg [15:0] total_entropy = 0;
    reg [15:0] frame_entropy = 0;
    
    localparam [15:0] MIN_ENTROPY = 16'd42; // Arbitrary threshold for "interesting" frames

    julia_core fractal (
        .clk(clk_12M),
        .rst(1'b0),
        .start(start_julia),
        .cx(c_x), .cy(c_y),
        .ox(zoom_x), .oy(zoom_y),
        .dx(delta_x), .dy(delta_y),
        .p_x(p_x), .p_y(p_y),
        .iter(iter), .p_valid(p_valid), .done(done)
    );

    // Color gradient mapping based on iter value
    // Cycle through palettes with btn_ok
    reg [2:0] palette = 0;
    reg [7:0] t_r, t_g, t_b;

    always @(*) begin
        case (palette)
            3'd0: begin // Default
                t_r = {iter[3:0], iter[4:1]};
                t_g = {iter[4:2], iter[4:0]};
                t_b = {iter[2:0], iter[4:0]};
            end
            3'd1: begin // Fire
                t_r = {iter[4:0], 3'b0};
                t_g = {iter[3:0], 4'b0};
                t_b = {iter[2:0], 5'b0};
            end
            3'd2: begin // Ice
                t_r = {iter[2:0], 5'b0};
                t_g = {iter[3:0], 4'b0};
                t_b = {iter[4:0], 3'b0};
            end
            3'd3: begin // Matrix (Green)
                t_r = {iter[2:0], 5'b0};
                t_g = {iter[4:0], 3'b0};
                t_b = {iter[2:0], 5'b0};
            end
            3'd4: begin // Synthwave (Pink/Cyan)
                t_r = {iter[4:0], 3'b0};
                t_g = {iter[2:0], 5'b0};
                t_b = {iter[4:0], 3'b0};
            end
            3'd5: begin // Grayscale
                t_r = {iter[4:0], 3'b0};
                t_g = {iter[4:0], 3'b0};
                t_b = {iter[4:0], 3'b0};
            end
            3'd6: begin // High Contrast
                t_r = iter[0] ? 8'hFF : 8'h00;
                t_g = iter[1] ? 8'hFF : 8'h00;
                t_b = iter[2] ? 8'hFF : 8'h00;
            end
            3'd7: begin // Inverted default
                t_r = ~{iter[3:0], iter[4:1]};
                t_g = ~{iter[4:2], iter[4:0]};
                t_b = ~{iter[2:0], iter[4:0]};
            end
        endcase
    end

    wire [7:0] next_r = (iter == 31) ? 8'h0 : t_r;
    wire [7:0] next_g = (iter == 31) ? 8'h0 : t_g;
    wire [7:0] next_b = (iter == 31) ? 8'h0 : t_b;

    wire [7:0] diff_r = (next_r > wr_r) ? (next_r - wr_r) : (wr_r - next_r);
    wire [7:0] diff_g = (next_g > wr_g) ? (next_g - wr_g) : (wr_g - next_g);
    wire [7:0] diff_b = (next_b > wr_b) ? (next_b - wr_b) : (wr_b - next_b);

    always @(posedge clk_12M) begin
        if (p_valid) begin
            wr_x <= p_x;
            wr_y <= p_y;
            wr_r <= next_r;
            wr_g <= next_g;
            wr_b <= next_b;
            wr_en <= 1'b1;

            // Compute running entropy for this frame (compare new pixel with previous pixel)
            if (p_x == 0 && p_y == 0) begin
                // For the first pixel, we don't have a valid previous pixel to compare against
                total_entropy <= 0;
            end else begin
                // diff_r/g/b look at next_r/g/b against wr_r/g/b which are safely the PREVIOUS cycle's pixel
                total_entropy <= total_entropy + diff_r + diff_g + diff_b;
            end

        end else begin
            wr_en <= 1'b0;
        end
    end

    wire signed [15:0] rand_x = { {4{lfsr[11]}}, lfsr[11:0] }; // -2048 to 2047 (-1.0 to +1.0)
    wire signed [15:0] rand_y = { {4{lfsr[15]}}, lfsr[15:4] }; // -2048 to 2047 (-1.0 to +1.0)
    wire [15:0] abs_x = (rand_x[15]) ? -rand_x : rand_x;
    wire [15:0] abs_y = (rand_y[15]) ? -rand_y : rand_y;

    // -- Simple Sequencer (Start Julia calc -> Done -> Wait -> Repeat) --
    reg [23:0] frame_timer = 24'd400_000; // 30 FPS
    
    reg btn_ok_prev = 1'b1;

    always @(posedge clk_12M) begin
        start_julia <= 1'b0;
        lfsr <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]}; // LFSR for random points
        
        if (done) begin
            frame_entropy <= total_entropy;
            frame_timer <= 24'd400_000; // wait ~33ms
            
            // Cycle palette on btn_ok press (sampled once per frame acts as a free debounce!)
            btn_ok_prev <= btn_ok;
            if (btn_ok_prev == 1'b1 && btn_ok == 1'b0) begin
                palette <= palette + 1;
            end
            
            // Dynamic parameter update via active-low buttons
            // Clamped C bounded to "interesting" bounds (-1.5 to +1.5) and (-2.0 to +1.0)
            if (!btn_up && c_y > -16'sd3072)    c_y <= c_y - 16'h0020;
            else if (!btn_down && c_y < 16'sd3072)  c_y <= c_y + 16'h0020;
            
            if (!btn_left && c_x > -16'sd4096)  c_x <= c_x - 16'h0020;
            else if (!btn_right && c_x < 16'sd2048) c_x <= c_x + 16'h0020;
            
            // --- Auto Zoom Logic ---
            if (auto_state == STATE_ZOOM_IN) begin
                // Slowly zoom into target (>> 6 gives proportional speed)
                if (delta_x > 16'h0004 && frame_entropy > MIN_ENTROPY) begin
                    delta_x <= delta_x - ((delta_x >> 6) | 16'h0001);
                    delta_y <= delta_y - ((delta_y >> 6) | 16'h0001);
                end else begin
                    // Entropy dropped too low or zoomed all the way in
                    auto_state <= STATE_ZOOM_OUT;
                end
            end else if (auto_state == STATE_ZOOM_OUT) begin
                // Zoom out further (16'h0200 = step of 0.25 per pixel -> 4.0 total width)
                if (delta_x < 16'h0200) begin
                    delta_x <= delta_x + ((delta_x >> 8) | 16'h0001);
                    delta_y <= delta_y + ((delta_y >> 8) | 16'h0001);
                end else begin
                    // Fully zoomed out
                    delta_x <= 16'h0200;
                    delta_y <= 16'h0200;
                    // Pick random coords within the unit circle |p_x| + |p_y| < 1.0 (0x0800)
                    if (abs_x + abs_y < 16'h0800) begin
                        target_x <= rand_x;
                        target_y <= rand_y;
                        auto_state <= STATE_PAN;
                    end
                end
            end else if (auto_state == STATE_PAN) begin
                // Slowly pan to target
                if (center_x < target_x) begin
                    if (target_x - center_x < 16'h0008) center_x <= target_x;
                    else center_x <= center_x + 16'h0008;
                end else if (center_x > target_x) begin
                    if (center_x - target_x < 16'h0008) center_x <= target_x;
                    else center_x <= center_x - 16'h0008;
                end
                
                if (center_y < target_y) begin
                    if (target_y - center_y < 16'h0008) center_y <= target_y;
                    else center_y <= center_y + 16'h0008;
                end else if (center_y > target_y) begin
                    if (center_y - target_y < 16'h0008) center_y <= target_y;
                    else center_y <= center_y - 16'h0008;
                end
                
                if (center_x == target_x && center_y == target_y) begin
                    auto_state <= STATE_ZOOM_IN;
                end
            end
            
            // Adjust the actual viewport (ox, oy) so center stays at the center (x=8, y=4)
            zoom_x <= center_x - 8 * delta_x;
            zoom_y <= center_y - 4 * delta_y;
            // -----------------------

        end else if (frame_timer > 0) begin
            frame_timer <= frame_timer - 1;
            if (frame_timer == 1) begin
                start_julia <= 1'b1;
            end
        end
    end
endmodule
