`timescale 1ns/1ps
// AXI4-Lite readout of the per-frame DSP words (M1c).
//
// Purpose: prove that the PS can read the SAME frame the acquisition core
// produced, over AXI, and get bit-identical numbers.  Frames are still triggered
// by the host over VIO (exactly as today), so this block is a passive observer:
//   - it must not disturb the datapath (no writes into merged_top);
//   - it must not lose a frame silently (a sequence counter exposes gaps).
//
// Record = {seq[15:0], pose_rot[31:0], pose_lift[31:0], peak_word[39:0], cent_word[55:0]}
//        = 176 bit, latched on frame_done in the sys_clk domain.
//
// Clocking: the datapath runs on the board's 50 MHz crystal (clk), the AXI side on
// the PS FCLK (aclk).  They are unrelated 50 MHz clocks, so the payload crosses by
// a toggle handshake: latch payload, then flip tog; the aclk side sees the flip
// through a 2-FF synchroniser and samples the payload two cycles later -- by then
// it has been stable for >= 3 sys_clk edges.
//
// Register map (byte offsets, 32-bit):
//   0x00 STATUS  [0] new record pending, [1] previous record was overwritten
//                before the PS read it, [15:8] missed count, [31:16] live seq
//   0x04 SEQ
//   0x08 PEAK_LO                    0x0C PEAK_HI  (40 bit total)
//   0x10 CENT_LO                    0x14 CENT_HI  (56 bit total)
//   0x18 POSE_ROT                   0x1C POSE_LIFT
//   0x20 ACK     write 1 to clear the pending flag and the missed bit
//   0x24 CTRL    [0] arm  [16] sel_ext
//   0x28 PERIOD_MS
//   0x30 POSE_YAW_ERR               (F1, 2026-10-27: 128-bit pose word)
//   0x34 POSE_ROLL_PITCH
//   0x38 POSE_TICK
//   0x3C POSE_HDR                   {magic 0x4D50, seq[7:0], flags[7:0]}
// Reads of 0x04..0x1F always return the last captured frame, so a status read
// followed by a data read is coherent as long as ACK comes afterwards.
//
// The pose word is a SECOND, independent channel (1 kHz) with its own toggle: it
// must not share the frame payload, which is latched once per frame (90 Hz).  A
// reader that wants a coherent attitude reads 0x3C, then 0x30..0x38, then 0x3C
// again and accepts the snapshot only if the two seq values match.
module acq_axi_regs #(
    parameter integer C_S_AXI_ADDR_WIDTH = 6,
    parameter integer C_S_AXI_DATA_WIDTH = 32,
    // ms -> cycles.  50 000 for the real 50 MHz design; the testbench shrinks it
    // so a 10 ms period does not cost 500 000 simulated cycles per frame.
    parameter integer CYCLES_PER_MS = 50000
) (
    // ---- AXI4-Lite slave (PS FCLK domain) ----
    input  wire                                   aclk,
    input  wire                                   aresetn,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]          s_axi_awaddr,
    input  wire                                   s_axi_awvalid,
    output wire                                   s_axi_awready,
    input  wire [C_S_AXI_DATA_WIDTH-1:0]          s_axi_wdata,
    input  wire [C_S_AXI_DATA_WIDTH/8-1:0]        s_axi_wstrb,
    input  wire                                   s_axi_wvalid,
    output wire                                   s_axi_wready,
    output wire [1:0]                             s_axi_bresp,
    output reg                                    s_axi_bvalid,
    input  wire                                   s_axi_bready,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]          s_axi_araddr,
    input  wire                                   s_axi_arvalid,
    output wire                                   s_axi_arready,
    output reg  [C_S_AXI_DATA_WIDTH-1:0]          s_axi_rdata,
    output wire [1:0]                             s_axi_rresp,
    output reg                                    s_axi_rvalid,
    input  wire                                   s_axi_rready,

    // ---- datapath domain (board 50 MHz crystal) ----
    input  wire                                   clk,
    input  wire                                   rst_n,
    input  wire                                   frame_done,
    input  wire [39:0]                            peak_word,
    input  wire [55:0]                            cent_word,
    input  wire [31:0]                            pose_rot,
    input  wire [31:0]                            pose_lift,

    // ---- F1 pose word (128 bit), datapath domain, 1 kHz ----------------------
    // {magic 0x4D50, seq[7:0], flags[7:0], tick[31:0], roll[15:0], pitch[15:0],
    //  yaw[15:0], err_cnt[15:0]}  -- see pose_fusion.sv
    input  wire [127:0]                           f1_pose_word,
    input  wire                                   f1_pose_valid,

    // ---- autonomous frame trigger (M2a) ----
    // The host can only trigger ~30 frames/s because every trigger costs a JTAG
    // round trip.  These three outputs let the PL clock the acquisition core
    // instead: o_sel_ext switches merged_top's ctrl source to this block, o_trig
    // is one pulse per period and o_tx_en keeps TX armed.
    //
    // Period floor is NOT set here on purpose: TX_LOCKOUT_CYCLES in
    // ultrasound_test_core (500 000 cycles = 10 ms) already refuses frames faster
    // than 100 Hz, and silently clamping here would hide that ceiling.
    output wire                                   o_trig,
    output wire                                   o_tx_en,
    output wire                                   o_sel_ext
);

    assign s_axi_awready = 1'b1;
    assign s_axi_wready  = 1'b1;
    assign s_axi_arready = 1'b1;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;

    // ------------------------------------------------------------ producer side
    reg [175:0] payload;
    reg [15:0]  seq;
    reg         tog;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            payload <= 176'd0;
            seq     <= 16'd0;
            tog     <= 1'b0;
        end else if (frame_done) begin
            payload <= {seq, pose_rot, pose_lift, peak_word, cent_word};
            seq     <= seq + 16'd1;
            // the payload and the toggle change on the same edge, so the toggle is
            // already visible 2 aclk cycles before the payload can be sampled
            tog     <= ~tog;
        end
    end

    // --------------------------------------------------- F1 pose word producer
    // Independent toggle: the attitude updates at 1 kHz, the frame payload at
    // 90 Hz.  Sharing one toggle would make each stream overwrite the other.
    reg [127:0] f1_payload;
    reg         f1_tog;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            f1_payload <= 128'd0;
            f1_tog     <= 1'b0;
        end else if (f1_pose_valid) begin
            f1_payload <= f1_pose_word;
            f1_tog     <= ~f1_tog;
        end
    end

    // ------------------------------------------------------------ consumer side
    // Write-side decode lives here (not further down) because the pending/missed
    // logic below depends on wr_ack; Verilog would otherwise create an implicit
    // net and then complain about the later redeclaration.
    wire        wr_en    = s_axi_awvalid & s_axi_wvalid & ~s_axi_bvalid;
    wire [5:0]  wr_addr  = s_axi_awaddr[5:0];
    wire        wr_ack   = wr_en & (wr_addr[5:2] == 4'h8);      // 0x20 ACK
    wire        wr_ctrl  = wr_en & (wr_addr[5:2] == 4'h9);      // 0x24 CTRL
    wire        wr_per   = wr_en & (wr_addr[5:2] == 4'hA);      // 0x28 PERIOD_MS
    reg         bvalid_r;

    // ---- configuration registers (aclk domain) ----
    reg        cfg_arm;        // 1 = let the PL trigger frames
    reg        cfg_sel;        // 1 = merged_top takes ctrl from here, 0 = from the VIO
    reg [15:0] cfg_period;     // requested period in ms
    initial begin
        cfg_arm    = 1'b0;
        cfg_sel    = 1'b0;
        cfg_period = 16'd10;
    end

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            cfg_arm  <= 1'b0;
            cfg_sel  <= 1'b0;
            cfg_period <= 16'd10;
        end else begin
            if (wr_ctrl) begin
                cfg_arm <= s_axi_wdata[0];
                cfg_sel <= s_axi_wdata[16];
            end
            if (wr_per) cfg_period <= s_axi_wdata[15:0];
        end
    end

    (* ASYNC_REG = "TRUE" *) reg [2:0] tog_s;
    always @(posedge aclk or negedge aresetn)
        if (!aresetn) tog_s <= 3'b000; else tog_s <= {tog_s[1:0], tog};

    wire tog_edge = tog_s[2] ^ tog_s[1];

    reg [1:0]  settle;
    reg        cap;
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin settle <= 2'd0; cap <= 1'b0; end
        else begin
            cap    <= 1'b0;
            settle <= {settle[0], tog_edge};
            if (settle[1]) cap <= 1'b1;          // two aclk cycles after the edge
        end
    end

    reg [175:0] payload_r;
    reg [15:0]  seq_r;
    reg         cfg_arm_d;

    // F1 pose consumer (aclk side), same 2-FF toggle + settle scheme
    (* ASYNC_REG = "TRUE" *) reg [2:0] ftog_s;
    always @(posedge aclk or negedge aresetn)
        if (!aresetn) ftog_s <= 3'b000; else ftog_s <= {ftog_s[1:0], f1_tog};

    wire ftog_edge = ftog_s[2] ^ ftog_s[1];

    reg [1:0] fsettle;
    reg       fcap;
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin fsettle <= 2'd0; fcap <= 1'b0; end
        else begin
            fcap    <= 1'b0;
            fsettle <= {fsettle[0], ftog_edge};
            if (fsettle[1]) fcap <= 1'b1;
        end
    end

    reg [127:0] f1_r;
    always @(posedge aclk or negedge aresetn)
        if (!aresetn) f1_r <= {16'h4D50, 112'd0};   // magic visible before any sample
        else if (fcap) f1_r <= f1_payload;

    reg         pending;
    reg         missed;
    reg [7:0]   missed_cnt;

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            payload_r  <= 176'd0;
            seq_r      <= 16'd0;
            pending    <= 1'b0;
            missed     <= 1'b0;
            missed_cnt <= 8'd0;
        end else if (cfg_arm && !cfg_arm_d) begin
            // "missed" is cumulative since the last arm: an ACK must not erase a
            // loss that already happened, otherwise a scan cannot report it.
            missed_cnt <= 8'd0;
            missed     <= 1'b0;
        end else if (cap) begin
            // a still-pending record means the PS was too slow: count it, do not hide it
            if (pending) begin
                missed     <= 1'b1;
                missed_cnt <= missed_cnt + 8'd1;
            end
            payload_r <= payload;
            seq_r     <= payload[175:160];
            pending   <= 1'b1;
        end else if (wr_ack) begin
            pending <= 1'b0;
            missed  <= 1'b0;
        end
    end

    // ------------------------------------------------------------- AXI write side
    // final write-response handshake (decode itself is in the consumer section)
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) bvalid_r <= 1'b0;
        else if (wr_en)   bvalid_r <= 1'b1;
        else if (s_axi_bready) bvalid_r <= 1'b0;
    end
    always @(posedge aclk) s_axi_bvalid <= bvalid_r;

    // -------------------------------------------------------------- AXI read side
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            s_axi_rvalid <= 1'b0;
            s_axi_rdata  <= 32'd0;
        end else if (s_axi_arvalid & ~s_axi_rvalid) begin
            s_axi_rvalid <= 1'b1;
            case (s_axi_araddr[5:2])
                4'h0: s_axi_rdata <= {seq, missed_cnt, 6'd0, missed, pending};
                4'h1: s_axi_rdata <= {16'd0, seq_r};
                // payload = {seq[175:160], pose_rot[159:128], pose_lift[127:96],
                //            peak_word[95:56], cent_word[55:0]}
                4'h2: s_axi_rdata <= payload_r[87:56];           // PEAK[31:0]
                4'h3: s_axi_rdata <= {24'd0, payload_r[95:88]};  // PEAK[39:32]
                4'h4: s_axi_rdata <= payload_r[31:0];            // CENT[31:0]
                4'h5: s_axi_rdata <= {8'd0, payload_r[55:32]};   // CENT[55:32]
                4'h6: s_axi_rdata <= payload_r[159:128];         // POSE_ROT
                4'h7: s_axi_rdata <= payload_r[127:96];          // POSE_LIFT
                4'h9: s_axi_rdata <= {15'd0, cfg_sel, 15'd0, cfg_arm};   // 0x24 CTRL
                4'hA: s_axi_rdata <= {16'd0, cfg_period};                // 0x28 PERIOD_MS
                // ---- F1 pose word (independent channel, coherent via seq) ----
                4'hC: s_axi_rdata <= f1_r[31:0];      // 0x30 {yaw, err_cnt}
                4'hD: s_axi_rdata <= f1_r[63:32];     // 0x34 {pitch, roll}
                4'hE: s_axi_rdata <= f1_r[95:64];     // 0x38 tick
                4'hF: s_axi_rdata <= f1_r[127:96];    // 0x3C {magic, seq, flags}
                default: s_axi_rdata <= 32'd0;
            endcase
        end else if (s_axi_rready) begin
            s_axi_rvalid <= 1'b0;
        end
    end

    // ------------------------------------------------- autonomous frame trigger
    // cfg_arm / cfg_sel are single bits: 2-FF synchronisers are enough.
    // cfg_period is multi-bit, so it is NOT sampled continuously -- it is latched
    // on the rising edge of the synchronised arm, i.e. after the host has finished
    // writing it.  That is the contract: write PERIOD_MS first, then set CTRL.arm.
    (* ASYNC_REG = "TRUE" *) reg [1:0] arm_s;
    (* ASYNC_REG = "TRUE" *) reg [1:0] sel_s;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_s <= 2'b00;
            sel_s <= 2'b00;
        end else begin
            arm_s <= {arm_s[0], cfg_arm};
            sel_s <= {sel_s[0], cfg_sel};
        end
    end
    wire arm_l = arm_s[1];

    // one-cycle strobe on a fresh arm; used to reset the cumulative miss counter
    always @(posedge aclk or negedge aresetn)
        if (!aresetn) cfg_arm_d <= 1'b0; else cfg_arm_d <= cfg_arm;
    wire sel_l = sel_s[1];

    reg        arm_l_d;
    reg [15:0] per_l;
    reg [31:0] limit;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            arm_l_d <= 1'b0;
            per_l   <= 16'd10;
            limit   <= 32'd500000;
        end else begin
            arm_l_d <= arm_l;
            if (arm_l && !arm_l_d) begin
                per_l <= (cfg_period < 16'd10) ? 16'd10 : cfg_period;
                limit <= ((cfg_period < 16'd10) ? 32'd10 : {16'd0, cfg_period}) * CYCLES_PER_MS;
            end
        end
    end

    reg [31:0] cnt;
    reg        trig_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt    <= 32'd0;
            trig_r <= 1'b0;
        end else begin
            trig_r <= 1'b0;
            if (!arm_l)                 cnt <= 32'd0;
            else if (cnt >= limit - 1) begin
                cnt    <= 32'd0;
                trig_r <= 1'b1;
            end else                   cnt <= cnt + 32'd1;
        end
    end

    assign o_trig    = trig_r;
    assign o_tx_en   = arm_l;
    assign o_sel_ext = sel_l;

endmodule
