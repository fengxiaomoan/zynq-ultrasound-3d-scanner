// Thin Verilog wrapper so the block design can reference the datapath.
//
// Why this file exists: IP Integrator refuses a SystemVerilog file as a module
// reference ("filemgmt 56-195"), and merged_top.sv is SystemVerilog.  This shell
// is plain Verilog, ports are identical to merged_top's, so merged_top.xdc keeps
// matching by name and the verified logic inside is untouched.
//
// Merged_top stays clocked by the board's 50 MHz crystal (sys_clk).  Nothing here
// crosses into the PS's FCLK domain; M1b only proves the two coexist in one image.
module merged_top_bd (
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
    input  wire        ext_tx_en
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

endmodule
