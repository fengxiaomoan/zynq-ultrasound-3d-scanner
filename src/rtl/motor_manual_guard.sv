`timescale 1ns/1ps
// ctrl[0]=arm, [1]=go, [2]=axis (0 lift,1 ball), [3]=direction, [4]=stop.
// One command per arm cycle. Arm -> observe go=0 -> go=1. Both axes interlocked.
module motor_manual_guard(input wire clk,rst_n,input wire [4:0] ctrl,
 input wire [1:0] busy,output reg [1:0] start,output reg [1:0] direction,
 output wire [1:0] stop);
 reg ready,fired;
 assign stop={2{!ctrl[0] || ctrl[4]}};
 always @(posedge clk) begin
 if(!rst_n) begin start<=0;direction<=0;ready<=0;fired<=0;end
 else begin
 start<=0;
 if(!ctrl[0] || ctrl[4]) begin ready<=0;fired<=0;end
 else if(!fired) begin
 if(!ctrl[1]) ready<=1;
 else if(ready && busy==0 && start==0) begin
 direction<={2{ctrl[3]}};
 start<=ctrl[2] ? 2'b10 : 2'b01;
 fired<=1;ready<=0;
 end
 end
 end
 end
endmodule
