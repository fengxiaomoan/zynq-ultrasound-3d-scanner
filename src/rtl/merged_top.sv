`timescale 1ns/1ps
// Merged build: 13号 acquisition + dual-axis stepper + pose latch.
//
//   * acquisition path is the validated 13号 core, unchanged (same ports, same
//     ILA probe order, same VIO control word);
//   * motor path is the validated jog build (arm/go, step envelope, watchdog);
//   * pose latch samples both step counters on the capture_start rising edge,
//     so a frame carries the commanded pose at the instant of acquisition
//     instead of a host timestamp.
//
// The two VIO cores keep the interfaces independent: `control` stays 2-bit as
// the existing capture tools expect, `motors` carries the jog registers.
module merged_top (
 input wire sys_clk,
 input wire sys_rst_n,
 input wire [9:0] ad1_data,
 input wire [9:0] ad2_data,
 input wire ad1_otr,
 input wire ad2_otr,
 output wire ad1_clk,
 output wire ad2_clk,
 output wire ad1_oe,
 output wire ad2_oe,
 output wire tx_burst,
 output wire [3:0] lift_coils,
 output wire [3:0] ball_coils,
 // ---- readout taps for the PS path (added 2026-10-27 for M1c) -------------
 // Passive observers only: nothing inside the datapath reads them back, so the
 // captured behaviour is unchanged.  The c1-era source (before these taps were
 // added) is frozen at fpga/ps/merged_top_c1_frozen.sv, sha256
 // 3779A309DE0E86A977FC2B41BFDBF12850FDFF5E3B89FA633A5928DCD0BCBEB8, so the
 // evidence bitstream fpga_dsp_c1 stays reproducible from source.
 output wire [39:0] dbg_peak_word,
 output wire [55:0] dbg_cent_word,
 output wire [31:0] dbg_pose_rot,
 output wire [31:0] dbg_pose_lift,
 output wire        dbg_frame_done,
 // ---- autonomous trigger from the AXI block (M2a) -------------------------
 // ext_ctrl_sel = 0 keeps today's behaviour (VIO drives ctrl) so this file can
 // still be exercised exactly as before; 1 lets the PL clock the acquisition.
 input  wire        ext_ctrl_sel,
 input  wire        ext_trig,
 input  wire        ext_tx_en
);
 (* ASYNC_REG="TRUE" *) reg [1:0] reset_pipe;
 always @(posedge sys_clk or negedge sys_rst_n)
  if(!sys_rst_n) reset_pipe<=0; else reset_pipe<={reset_pipe[0],1'b1};
 wire rst_n = reset_pipe[1];

 // ------------------------------------------------------------- acquisition
 // ctrl[0] = capture trigger (rising edge), ctrl[1] = TX enable.
 // Source is the VIO by default; ext_ctrl_sel hands it to the AXI block so the
 // PL can run frames without a host round trip per frame (M2a).
 wire [1:0] ctrl_vio;
 wire [1:0] ctrl = ext_ctrl_sel ? {ext_tx_en, ext_trig} : ctrl_vio;
 wire adc_clock, sample_valid, capture_start, frame_active, frame_done;
 wire tx_busy, rejected;
 wire [9:0] sample1, sample2;
 wire signed [10:0] diff;
 wire [1:0] sample_otr;
 wire [12:0] frame_index;
 wire [15:0] frame_count;
 wire [6:0] status = {rejected, sample_valid, sample_otr, frame_active,
                      tx_busy, rst_n};

 assign ad1_clk = adc_clock;
 assign ad2_clk = adc_clock;
 assign ad1_oe = 0;
 assign ad2_oe = 0;

 ultrasound_test_core acq (
  .clk(sys_clk), .rst_n(rst_n), .ctrl(ctrl),
  .ad1_data(ad1_data), .ad2_data(ad2_data),
  .ad1_otr(ad1_otr), .ad2_otr(ad2_otr),
  .adc_clock(adc_clock), .tx_burst(tx_burst),
  .sample1(sample1), .sample2(sample2), .diff(diff),
  .sample_otr(sample_otr), .sample_valid(sample_valid),
  .capture_start(capture_start), .frame_active(frame_active),
  .frame_done(frame_done), .frame_index(frame_index),
  .frame_count(frame_count), .tx_busy(tx_busy), .rejected(rejected));

 // ------------------------------------------------------------------ motors
 wire [4:0]  m_ctrl;
 wire [17:0] m_steps, m_limit;
 wire [31:0] m_period;
 wire [15:0] m_ramp, m_delta;
 wire        m_kick;
 wire [1:0]  m_busy, m_done, m_fault, m_status;
 wire signed [63:0] lift_position, ball_position;
 wire [1:0]  m_start, m_direction, m_stop;
 reg [31:0] pose_lift, pose_rot;

 localparam [31:0] PERIOD_MIN = 32'd50000;
 localparam [17:0] STEPS_MAX  = 18'd120000;
 localparam [31:0] WD_CYCLES  = 32'd100_000_000;

 wire cmd_ok = (m_steps <= m_limit) && (m_steps <= STEPS_MAX)
               && (m_period >= PERIOD_MIN);

 reg cmd_error;
 always @(posedge sys_clk) begin
  if(!rst_n) cmd_error <= 1'b0;
  else if(!m_ctrl[0]) cmd_error <= 1'b0;
  else if((m_start != 2'b00) && !cmd_ok) cmd_error <= 1'b1;
 end

 reg kick_q;
 reg [31:0] wd_cnt;
 reg wd_fault;
 always @(posedge sys_clk) begin
  if(!rst_n) begin kick_q<=0; wd_cnt<=0; wd_fault<=0; end
  else begin
   kick_q <= m_kick;
   if(!m_ctrl[0]) wd_fault <= 1'b0;
   else if(m_kick != kick_q) wd_cnt <= 0;
   else if(m_busy != 2'b00) begin
    if(wd_cnt >= WD_CYCLES) wd_fault <= 1'b1;
    else wd_cnt <= wd_cnt + 1'b1;
   end else wd_cnt <= 0;
  end
 end

 wire [4:0] guard_ctrl = {m_ctrl[4] | wd_fault | cmd_error, m_ctrl[3:0]};
 wire [31:0] cmd_steps  = cmd_ok ? {14'd0, m_steps} : 32'd0;
 wire [31:0] cmd_period = (m_period < PERIOD_MIN) ? PERIOD_MIN : m_period;

 motor_manual_guard guard (
  .clk(sys_clk), .rst_n(rst_n), .ctrl(guard_ctrl), .busy(m_busy),
  .start(m_start), .direction(m_direction), .stop(m_stop));

 motor_pair motors (
  .clk(sys_clk), .rst_n(rst_n),
  .start(m_start), .direction(m_direction), .stop(m_stop),
  .release_coils(2'b00), .limit_neg(2'b00), .limit_pos(2'b00),
  .lift_steps(cmd_steps), .ball_steps(cmd_steps),
  .lift_period(cmd_period), .ball_period(cmd_period),
  .lift_ramp(m_ramp), .ball_ramp(m_ramp),
  .lift_delta(m_delta), .ball_delta(m_delta),
  .busy(m_busy), .done(m_done), .fault(m_fault), .step_tick(),
  .lift_coils(lift_coils), .ball_coils(ball_coils),
  .lift_position(lift_position), .ball_position(ball_position));

 assign m_status = {cmd_error, wd_fault};

 // -------------------------------------------------------------- pose latch
 reg capture_start_q;
 always @(posedge sys_clk) begin
  if(!rst_n) begin
   capture_start_q <= 1'b0;
   pose_lift <= 32'd0;
   pose_rot  <= 32'd0;
  end else begin
   capture_start_q <= capture_start;
   if(capture_start && !capture_start_q) begin
    pose_lift <= lift_position[31:0];
    pose_rot  <= ball_position[31:0];
   end
  end
 end

 // -------------------------------------------------------------- peak DSP
 // 1 MHz I/Q demod -> envelope -> windowed peak; the result is latched in a
 // 40-bit word so the host reads one value instead of uploading an ILA frame.
 // Word = {valid, frame_count[12:0], idx[9:0], amp[15:0]} so the host can prove
 // that the word belongs to the same frame as the ILA capture it compares with.
 wire [39:0] peak_word;
 wire        peak_strobe;
 wire [14:0] peak_idx;
 wire [15:0] peak_amp;
 wire [15:0] dsp_sid, dsp_amp;

 peak_dsp dsp (
  .clk(sys_clk), .rst_n(rst_n),
  .sample_valid(sample_valid), .diff(diff),
  .capture_start(capture_start), .frame_count(frame_count),
  .peak_word(peak_word), .peak_strobe(peak_strobe),
  .peak_idx(peak_idx), .peak_amp(peak_amp),
  .sid_o(dsp_sid), .amp_o(dsp_amp));

 // ------------------------------------------------------------ C1: centroid
 // Window centroid of the same envelope stream, on its own probe.  The 40-bit
 // word above is P1.1-verified and is deliberately left untouched, so the old
 // bit-exact evidence and scripts keep working.
 //   cent_word = {valid, idx[9:0], sum_w[17:0], sum_kw[26:0]}   56 bit
 wire [55:0] cent_word;
 wire        cent_valid;
 wire [9:0]  cent_idx;
 wire [17:0] cent_sum_w;
 wire [26:0] cent_sum_kw;

 peak_centroid cent (
  .clk(sys_clk), .rst_n(rst_n),
  .capture_start(capture_start), .sample_valid(sample_valid),
  .sid(dsp_sid), .amp(dsp_amp),
  .cent_valid(cent_valid), .cent_idx(cent_idx),
  .cent_sum_w(cent_sum_w), .cent_sum_kw(cent_sum_kw));

 // cent_valid is a one-clock (20 ns) pulse.  A VIO input probe is sampled
 // asynchronously by the debug hub, so that pulse is almost never observed
 // (measured on the board 2026-10-26: cent_valid read 0 on all 4 rounds while
 // idx/sum_w/sum_kw were bit-exact).  Hold it until the next frame, exactly like
 // the 40-bit peak word, so the word is self-describing whenever it is read.
 reg cent_valid_hold;
 always @(posedge sys_clk) begin
  if(!rst_n || capture_start) cent_valid_hold <= 1'b0;
  else if(cent_valid)         cent_valid_hold <= 1'b1;
 end

 assign cent_word = {cent_valid_hold, cent_idx, cent_sum_w, cent_sum_kw};

 // -------------------------------------------------------------------- VIOs
 ultrasound_vio control (
  .clk(sys_clk), .probe_out0(ctrl_vio),
  .probe_in0(status), .probe_in1(frame_count));

 merged_vio motors_vio (
  .clk(sys_clk),
  .probe_out0(m_ctrl),
  .probe_out1(m_steps),
  .probe_out2(m_limit),
  .probe_out3(m_period),
  .probe_out4(m_ramp),
  .probe_out5(m_delta),
  .probe_out6(m_kick),
  .probe_in0(m_busy),
  .probe_in1(m_done),
  .probe_in2(m_fault),
  .probe_in3(m_status),
  .probe_in4(lift_position[31:0]),
  .probe_in5(ball_position[31:0]),
  .probe_in6(pose_lift),
  .probe_in7(pose_rot),
  .probe_in8(peak_word),
  .probe_in9(cent_word));

 // --------------------------------------------------------------------- ILA
 // Probe order and widths are identical to the 13号 build, so the existing
 // capture tools and profile_13.json decode unchanged.
 ultrasound_ila scope (
  .clk(sys_clk),
  .probe0(sample1), .probe1(sample2), .probe2(diff), .probe3(sample_otr),
  .probe4(tx_burst), .probe5(capture_start), .probe6(frame_active),
  .probe7(frame_index), .probe8(sample_valid), .probe9(rst_n));

 // ---------------------------------------------------------- PS readout taps
 assign dbg_peak_word  = peak_word;
 assign dbg_cent_word  = cent_word;
 assign dbg_pose_rot   = pose_rot;
 assign dbg_pose_lift  = pose_lift;
 assign dbg_frame_done = frame_done;
endmodule

