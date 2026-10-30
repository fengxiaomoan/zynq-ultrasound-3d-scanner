`timescale 1ns/1ps
module ultrasound_test_core #(
 parameter integer FRAME_CYCLES=8192,
 parameter integer TX_LOCKOUT_CYCLES=500000
)(input wire clk,rst_n,input wire [1:0] ctrl,
 input wire [9:0] ad1_data,ad2_data,input wire ad1_otr,ad2_otr,
 output reg adc_clock,output wire tx_burst,
 output reg [9:0] sample1,sample2,output reg signed [10:0] diff,
 output reg [1:0] sample_otr,output reg sample_valid,
 output reg capture_start,frame_active,frame_done,
 output reg [12:0] frame_index,output reg [15:0] frame_count,
 output wire tx_busy,output reg rejected);
 reg [3:0] adc_phase;
 reg go_d;
 reg tx_for_frame;
 reg [18:0] lockout;
 wire tx_done,tx_marker;
 tx_probe_test tx(.clk(clk),.rst_n(rst_n),.arm(ctrl[1]),
 .fire(capture_start && tx_for_frame),.tx(tx_burst),.busy(tx_busy),
 .done(tx_done),.start_marker(tx_marker));
 // Always clock ADC while out of reset; capture OLD output at next ADC rising edge.
 // New ADC data appears after its tOD, not at this system sampling edge.
 always @(posedge clk) begin
 if(!rst_n) begin
 adc_clock<=0;adc_phase<=0;sample1<=0;sample2<=0;diff<=0;
 sample_otr<=0;sample_valid<=0;
 end else begin
 sample_valid<=0;
 if(adc_phase==9) adc_phase<=0;else adc_phase<=adc_phase+1'b1;
 if(adc_phase==0) begin
 adc_clock<=1;sample1<=ad1_data;sample2<=ad2_data;
 diff<=$signed({1'b0,ad1_data})-$signed({1'b0,ad2_data});
 sample_otr<={ad2_otr,ad1_otr};sample_valid<=1;
 end else if(adc_phase==5) adc_clock<=0;
 end
 end
 always @(posedge clk) begin
 if(!rst_n) begin
 go_d<=1;tx_for_frame<=0;capture_start<=0;frame_active<=0;frame_done<=0;
 frame_index<=0;frame_count<=0;lockout<=0;rejected<=0;
 end else begin
 go_d<=ctrl[0];capture_start<=0;frame_done<=0;
 if(lockout!=0)lockout<=lockout-1'b1;
 if(ctrl[0] && !go_d) begin
 if(!frame_active && !tx_busy && (!ctrl[1] || lockout==0)) begin
 capture_start<=1;tx_for_frame<=ctrl[1];frame_active<=1;frame_index<=0;
 frame_count<=frame_count+1'b1;rejected<=0;
 if(ctrl[1])lockout<=TX_LOCKOUT_CYCLES;
 end else rejected<=1;
 end
 if(frame_active) begin
 if(frame_index==FRAME_CYCLES-1) begin frame_active<=0;frame_done<=1;end
 else frame_index<=frame_index+1'b1;
 end
 end
 end
 // synthesis translate_off
 initial begin
 if(FRAME_CYCLES<2 || FRAME_CYCLES>8192 || TX_LOCKOUT_CYCLES<400 || TX_LOCKOUT_CYCLES>524287)
 $fatal(1,"Invalid frame/lockout configuration");
 end
 // synthesis translate_on
endmodule
