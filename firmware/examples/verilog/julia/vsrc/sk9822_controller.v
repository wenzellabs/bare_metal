module sk9822_controller(    input  wire clk,    input  wire rst,
    // Write parameters
    input  wire [3:0] wr_x,
    input  wire [3:0] wr_y,
    input  wire [7:0] wr_r,
    input  wire [7:0] wr_g,
    input  wire [7:0] wr_b,
    input  wire       wr_en,

    // Hardware outputs (SPI-ish)
    output reg led_data,
    output reg led_clk
);

    // -- Framebuffer Memory --
    // 16 cols (x) x 8 rows (y) = 128 LEDs.
    reg [7:0] mem_r [0:127];
    reg [7:0] mem_g [0:127];
    reg [7:0] mem_b [0:127];
    
    // Mapping: X=0..15, Y=0..7 -> index = (15 - wr_x) * 8 + wr_y
    wire [6:0] wr_addr = ((7'd15 - wr_x) * 8) + wr_y; // Safe math

    always @(posedge clk) begin
        if (wr_en) begin
            mem_r[wr_addr] <= wr_r;
            mem_g[wr_addr] <= wr_g;
            mem_b[wr_addr] <= wr_b;
        end
    end

    reg [2:0]  clk_div = 0;
    reg [12:0] bit_counter = 0;
    initial begin
        led_clk = 0;
        led_data = 0;
    end

    wire tick = (clk_div == 3'h0);
    wire next_bit = tick && !led_clk;

    // Prefetch for memory reads
    wire [6:0] led_index = (bit_counter >= 32) ? ((bit_counter - 32) >> 5) : 0;
    reg [7:0] red, green, blue;

    always @(posedge clk) begin
        red   <= mem_r[led_index];
        green <= mem_g[led_index];
        blue  <= mem_b[led_index];
    end

    // APA102 / SK9822 format: 111, brightness, then B, G, R
    wire [31:0] current_frame = {3'b111, 5'h02, blue, green, red};

    always @(posedge clk) begin
        if (rst) begin
            clk_div     <= 0;
            led_clk     <= 0;
            led_data    <= 0;
            bit_counter <= 0;
        end else begin
            clk_div <= clk_div + 1;
            
            if (tick) begin
                led_clk <= ~led_clk;
                
                if (led_clk) begin // Update on falling edge of led_clk
                    // On falling edge of generated led_clk, we push new data
                    
                    if (bit_counter < 32) begin
                        // 32 bits Start Frame
                        led_data <= 1'b0;
                    end else if (bit_counter < 4128) begin // 32 + (128 LEDs * 32 bits)
                        // MSB first
                        led_data <= current_frame[~bit_counter[4:0]];
                    end else begin
                        // End Frame (at least 64 bits of 1s or 0s to latch)
                        led_data <= 1'b1;
                    end

                    // Count bits
                    if (bit_counter == 13'h105F) begin // 4128 + 64 - 1
                        bit_counter <= 0;
                    end else begin
                        bit_counter <= bit_counter + 1;
                    end
                end
            end
        end
    end

endmodule
