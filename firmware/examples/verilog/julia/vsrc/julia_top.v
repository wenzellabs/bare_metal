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
    reg signed [15:0] zoom_x = 16'hF000; // -2.0 (was E000 which is -4.0 in Q5.11)
    reg signed [15:0] zoom_y = 16'hF800; // -1.0 (was F000 which is -2.0 in Q5.11)
    reg signed [15:0] delta_x = 16'h0200; // 0.25
    reg signed [15:0] delta_y = 16'h0200; // 0.25

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
    wire [7:0] t_r = iter * 8;
    wire [7:0] t_g = iter * 4;
    wire [7:0] t_b = iter * 12;

    always @(posedge clk_12M) begin
        if (p_valid) begin
            wr_x <= p_x;
            wr_y <= p_y;
            wr_r <= (iter == 31) ? 8'h0 : t_r;
            wr_g <= (iter == 31) ? 8'h0 : t_g;
            wr_b <= (iter == 31) ? 8'h0 : t_b;
            wr_en <= 1'b1;
        end else begin
            wr_en <= 1'b0;
        end
    end

    // -- Simple Sequencer (Start Julia calc -> Done -> Wait -> Repeat) --
    reg [23:0] frame_timer = 24'd400_000; // 30 FPS
    always @(posedge clk_12M) begin
        start_julia <= 1'b0;
        if (done) begin
            frame_timer <= 24'd400_000; // wait ~33ms
            
            // Dynamic parameter update (animated slowly instead of buttons)
            c_y <= c_y + 16'h0008; // Slowly drift C_y
            // c_x <= c_x + 16'h0004; // Slowly drift C_x
            
        end else if (frame_timer > 0) begin
            frame_timer <= frame_timer - 1;
            if (frame_timer == 1) begin
                start_julia <= 1'b1;
            end
        end
    end
endmodule
