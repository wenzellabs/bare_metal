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

    // 2D pattern generating all 64 colors and showing full resolution
    wire [5:0] pattern;
    
    // An XOR pattern that uses fine bits to show full resolution and 
    // higher bits to show slow gradients/blocks. Offset by frame counter for animation.
    wire [5:0] munching = (x[7:2] ^ y[7:2]);
    wire [5:0] gradient = x[5:0] + y[5:0];
    assign pattern = munching + gradient + frame_counter[7:2];
    
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
