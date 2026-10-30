// BD wrapper for the M3 image: the M2b datapath *plus* F1 (MPU6050).
//
// Same reason as merged_top_bd.v: IP Integrator refuses a SystemVerilog file as a
// module reference, so the cell it instantiates must be plain Verilog.  This file
// is a copy of that shim with the F1 block added; the datapath instance below is
// character-for-character the M2b one, so the M2b behaviour is untouched.
//
// What is added:
//   * the camera-header SCCB bus (T10/T11) as an inout port pair;
//   * i2c_master + mpu6050_bringup + pose_fusion, clocked by the same 50 MHz
//     crystal as the datapath, so the pose tick and the frame tick are one counter;
//   * the 128-bit pose word handed to acq_axi_regs (independent 1 kHz channel).
//
// `hold` is tied to 0 here (there is no VIO in the PS image): the sequencer starts
// its 100 ms power-up wait immediately after reset.  A missing module therefore
// shows up as err_cnt climbing and pose_valid=false, which the page treats as
// "no attitude" and falls back to auto-spin -- it never blocks the scan.
module merged_top_bd_f1 (
    input  wire        sys_clk,
    input  wire        sys_rst_n,
    input  wire [9:0]  ad1_data,
    input  wire [9:0]  ad2_data,
    input  wire        ad1_otr,
    input  wire        ad2_otr,
    output wire        ad1_clk,
    output wire        ad2_clk,
    output wire        ad1_oe,
    output wire        ad2_oe,
    output wire        tx_burst,
    output wire [3:0]  lift_coils,
    output wire [3:0]  ball_coils,
    // readout taps to the AXI register block (passive observers)
    output wire [39:0] dbg_peak_word,
    output wire [55:0] dbg_cent_word,
    output wire [31:0] dbg_pose_rot,
    output wire [31:0] dbg_pose_lift,
    output wire        dbg_frame_done,
    // autonomous trigger from the AXI register block
    input  wire        ext_ctrl_sel,
    input  wire        ext_trig,
    input  wire        ext_tx_en,
    // ---- F1: MPU6050 on the camera header ----
    inout  wire        scl,          // T10
    inout  wire        sda,          // T11
    output wire [127:0] dbg_f1_pose_word,
    output wire         dbg_f1_pose_valid
);

    merged_top u_datapath (
        .sys_clk     (sys_clk),
        .sys_rst_n   (sys_rst_n),
        .ad1_data    (ad1_data),
        .ad2_data    (ad2_data),
        .ad1_otr     (ad1_otr),
        .ad2_otr     (ad2_otr),
        .ad1_clk     (ad1_clk),
        .ad2_clk     (ad2_clk),
        .ad1_oe      (ad1_oe),
        .ad2_oe      (ad2_oe),
        .tx_burst    (tx_burst),
        .lift_coils  (lift_coils),
        .ball_coils  (ball_coils),
        .dbg_peak_word  (dbg_peak_word),
        .dbg_cent_word  (dbg_cent_word),
        .dbg_pose_rot   (dbg_pose_rot),
        .dbg_pose_lift  (dbg_pose_lift),
        .dbg_frame_done (dbg_frame_done),
        .ext_ctrl_sel   (ext_ctrl_sel),
        .ext_trig       (ext_trig),
        .ext_tx_en      (ext_tx_en)
    );

    // ---------------------------------------------------------------- F1 block
    (* ASYNC_REG = "TRUE" *) reg [1:0] f1_rst_pipe;
    always @(posedge sys_clk) f1_rst_pipe <= {f1_rst_pipe[0], ~sys_rst_n};
    wire f1_rst = f1_rst_pipe[1];

    // free-running 50 MHz tick: the shared timebase of pose and frames
    reg [31:0] f1_tick;
    always @(posedge sys_clk) f1_tick <= f1_rst ? 32'd0 : (f1_tick + 32'd1);

    wire scl_i, sda_i, scl_oe, sda_oe;
    IOBUF scl_iobuf (.IO(scl), .I(1'b0), .O(scl_i), .T(~scl_oe));
    IOBUF sda_iobuf (.IO(sda), .I(1'b0), .O(sda_i), .T(~sda_oe));

    wire        m_start, m_stop, m_send, m_recv, m_ack;
    wire [7:0]  m_tx, m_rx;
    wire        m_ack_in, m_busy, m_done, m_err;
    wire [7:0]  who, pc_dbg, err_cnt;
    wire [15:0] ax, ay, az, gx, gy, gz;
    wire        sample_valid;
    wire [31:0] sample_tick;

    i2c_master #(
        .CLK_HZ (50_000_000),
        .SCL_HZ (400_000)              // 14 B burst = 337 us -> 1 kHz is possible
    ) u_i2c (
        .clk (sys_clk), .rst (f1_rst),
        .start (m_start), .stop (m_stop), .send (m_send), .recv (m_recv),
        .ack_out (m_ack), .tx_data (m_tx), .rx_data (m_rx),
        .ack_in (m_ack_in), .busy (m_busy), .done (m_done), .err (m_err),
        .scl_oe (scl_oe), .sda_oe (sda_oe), .scl_i (scl_i), .sda_i (sda_i)
    );

    mpu6050_bringup #(
        .PWR_CYCLES    (5_000_000),
        .WAKE_CYCLES   (500_000),
        .SAMPLE_CYCLES (50_000),       // 1 ms
        .RETRY_CYCLES  (5_000_000)
    ) u_mpu (
        .clk (sys_clk), .rst (f1_rst), .hold (1'b0),
        .m_start (m_start), .m_stop (m_stop), .m_send (m_send), .m_recv (m_recv),
        .m_ack (m_ack), .m_tx (m_tx), .m_rx (m_rx), .m_ack_in (m_ack_in),
        .m_busy (m_busy), .m_done (m_done), .m_err (m_err),
        .who (who), .pc_dbg (pc_dbg), .err_cnt (err_cnt),
        .ax (ax), .ay (ay), .az (az), .gx (gx), .gy (gy), .gz (gz),
        .free_tick (f1_tick), .sample_valid (sample_valid), .sample_tick (sample_tick)
    );

    wire signed [15:0] roll, pitch, yaw;
    wire [7:0]  pseq, pflags;
    wire [31:0] pose_tick;

    pose_fusion u_pose (
        .clk (sys_clk), .rst (f1_rst),
        .sample_valid (sample_valid), .tick (sample_tick),
        .ax (ax), .ay (ay), .az (az), .gx (gx), .gy (gy), .gz (gz),
        .err_cnt (err_cnt), .bus_stuck (m_err),
        .roll (roll), .pitch (pitch), .yaw (yaw),
        .seq (pseq), .pose_tick (pose_tick), .pose_valid (dbg_f1_pose_valid),
        .flags (pflags), .sample_cnt (), .state_dbg ()
    );

    // Pose word, exactly the layout in F1P §12.2 / acq_axi_regs:
    //   [127:112] magic  [111:104] seq  [103:96] flags  [95:64] tick
    //   [63:48]   roll   [47:32]   pitch[31:16] yaw    [15:0]  err_cnt
    // 2026-10-27: err_cnt is 8 bit here but the contract (and the PC/firmware
    // readers) reserve 16 for it.  Concatenating 120 bits into a 128-bit wire
    // zero-padded the TOP, which shifted the whole word right by 8 -- the PL was
    // sampling fine (seq advancing) while every reader saw magic 0x004D instead of
    // 0x4D50 and rejected the sample.  Pad err_cnt explicitly.
    assign dbg_f1_pose_word = {16'h4D50, pseq, pflags, pose_tick,
                               roll, pitch, yaw, 8'd0, err_cnt};

endmodule
