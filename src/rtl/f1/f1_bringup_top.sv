// F1 bring-up top: MPU6050 on the camera-header SCCB bus (SCL=T10, SDA=T11),
// now with pose_fusion behind it.
//
// VIO layout (probes are read over JTAG; nothing here touches the AXI map yet):
//   probe_in0 [127:0]  pose word:
//        127:112 magic 0x4D50  111:104 seq      103:96 flags
//         95:64  tick (50 MHz)  63:48  roll     47:32 pitch  31:16 yaw  15:0 err_cnt
//   probe_in1 [47:0]   raw {ax,ay,az} so the wiring/axis check of the design doc
//                      (rest: 0 0 8192) still works before the filter is trusted
//   probe_out0         hold (initial 1): keeps the sequencer parked, bus released,
//                      so the first read is a pure line check
// Flags: bit0 pose valid, bit1 init done (32 samples of accel-only), bit2 i2c err,
//        bit3 bus stuck (i2c_master recovered a stuck bus).
`timescale 1ns / 1ps
module f1_bringup_top (
    input  wire sys_clk,    // U18, 50 MHz
    input  wire sys_rst_n,  // N16, active low
    inout  wire scl,        // T10
    inout  wire sda         // T11
);
    reg [1:0] rst_sync;
    always @(posedge sys_clk) rst_sync <= {rst_sync[0], ~sys_rst_n};
    wire rst = rst_sync[1];

    // free-running 50 MHz tick: the shared timebase of pose and (later) frames
    reg [31:0] tick;
    always @(posedge sys_clk) tick <= rst ? 32'd0 : (tick + 32'd1);

    wire scl_i, sda_i, scl_oe, sda_oe;
    IOBUF scl_iobuf (.IO(scl), .I(1'b0), .O(scl_i), .T(~scl_oe));
    IOBUF sda_iobuf (.IO(sda), .I(1'b0), .O(sda_i), .T(~sda_oe));

    wire        m_start, m_stop, m_send, m_recv, m_ack;
    wire [7:0]  m_tx, m_rx;
    wire        m_ack_in, m_busy, m_done, m_err;

    wire [7:0]  who, pc_dbg, err_cnt;
    wire [15:0] ax, ay, az, gx, gy, gz;
    wire        hold;

    i2c_master #(
        .CLK_HZ (50_000_000),
        // 400 kHz: at 100 kHz the 14-byte burst costs 1.36 ms, so a 1 kHz sample
        // rate is physically impossible.  400 kHz leaves ~34% bus load.
        .SCL_HZ (400_000)
    ) u_i2c (
        .clk     (sys_clk),
        .rst     (rst),
        .start   (m_start),
        .stop    (m_stop),
        .send    (m_send),
        .recv    (m_recv),
        .ack_out (m_ack),
        .tx_data (m_tx),
        .rx_data (m_rx),
        .ack_in  (m_ack_in),
        .busy    (m_busy),
        .done    (m_done),
        .err     (m_err),
        .scl_oe  (scl_oe),
        .sda_oe  (sda_oe),
        .scl_i   (scl_i),
        .sda_i   (sda_i)
    );

    wire        sample_valid;
    wire [31:0] sample_tick;

    mpu6050_bringup #(
        .PWR_CYCLES    (5_000_000),  // 100 ms
        .WAKE_CYCLES   (500_000),    // 10 ms
        .SAMPLE_CYCLES (50_000),     // 1 ms
        .RETRY_CYCLES  (5_000_000)
    ) u_mpu (
        .clk      (sys_clk),
        .rst      (rst),
        .hold     (hold),
        .m_start  (m_start),
        .m_stop   (m_stop),
        .m_send   (m_send),
        .m_recv   (m_recv),
        .m_ack    (m_ack),
        .m_tx     (m_tx),
        .m_rx     (m_rx),
        .m_ack_in (m_ack_in),
        .m_busy   (m_busy),
        .m_done   (m_done),
        .m_err    (m_err),
        .who      (who),
        .pc_dbg   (pc_dbg),
        .err_cnt  (err_cnt),
        .ax       (ax),
        .ay       (ay),
        .az       (az),
        .gx       (gx),
        .gy       (gy),
        .gz       (gz),
        .free_tick    (tick),
        .sample_valid (sample_valid),
        .sample_tick  (sample_tick)
    );

    wire signed [15:0] roll, pitch, yaw;
    wire [7:0]  pseq, pflags;
    wire [31:0] pose_tick, sample_cnt;
    wire        pose_valid;

    pose_fusion u_pose (
        .clk          (sys_clk),
        .rst          (rst),
        .sample_valid (sample_valid),
        .tick         (sample_tick),
        .ax           (ax), .ay (ay), .az (az),
        .gx           (gx), .gy (gy), .gz (gz),
        .err_cnt      (err_cnt),
        .bus_stuck    (m_err),
        .roll         (roll), .pitch (pitch), .yaw (yaw),
        .seq          (pseq), .pose_tick (pose_tick), .pose_valid (pose_valid),
        .flags        (pflags), .sample_cnt (sample_cnt), .state_dbg ()
    );

    wire [127:0] probe0;
    assign probe0 = {16'h4D50, pseq, pflags, pose_tick, roll, pitch, yaw, err_cnt};

    wire [47:0] probe1 = {ax, ay, az};

    vio_f1 u_vio (
        .clk        (sys_clk),
        .probe_in0  (probe0),
        .probe_in1  (probe1),
        .probe_out0 (hold)
    );
endmodule
