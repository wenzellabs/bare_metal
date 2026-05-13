`default_nettype none

module vga_top (
    input clk_12M,
    
    // PMOD VGA
    output hsync,
    output vsync,
    output r_hi,
    output r_lo,
    output g_hi,
    output g_lo,
    output b_hi,
    output b_lo,
    
    // Buttons
    input btn_ok,
    input btn_down,

    // LEDs for status
    output led_index,
    output led_middle,
    output led_pinky
);

    wire clk_25M;
    wire locked;
    
    pll pll_inst (
        .clock_in(clk_12M),
        .clock_out(clk_25M),
        .locked(locked)
    );

    wire [9:0] x, y;
    wire active;
    
    vga_sync sync_inst (
        .clk(clk_25M),
        .rst(~locked),
        .hsync(hsync),
        .vsync(vsync),
        .x(x),
        .y(y),
        .active(active)
    );

    reg [23:0] frame_counter = 0;
    always @(posedge vsync) begin
        frame_counter <= frame_counter + 1;
    end

    // Button edge detection for advancing modes
    reg [2:0] btn_sync;
    always @(posedge clk_25M) begin
        btn_sync <= {btn_sync[1:0], btn_ok};
    end
    wire btn_pressed = (btn_sync[2:1] == 2'b10); // assuming active low, but standard is just looking for an edge. If btn_ok is active low (common on pull-up buttons), pressing goes 1->0. Let's trigger on 0->1 or 1->0. Let's just catch falling edge:
    wire btn_falling = (btn_sync[2:1] == 2'b10); 
    wire btn_rising = (btn_sync[2:1] == 2'b01);
    
    // We'll advance on falling edge (assuming active low with pull-up)
    // Actually the pcf doesn't say pullup, but it's on IOT_37a or similar.
    // Let's just use falling edge.
    reg [2:0] manual_offset = 0;
    always @(posedge clk_25M) begin
        // The button might bounce, so let's only increment if it's pressed and a slow clock enables it,
        // or just use a simple debounce:
    end

    // Debounce buttons by sampling at ~95Hz
    reg [17:0] debounce_counter = 0;
    reg btn_state = 1'b1;
    reg btn_prev = 1'b1;
    reg btn_down_state = 1'b1;
    reg btn_down_prev = 1'b1;
    
    always @(posedge clk_25M) begin
        debounce_counter <= debounce_counter + 1;
        if (debounce_counter == 0) begin
            btn_state <= btn_ok;
            btn_down_state <= btn_down;
        end
        
        // Edge detection on the sampled state
        btn_prev <= btn_state;
        if (btn_prev == 1'b1 && btn_state == 1'b0) begin
            manual_offset <= manual_offset + 1;
        end
        
        btn_down_prev <= btn_down_state;
        if (btn_down_prev == 1'b1 && btn_down_state == 1'b0) begin
            // Jump to mode 0 by zeroing out the sum
            manual_offset <= -frame_counter[13:11];
        end
    end

    wire [1:0] hbar = (y < 120) ? 2'd0 : (y < 240) ? 2'd1 : (y < 360) ? 2'd2 : 2'd3;
    wire [1:0] vbar = (x < 160) ? 2'd0 : (x < 320) ? 2'd1 : (x < 480) ? 2'd2 : 2'd3;
    wire [10:0] diag = x + y + {t, 3'b0}; 
    wire [1:0] bdiag = diag[7:6]; // diagonal stripes

    // 2D pattern generating all 64 colors and showing full resolution
    wire [2:0] stage = frame_counter[13:11] + manual_offset; // Switch demo stage periodically or via button
    wire [7:0] t = frame_counter[10:3];      // 8x slower animation
    
    reg [5:0] pattern_reg;
    always @(*) begin
        case (stage)
            3'd0: begin
                // 4 hbars and 4 vbars, R and G increasingly bright.
                // Diagonal stripes for B
                pattern_reg[1:0] = hbar;
                pattern_reg[3:2] = vbar;
                pattern_reg[5:4] = bdiag;
            end
            3'd1: pattern_reg = (x[8:3] ^ y[8:3]) + t[5:0];                             // Moving XOR munching squares
            3'd2: begin 
                // Color Cubes: 4x4 grid of 64x64 blocks. R, G across grid. B oscillates.
                pattern_reg[1:0] = x[8:7]; // R 
                pattern_reg[3:2] = y[8:7]; // G
                pattern_reg[5:4] = t[5:4] + x[6:5] + y[6:5]; // B slowly changing with sub-blocks
            end
            3'd3: pattern_reg = x[8:3] - y[8:3] + t[5:0];                               // Reverse diagonal waves
            3'd4: begin 
                // RGB spectrum gradients mapping spatial blocks
                pattern_reg[1:0] = x[6:5] + t[3:2]; 
                pattern_reg[3:2] = y[6:5] - t[3:2]; 
                pattern_reg[5:4] = (x[7:6] ^ y[7:6]) + t[4:3];
            end
            3'd5: pattern_reg = (x[7:2] | y[7:2]) - t[5:0];                             // OR texture zooming
            3'd6: begin
                // Color cube palette showing all 64 colors mapped geometrically as tiles
                pattern_reg[1:0] = x[7:6]; // R component
                pattern_reg[3:2] = y[7:6]; // G component
                // B component uses a grid divided into 4 quadrants
                pattern_reg[5:4] = {x[8], y[8]} ^ t[5:4]; // B component flips over time
            end
            3'd7: pattern_reg = x[9:4] + y[9:4] + (x[7:2] ^ y[7:2]) - (t[6:1] ^ x[7:2]);// Complex organic gradient
            default: pattern_reg = 6'b00_00_00;
        endcase
    end

    wire [5:0] pattern = pattern_reg;

    wire [1:0] r = active ? pattern[1:0] : 2'b00;
    wire [1:0] g = active ? pattern[3:2] : 2'b00;
    wire [1:0] b = active ? pattern[5:4] : 2'b00;

    assign r_hi = r[1];
    assign r_lo = r[0];
    assign g_hi = g[1];
    assign g_lo = g[0];
    assign b_hi = b[1];
    assign b_lo = b[0];

    // Status LEDs: active low
    assign led_index = ~locked;
    assign led_middle = ~vsync;
    assign led_pinky = ~hsync;

endmodule
