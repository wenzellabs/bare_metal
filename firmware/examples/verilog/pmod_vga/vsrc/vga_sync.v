module vga_sync (
    input wire clk,
    input wire rst,
    output wire hsync,
    output wire vsync,
    output wire [9:0] x,
    output wire [9:0] y,
    output wire active
);

    // 640x480 @ 60 Hz
    parameter H_DISP = 640;
    parameter H_FP   = 16;
    parameter H_SYNC = 96;
    parameter H_BP   = 48;
    parameter H_TOTAL = H_DISP + H_FP + H_SYNC + H_BP; // 800

    parameter V_DISP = 480;
    parameter V_FP   = 10;
    parameter V_SYNC = 2;
    parameter V_BP   = 33;
    parameter V_TOTAL = V_DISP + V_FP + V_SYNC + V_BP; // 525

    reg [9:0] h_cnt;
    reg [9:0] v_cnt;

    always @(posedge clk) begin
        if (rst) begin
            h_cnt <= 0;
            v_cnt <= 0;
        end else begin
            if (h_cnt == H_TOTAL - 1) begin
                h_cnt <= 0;
                if (v_cnt == V_TOTAL - 1)
                    v_cnt <= 0;
                else
                    v_cnt <= v_cnt + 1;
            end else begin
                h_cnt <= h_cnt + 1;
            end
        end
    end

    assign hsync = ~(h_cnt >= (H_DISP + H_FP) && h_cnt < (H_DISP + H_FP + H_SYNC));
    assign vsync = ~(v_cnt >= (V_DISP + V_FP) && v_cnt < (V_DISP + V_FP + V_SYNC));
    
    assign active = (h_cnt < H_DISP) && (v_cnt < V_DISP);
    assign x = (h_cnt < H_DISP) ? h_cnt : 10'd0;
    assign y = (v_cnt < V_DISP) ? v_cnt : 10'd0;

endmodule
