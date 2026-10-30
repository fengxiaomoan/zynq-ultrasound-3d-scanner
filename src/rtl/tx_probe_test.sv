`timescale 1ns/1ps
// Single-shot digital waveform only. All controls synchronous to clk.
// No pin/voltage claim: board reset and analog driver need separate validation.
module tx_probe_test #(
 parameter integer CLK_HZ=50000000,
 parameter integer TX_HZ=1000000,
 parameter integer CYCLES=8
)(input wire clk,rst_n,arm,fire,
 output reg tx, busy, done, start_marker);
 localparam integer HALF=CLK_HZ/(2*TX_HZ);
 localparam integer HALF_W=(HALF<=1)?1:$clog2(HALF);
 localparam integer EDGE_W=(2*CYCLES<=1)?1:$clog2(2*CYCLES);
 reg [HALF_W-1:0] count;
 reg [EDGE_W-1:0] half_index;
 reg fire_d;
 // synthesis translate_off
 initial begin
 if(TX_HZ<=0 || HALF<2 || CLK_HZ!=HALF*2*TX_HZ || CYCLES<1)
 $fatal(1,"Invalid TX timing parameters");
 end
 // synthesis translate_on
 always @(posedge clk) begin
 if(!rst_n) begin
 tx<=0;busy<=0;done<=0;start_marker<=0;count<=0;half_index<=0;fire_d<=1;
 end else begin
 fire_d<=fire; done<=0;start_marker<=0;
 if(!arm) begin tx<=0;busy<=0;count<=0;half_index<=0;end
 else if(busy) begin
 if(count==HALF-1) begin
 count<=0;
 if(half_index==2*CYCLES-1) begin tx<=0;busy<=0;done<=1;end
 else begin tx<=~tx;half_index<=half_index+1'b1;end
 end else count<=count+1'b1;
 end else if(fire && !fire_d) begin
 tx<=1;busy<=1;start_marker<=1;count<=0;half_index<=0;
 end else tx<=0;
 end
 end
endmodule
