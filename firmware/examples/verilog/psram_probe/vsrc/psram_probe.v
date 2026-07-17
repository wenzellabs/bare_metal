module psram_probe(
    input clk,
    input rst,
    input restart,  // Pulse to restart test
    output reg spi_mosi,
    input spi_miso,
    output reg spi_clk,
    output reg spi_csn,
    output reg busy,
    output reg [31:0] detected_bytes,
    output reg [7:0] state,
    output [23:0] addr_out,
    output reg test_passed  // High if test passed (all bytes matched)
);
    reg clk_div;
    localparam S_START_WRITE = 0;
    localparam S_CMD_WRITE = 1;
    localparam S_ADDR_WRITE = 2;
    localparam S_DATA_WRITE = 3;
    localparam S_FINISH_WRITE = 4;
    localparam S_START_READ = 5;
    localparam S_CMD_READ = 6;
    localparam S_ADDR_READ = 7;
    localparam S_DATA_READ = 8;
    localparam S_FINISH_READ = 9;
    localparam S_CHECK = 10;
    localparam S_DONE = 11;
    localparam S_WAIT = 12;

    reg [7:0] bitcnt;
    reg [7:0] cmd_byte;
    reg [23:0] addr;
    reg [7:0] in_byte;
    reg [7:0] next_state;
    reg spi_phase;
    reg [7:0] test_pattern;

    // Export addr for live progress updates
    assign addr_out = addr;

    localparam S_INIT_66_CMD = 20;
    localparam S_INIT_66_CS_HIGH = 21;
    localparam S_INIT_99_CMD = 22;
    localparam S_INIT_99_CS_HIGH = 23;

    initial begin
        spi_mosi = 1'b0;
        spi_clk = 1'b0;
        spi_csn = 1'b1;
        busy = 1'b1;
        detected_bytes = 32'd0;
        clk_div = 1'b0;
        state = S_INIT_66_CMD;
        addr = 24'h000000;
        test_pattern = 8'hA5;
        spi_phase = 0;
        test_passed = 1'b1;
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= S_INIT_66_CMD;
            spi_csn <= 1'b1;
            busy <= 1'b1;
            detected_bytes <= 32'd0;
            clk_div <= 0;
            addr <= 0;
            test_passed <= 1'b1;
        end else if (restart && state == S_DONE) begin
            // Restart the test from beginning
            state <= S_INIT_66_CMD;
            addr <= 0;
            detected_bytes <= 0;
            test_passed <= 1'b1;
        end else begin
            clk_div <= ~clk_div;
            if (!clk_div) begin
                case (state)

                    S_INIT_66_CMD: begin
                        spi_csn <= 1'b0;
                        cmd_byte <= 8'h66; // RESET ENABLE
                        bitcnt <= 8'd7;
                        spi_phase <= 1'b0;
                        next_state <= S_INIT_66_CS_HIGH;
                        state <= S_CMD_WRITE;
                    end
                    S_INIT_66_CS_HIGH: begin
                        spi_clk <= 1'b0;
                        spi_csn <= 1'b1;
                        bitcnt <= 8'd50; // wait some cycles
                        next_state <= S_INIT_99_CMD;
                        state <= S_WAIT;
                    end
                    S_INIT_99_CMD: begin
                        spi_csn <= 1'b0;
                        cmd_byte <= 8'h99; // RESET
                        bitcnt <= 8'd7;
                        spi_phase <= 1'b0;
                        next_state <= S_INIT_99_CS_HIGH;
                        state <= S_CMD_WRITE;
                    end
                    S_INIT_99_CS_HIGH: begin
                        spi_clk <= 1'b0;
                        spi_csn <= 1'b1;
                        bitcnt <= 8'd200; // wait 200 cycles, ~10+ us
                        next_state <= S_START_WRITE;
                        state <= S_WAIT;
                    end
                    S_START_WRITE: begin
                        spi_csn <= 1'b0;
                        cmd_byte <= 8'h02; // WRITE
                        bitcnt <= 8'd7;
                        spi_phase <= 1'b0;
                        // Vary the pattern per address to avoid false wrap matches on a floating bus
                        test_pattern <= 8'hA5 + addr[23:16];
                        state <= S_CMD_WRITE;
                    end
                    S_CMD_WRITE: begin
                        if (spi_phase == 1'b0) begin
                            spi_mosi <= cmd_byte[bitcnt];
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                if (state == S_CMD_WRITE && (cmd_byte == 8'h66 || cmd_byte == 8'h99)) begin
                                    state <= next_state;
                                end else begin
                                    bitcnt <= 8'd23;
                                    state <= S_ADDR_WRITE;
                                end
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_ADDR_WRITE: begin
                        if (spi_phase == 1'b0) begin
                            spi_mosi <= addr[bitcnt];
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                bitcnt <= 8'd7;
                                state <= S_DATA_WRITE;
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_DATA_WRITE: begin
                        if (spi_phase == 1'b0) begin
                            spi_mosi <= test_pattern[bitcnt];
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                state <= S_FINISH_WRITE;
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_FINISH_WRITE: begin
                        spi_clk <= 1'b0;
                        spi_csn <= 1'b1;
                        bitcnt <= 8'd10;
                        next_state <= S_START_READ;
                        state <= S_WAIT;
                    end
                    S_START_READ: begin
                        spi_csn <= 1'b0;
                        cmd_byte <= 8'h03; // READ
                        bitcnt <= 8'd7;
                        spi_phase <= 1'b0;
                        state <= S_CMD_READ;
                    end
                    S_CMD_READ: begin
                        if (spi_phase == 1'b0) begin
                            spi_mosi <= cmd_byte[bitcnt];
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                bitcnt <= 8'd23;
                                state <= S_ADDR_READ;
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_ADDR_READ: begin
                        if (spi_phase == 1'b0) begin
                            spi_mosi <= addr[bitcnt];
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                bitcnt <= 8'd7;
                                state <= S_DATA_READ;
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_DATA_READ: begin
                        if (spi_phase == 1'b0) begin
                            spi_clk <= 1'b0;
                            spi_phase <= 1'b1;
                        end else begin
                            in_byte[bitcnt] <= spi_miso;
                            spi_clk <= 1'b1;
                            spi_phase <= 1'b0;
                            if (bitcnt == 0) begin
                                state <= S_FINISH_READ;
                            end else begin
                                bitcnt <= bitcnt - 1;
                            end
                        end
                    end
                    S_FINISH_READ: begin
                        spi_clk <= 1'b0;
                        spi_csn <= 1'b1;
                        bitcnt <= 8'd10;
                        next_state <= S_CHECK;
                        state <= S_WAIT;
                    end
                    S_CHECK: begin
                        if (in_byte == test_pattern) begin
                            // Match! PSRAM exists at this address
                            // increment address
                            if (addr >= 24'h7F0000) begin
                                // max address reached (testing last or beyond)
                                detected_bytes <= {8'd0, addr} + 32'h010000;
                                test_passed <= 1'b1;
                                state <= S_DONE;
                            end else begin
                                addr <= addr + 24'h010000; // 64KB chunks
                                state <= S_START_WRITE;
                            end
                        end else begin
                            // Failed match, memory ends here or wrapped
                            // Format: [23:16]=0, [15:8]=expected_byte, [7:0]=actual_byte_read
                            detected_bytes <= {8'd0, 8'd0, test_pattern, in_byte};
                            test_passed <= 1'b0;
                            state <= S_DONE;
                        end
                    end
                    S_WAIT: begin
                        if (bitcnt == 0) begin
                            state <= next_state;
                        end else begin
                            bitcnt <= bitcnt - 1;
                        end
                    end
                    S_DONE: begin
                        spi_csn <= 1'b1;
                        spi_clk <= 1'b0;
                        busy <= 1'b0;
                    end
                endcase
            end
        end
    end
endmodule
