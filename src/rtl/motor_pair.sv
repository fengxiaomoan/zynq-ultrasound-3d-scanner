`timescale 1ns/1ps
// Two independent axes; bit 0 lift, bit 1 ball rotation.
// start is a one-cycle pulse accepted only while the selected axis is idle.
module motor_pair (
 input wire clk, rst_n,
 input wire [1:0] start, direction, stop, release_coils, limit_neg, limit_pos,
 input wire [31:0] lift_steps, ball_steps, lift_period, ball_period,
 input wire [15:0] lift_ramp, ball_ramp, lift_delta, ball_delta,
 output wire [1:0] busy, done, fault, step_tick,
 output wire [3:0] lift_coils, ball_coils,
 output wire signed [63:0] lift_position, ball_position
);
 stepper_axis lift(clk,rst_n,start[0],direction[0],stop[0],release_coils[0],
 limit_neg[0],limit_pos[0],lift_steps,lift_period,lift_ramp,lift_delta,
 busy[0],done[0],fault[0],step_tick[0],lift_coils,lift_position);
 stepper_axis ball(clk,rst_n,start[1],direction[1],stop[1],release_coils[1],
 limit_neg[1],limit_pos[1],ball_steps,ball_period,ball_ramp,ball_delta,
 busy[1],done[1],fault[1],step_tick[1],ball_coils,ball_position);
endmodule
