module julia_core(
    input  wire clk,
    input  wire rst,
    input  wire start,
    input  wire signed [15:0] cx, cy,
    input  wire signed [15:0] ox, oy,
    input  wire signed [15:0] dx, dy,
    
    output reg        [3:0] p_x,
    output reg        [2:0] p_y,
    output reg        [5:0] iter,
    output wire             p_valid,
    output wire             done
);
    localparam ITER_MAX = 6'd31;

    reg signed [15:0] zx, zy;
    reg signed [15:0] cur_ox, cur_oy;
    
    wire signed [31:0] zx2_32 = zx * zx;
    wire signed [31:0] zy2_32 = zy * zy;
    wire signed [31:0] zxy_32 = zx * zy;
    
    wire signed [15:0] zx2 = zx2_32[26:11];
    wire signed [15:0] zy2 = zy2_32[26:11];
    wire signed [15:0] zxy = zxy_32[26:11]; 
    
    wire signed [15:0] nx = zx2 - zy2 + cx;
    wire signed [15:0] ny = (zxy <<< 1) + cy;
    
    wire condition = ((zx2 + zy2) > 16'h2000);
    
    localparam S_IDLE = 0, S_INIT = 1, S_CALC = 2, S_RESULT = 3;
    reg [1:0] state = 0;
    
    assign p_valid = (state == S_RESULT);
    assign done = (state == S_RESULT && p_x == 15 && p_y == 7);
    
    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE;
            p_x <= 0; p_y <= 0;
            cur_ox <= 0; cur_oy <= 0;
            zx <= 0; zy <= 0;
            iter <= 0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (start) begin
                        state <= S_INIT;
                        p_x <= 0;
                        p_y <= 0;
                        cur_ox <= ox;
                        cur_oy <= oy;
                    end
                end
                
                S_INIT: begin
                    zx <= cur_ox;
                    zy <= cur_oy;
                    iter <= 0;
                    state <= S_CALC;
                end
                
                S_CALC: begin
                    if (condition || iter == ITER_MAX) begin
                        state <= S_RESULT;
                    end else begin
                        zx <= nx;
                        zy <= ny;
                        iter <= iter + 1;
                    end
                end
                
                S_RESULT: begin
                    if (p_x == 15 && p_y == 7) begin
                        state <= S_IDLE;
                    end else begin
                        if (p_y == 7) begin
                            p_y <= 0;
                            p_x <= p_x + 1;
                            cur_ox <= cur_ox + dx;
                            cur_oy <= oy;
                        end else begin
                            p_y <= p_y + 1;
                            cur_oy <= cur_oy + dy;
                        end
                        state <= S_INIT;
                    end
                end
            endcase
        end
    end
endmodule
