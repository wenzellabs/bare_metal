module psram_probe_top(
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
    output led_power_on,
);


    wire clkin;
    // tie-offs

    assign led_index = 1'b1;
    assign led_middle = 1'b1;
    assign led_pinky = 1'b1;
    assign spi_csn_flash = 1'b1;
    assign spi_wp = 1'b1;
    assign spi_hold = 1'b1;
    assign led_power_on = 1'b1; // CRITICAL: Need to power on the LED matrix!

    // sk9822 interface signals
    reg [3:0] wr_x;
    reg [3:0] wr_y;
    reg [7:0] wr_r, wr_g, wr_b;
    reg wr_en;

    sk9822_controller display (
        .clk(clkin),
        .rst(rst_probe),
        .wr_x(wr_x),
        .wr_y(wr_y),
        .wr_r(wr_r),
        .wr_g(wr_g),
        .wr_b(wr_b),
        .wr_en(wr_en),
        .led_data(led_di),
        .led_clk(led_ci)
    );

    // PSRAM probe unit
    wire probe_busy;
    reg [25:0] boot_delay;
    initial boot_delay = 26'd60000000;
    wire rst_probe = (boot_delay != 26'd0);
    always @(posedge clkin) begin
        if (boot_delay != 26'd0) begin
             boot_delay <= boot_delay - 1;
        end
    end

    wire [31:0] detected_bytes; // reported number of bytes found
    wire [7:0] probe_state;
    wire [23:0] addr; // current address being tested
    wire test_passed;
    reg [7:0] last_probe_state;
    reg probe_restart = 0;


    psram_probe probe (
        .clk(clkin),
        .rst(rst_probe),
        .restart(probe_restart),
        .spi_mosi(spi_mosi),
        .spi_miso(spi_miso),
        .spi_clk(spi_clk),
        .spi_csn(spi_csn_ram),
        .busy(probe_busy),
        .detected_bytes(detected_bytes),
        .state(probe_state),
        .addr_out(addr),
        .test_passed(test_passed)
    );

    // We instantiate the USB CDC ACM logic to send the report over USB serial!
    usb_reporter reporter (
        .report_data(p_val),
        .report_ready(usb_report_ready), // pulse when done
        .pin_clk_12M(clk_12M),
        .pin_usbp(usbp),
        .pin_usbn(usbn),
        .pin_usb_det(usb_det),
        .pin_btn_ok(btn_ok),
        .pin_btn_left(btn_left),
        .pin_btn_right(btn_right),
        .pin_btn_down(btn_down),
        .pin_led_index(),
        .pin_led_middle(),
        .pin_led_pinky(),
        .pin_spi_miso(1'b0),
        .pin_spi_cs(),
        .pin_spi_mosi(),
        .pin_spi_sck(),
        .pin_spi_wp(),
        .pin_spi_hold(), .clk_out(clkin)
    );

    reg usb_report_ready = 0;


    // Simple display FSM: wait for probe to finish, then show bar graph

    reg [23:0] timer = 0;
    reg [27:0] restart_timer = 0;

    reg showing = 0;
    reg [6:0] test_count = 0; // Count successful tests (for LED display)
    reg [6:0] led_idx = 0;

    reg [31:0] p_val = 0;

    always @(posedge clkin) begin
        probe_restart <= 1'b0; // Default
        usb_report_ready <= 1'b0; // Default

        if (!showing) begin
            // Probing - no output during test

            if (!probe_busy) begin
                // Test complete!
                showing <= 1'b1;
                timer <= 24'd0;
                restart_timer <= 0;

                // Send result immediately (USB reporter will format as 8 hex chars + \r\n)
                p_val <= detected_bytes;
                usb_report_ready <= 1'b1;

                // Increment test counter ONLY if passed AND memory detected (>0)
                if (test_passed && detected_bytes > 0 && test_count < 128) begin
                    test_count <= test_count + 1;
                end
            end

            // blank display while probing
            wr_en <= 1'b0;
            wr_x <= 0; wr_y <= 0; wr_r <= 0; wr_g <= 0; wr_b <= 0;
        end else begin
            // Done testing - wait 2 seconds then restart
            restart_timer <= restart_timer + 1;
            // Restart after ~2 seconds (24M clocks at 12MHz)
            if (restart_timer == 28'h1800000) begin
                probe_restart <= 1'b1;
                showing <= 1'b0;
            end

            // Update LED display - show one LED per successful test
            // iterate and write pixels one-per-cycle
            if (timer < 24'd20000) begin
                led_idx <= timer[6:0]; // wraps every 128
                wr_x <= 15 - (led_idx >> 3); // display is arranged with x reversed in this board
                wr_y <= led_idx & 3'h7;
                if (led_idx < test_count) begin
                    // Show green LED for each successful test
                    wr_r <= 8'h00; wr_g <= 8'hFF; wr_b <= 8'h00;
                end else begin
                    // Off
                    wr_r <= 8'h00; wr_g <= 8'h00; wr_b <= 8'h00;
                end
                wr_en <= 1'b1;
                timer <= timer + 1;
            end else begin
                timer <= 24'd0;
            end
        end
    end

endmodule
