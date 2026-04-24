module flash_controller(
    input wire clk, rst,
    input wire start,
    input wire [23:0] addr,
    input wire [15:0] read_len,
    
    output reg busy,
    output reg [7:0] rdata,
    output reg valid,
    
    // SPI physical pins
    output reg spi_csn,
    output reg spi_clk,
    output reg spi_mosi,
    input  wire spi_miso
);
    localparam S_IDLE = 0, S_CMD = 1, S_READ = 2;
    reg [1:0] state;
    
    reg [5:0] bit_cnt;
    reg [15:0] byte_cnt;
    reg [31:0] shift_out; 
    reg [7:0] shift_in;
    reg clk_phase;
    
    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE;
            busy <= 0;
            spi_csn <= 1;
            spi_clk <= 0;
            spi_mosi <= 0;
            valid <= 0;
            clk_phase <= 0;
        end else begin
            valid <= 0;
            
            case(state)
                S_IDLE: begin
                    spi_csn <= 1;
                    spi_clk <= 0;
                    if (start) begin
                        state <= S_CMD;
                        shift_out <= {8'h03, addr};
                        bit_cnt <= 31;
                        byte_cnt <= read_len;
                        busy <= 1;
                        spi_csn <= 0;
                        spi_mosi <= 0;
                        clk_phase <= 0;
                    end else begin
                        busy <= 0;
                    end
                end
                
                S_CMD: begin
                    if (clk_phase == 0) begin
                        spi_mosi <= shift_out[bit_cnt];
                        spi_clk <= 0;
                        clk_phase <= 1;
                    end else begin
                        spi_clk <= 1;
                        clk_phase <= 0;
                        if (bit_cnt == 0) begin
                            if (byte_cnt == 0) begin
                                state <= S_IDLE;
                            end else begin
                                state <= S_READ;
                                bit_cnt <= 7;
                            end
                        end else begin
                            bit_cnt <= bit_cnt - 1;
                        end
                    end
                end
                
                S_READ: begin
                    if (clk_phase == 0) begin
                        spi_clk <= 0;
                        clk_phase <= 1;
                    end else begin
                        spi_clk <= 1;
                        clk_phase <= 0;
                        shift_in <= {shift_in[6:0], spi_miso};
                        
                        if (bit_cnt == 0) begin
                            rdata <= {shift_in[6:0], spi_miso};
                            valid <= 1;
                            byte_cnt <= byte_cnt - 1;
                            if (byte_cnt == 1 || byte_cnt == 0) begin
                                state <= S_IDLE;
                            end else begin
                                bit_cnt <= 7;
                            end
                        end else begin
                            bit_cnt <= bit_cnt - 1;
                        end
                    end
                end
            endcase
        end
    end
endmodule