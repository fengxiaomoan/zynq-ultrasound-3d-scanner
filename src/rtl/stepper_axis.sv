`timescale 1ns/1ps
// All inputs synchronous to clk. rst_n synchronous active low.
module stepper_axis (
 input wire clk, rst_n,
 input wire start, direction, stop, release_coils,
 input wire limit_neg, limit_pos,
 input wire [31:0] steps, start_period,
 input wire [15:0] ramp_steps, period_delta,
 output reg busy, done, fault, step_tick,
 output wire [3:0] coils,
 output reg signed [63:0] position
);
 reg [2:0] phase;
 reg energized, dir_q;
 reg [31:0] total, issued, timer, period_q;
 reg [15:0] ramp_q, delta_q;
 wire [31:0] ramp_drop = {16'b0,ramp_steps} * {16'b0,period_delta};
 function automatic [3:0] pattern(input [2:0] i);
 case(i)
 0:pattern=4'b0001; 1:pattern=4'b0011;
 2:pattern=4'b0010; 3:pattern=4'b0110;
 4:pattern=4'b0100; 5:pattern=4'b1100;
 6:pattern=4'b1000; 7:pattern=4'b1001;
 endcase
 endfunction
 function automatic [31:0] interval_for(input [31:0] index);
 reg [31:0] depth;
 begin
 depth=index;
 if(total-1-index < depth) depth=total-1-index;
 if(depth > {16'b0,ramp_q}) depth={16'b0,ramp_q};
 interval_for=period_q-depth*{16'b0,delta_q};
 end
 endfunction
 assign coils = energized ? pattern(phase) : 4'b0000;
 always @(posedge clk) begin
 if(!rst_n) begin
 phase<=0; energized<=0; dir_q<=0; total<=0; issued<=0;
 timer<=0; period_q<=0; ramp_q<=0; delta_q<=0;
 busy<=0; done<=0; fault<=0; step_tick<=0; position<=0;
 end else begin
 done<=0; step_tick<=0;
 if(release_coils || stop) begin
 if(busy) begin busy<=0; fault<=1; end
 if(release_coils) energized<=0;
 end else if(busy) begin
 if((dir_q && limit_pos) || (!dir_q && limit_neg)) begin
 busy<=0; fault<=1;
 end else if(timer>1) timer<=timer-1;
 else begin
 phase<=dir_q ? phase+3'd1 : phase-3'd1;
 position<=dir_q ? position+64'sd1 : position-64'sd1;
 step_tick<=1;
 issued<=issued+1;
 if(issued==total-1) begin busy<=0; done<=1; end
 else timer<=interval_for(issued+1);
 end
 end else if(start) begin
 fault<=0;
 if(steps==0) done<=1;
 else if(start_period<2 || ramp_drop>=start_period-1 ||
         (direction && limit_pos) || (!direction && limit_neg)) fault<=1;
 else begin
 total<=steps; issued<=0; dir_q<=direction;
 period_q<=start_period; ramp_q<=ramp_steps; delta_q<=period_delta;
 // Energize existing phase and wait full initial interval before first step.
 energized<=1; timer<=start_period; busy<=1;
 end
 end
 end
 end
endmodule
