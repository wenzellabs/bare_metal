module pll(
    input  clock_in,
    output clock_out,
    output locked
);
    SB_PLL40_PAD #(
        .FEEDBACK_PATH("SIMPLE"),
        .DIVR(4'b0000),         // DIVR =  0
        .DIVF(7'b1000010),      // DIVF = 66
        .DIVQ(3'b101),          // DIVQ =  5
        .FILTER_RANGE(3'b001)   // FILTER_RANGE = 1
    ) uut (
        .PACKAGEPIN(clock_in),
        .PLLOUTCORE(clock_out),
        .RESETB(1'b1),
        .BYPASS(1'b0),
        .LOCK(locked)
    );
endmodule
