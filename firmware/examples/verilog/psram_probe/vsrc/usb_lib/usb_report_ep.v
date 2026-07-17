module usb_report_ep (  input clk,  input reset,  input [31:0] report_data,  input report_ready,
  // out endpoint interface (unused but tied off)
  output out_ep_req,
  input out_ep_grant,
  input out_ep_data_avail,
  input out_ep_setup,
  output out_ep_data_get,
  input [7:0] out_ep_data,
  output out_ep_stall,
  input out_ep_acked,

  // in endpoint interface (used to send our report to host)
  output reg in_ep_req = 0,
  input in_ep_grant,
  input in_ep_data_free,
  output reg in_ep_data_put = 0,
  output reg [7:0] in_ep_data = 0,
  output reg in_ep_data_done = 0,
  output in_ep_stall,
  input in_ep_acked
);

  assign out_ep_req = 1'b0;  assign out_ep_data_get = 1'b0;  assign out_ep_stall = 1'b0;  assign in_ep_stall = 1'b0;
  reg [31:0] p_val;
  reg [4:0] report_idx = 0;
  reg report_latched = 0;
  reg raw_mode = 0; // If 1, send single raw byte from p_val[7:0]

  always @(posedge clk) begin
    if (reset) begin
        in_ep_req <= 0;
        in_ep_data_put <= 0;
        in_ep_data_done <= 0;
        report_idx <= 0;
        report_latched <= 0;
        raw_mode <= 0;
    end else begin
        in_ep_data_put <= 0;
        in_ep_data_done <= 0;

        if (report_ready && !report_latched) begin
            p_val <= report_data;
            report_latched <= 1'b1;
            report_idx <= 0;
            in_ep_req <= 1'b1;
            raw_mode <= report_data[31]; // MSB = 1 means raw byte mode
        end else if (report_latched && !raw_mode && report_idx < 8) begin
            // Hex formatting mode: send 8 ASCII hex chars
            in_ep_req <= 1'b1;
            if (in_ep_grant && in_ep_data_free && !in_ep_data_put) begin
                in_ep_data <= (p_val[31:28] < 10) ? ("0" + p_val[31:28]) : ("A" + (p_val[31:28] - 10));
                p_val <= p_val << 4;
                in_ep_data_put <= 1'b1;
                report_idx <= report_idx + 1;
            end
        end else if (report_latched && !raw_mode && report_idx == 8) begin
            // Send \n after hex digits
            in_ep_req <= 1'b1;
            if (in_ep_grant && in_ep_data_free && !in_ep_data_put) begin
                in_ep_data <= 8'h0A; // \n
                in_ep_data_put <= 1'b1;
                report_idx <= 9;
            end
        end else if (report_latched && !raw_mode && report_idx == 9) begin
            // Done with hex formatting + \n
            if (in_ep_grant) begin
                in_ep_data_done <= 1'b1;
                in_ep_req <= 1'b0;
                report_idx <= 10;
                report_latched <= 0;
            end
        end else if (report_latched && raw_mode && report_idx == 0) begin
            // Raw byte mode: send single byte from p_val[7:0]
            in_ep_req <= 1'b1;
            if (in_ep_grant && in_ep_data_free && !in_ep_data_put) begin
                in_ep_data <= p_val[7:0];
                in_ep_data_put <= 1'b1;
                report_idx <= 1;
            end
        end else if (report_latched && raw_mode && report_idx == 1) begin
            // Done with raw byte
            if (in_ep_grant) begin
                in_ep_data_done <= 1'b1;
                in_ep_req <= 1'b0;
                report_idx <= 2;
                report_latched <= 0;
            end
        end
    end
  end
endmodule
