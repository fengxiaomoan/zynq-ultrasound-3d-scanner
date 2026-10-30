// MPU6050 bring-up sequencer: wait 100 ms, wake, check WHO_AM_I, write the
// fixed configuration, then read the 14 data bytes continuously.
//
// 2026-10-26 F1: first on-board checkpoint.  `hold` (VIO output, initial 1)
// keeps the sequencer parked with the bus released so the two lines can be
// checked before any transaction starts.
`timescale 1ns / 1ps
module mpu6050_bringup #(
    parameter integer PWR_CYCLES    = 50_000_000 / 10,  // 100 ms @ 50 MHz
    parameter integer WAKE_CYCLES   = 50_000_000 / 100, // 10 ms
    parameter integer SAMPLE_CYCLES = 50_000,           // 1 ms
    parameter integer RETRY_CYCLES  = 50_000_000 / 10   // 100 ms
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        hold,

    // byte-level master interface
    output wire        m_start,
    output wire        m_stop,
    output wire        m_send,
    output wire        m_recv,
    output wire        m_ack,
    output wire [7:0]  m_tx,
    input  wire [7:0]  m_rx,
    input  wire        m_ack_in,
    input  wire        m_busy,
    input  wire        m_done,
    input  wire        m_err,

    // debug / status
    output reg  [7:0]  who,
    output reg  [7:0]  pc_dbg,
    output reg  [7:0]  err_cnt,
    output reg  [15:0] ax,
    output reg  [15:0] ay,
    output reg  [15:0] az,
    output reg  [15:0] gx,
    output reg  [15:0] gy,
    output reg  [15:0] gz,
    // Pose timebase: one pulse per complete 14-byte sample, plus the free-running
    // 50 MHz tick at that instant.  pose_fusion needs both: the tick is what makes
    // the attitude and the ultrasound frames share one timebase.
    input  wire [31:0] free_tick,
    output reg         sample_valid,
    output reg  [31:0] sample_tick
);
    localparam integer P_PWR       = 8'd0;
    localparam integer P_WHO_S     = 8'd1;
    localparam integer P_WHO_A     = 8'd2;
    localparam integer P_WHO_R     = 8'd3;
    localparam integer P_WHO_RS    = 8'd4;
    localparam integer P_WHO_AR    = 8'd5;
    localparam integer P_WHO_RD    = 8'd6;
    localparam integer P_WHO_STOP  = 8'd7;
    localparam integer P_WHO_CHK   = 8'd8;
    localparam integer P_CFG_S     = 8'd10;
    localparam integer P_CFG_A     = 8'd11;
    localparam integer P_CFG_R     = 8'd12;
    localparam integer P_CFG_V     = 8'd13;
    localparam integer P_CFG_STOP  = 8'd14;
    localparam integer P_CFG_NEXT  = 8'd15;
    localparam integer P_WAKE_WAIT = 8'd16;
    localparam integer P_RD_S      = 8'd20;
    localparam integer P_RD_A      = 8'd21;
    localparam integer P_RD_R      = 8'd22;
    localparam integer P_RD_RS     = 8'd23;
    localparam integer P_RD_AR     = 8'd24;
    localparam integer P_RD_B      = 8'd25;
    localparam integer P_RD_STOP   = 8'd26;
    localparam integer P_RD_DONE   = 8'd27;
    localparam integer P_LOOP      = 8'd28;
    localparam integer P_ERR       = 8'd40;

    localparam [2:0] C_NONE = 3'd0, C_START = 3'd1, C_SEND = 3'd2,
                     C_RECV = 3'd3, C_STOP = 3'd4;

    reg [7:0]  pc;
    reg [7:0]  nxt;
    reg        waiting;
    reg        launch;
    reg [2:0]  cmd;
    reg [7:0]  txb;
    reg        ack_req;
    reg [7:0]  buf0, buf1, buf2, buf3, buf4, buf5, buf6, buf7,
               buf8, buf9, buf10, buf11, buf12, buf13;
    reg [3:0]  bi;
    reg [2:0]  ci;
    reg [31:0] pwr_cnt, wake_cnt, samp_cnt, retry_cnt;
    reg [31:0] next_tick;          /* absolute deadline of the next 14-byte burst */
    reg [31:0] burst_start;        /* tick when THIS burst started (period base)  */
    reg [7:0]  cfg_reg, cfg_val;

    // command pulses: `launch` is set for one cycle, so the master sees a
    // single-cycle start/send/recv/stop even though `cmd` is registered.
    assign m_start = launch && (cmd == C_START);
    assign m_send  = launch && (cmd == C_SEND);
    assign m_recv  = launch && (cmd == C_RECV);
    assign m_stop  = launch && (cmd == C_STOP);
    assign m_ack   = ack_req;
    assign m_tx    = txb;

    always @(*) begin
        case (ci)
            3'd0: begin cfg_reg = 8'h6B; cfg_val = 8'h00; end  // wake, PLL X gyro later
            3'd1: begin cfg_reg = 8'h19; cfg_val = 8'h00; end  // 1 kHz
            3'd2: begin cfg_reg = 8'h1A; cfg_val = 8'h02; end  // DLPF ~94 Hz
            3'd3: begin cfg_reg = 8'h1B; cfg_val = 8'h08; end  // gyro +-500 dps
            3'd4: begin cfg_reg = 8'h1C; cfg_val = 8'h08; end  // accel +-4 g
            default: begin cfg_reg = 8'h00; cfg_val = 8'h00; end
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            pc <= P_PWR; nxt <= P_PWR; waiting <= 1'b0; launch <= 1'b0;
            cmd <= C_NONE; txb <= 8'd0; ack_req <= 1'b0;
            bi <= 4'd0; ci <= 3'd0;
            pwr_cnt <= 32'd0; wake_cnt <= 32'd0; samp_cnt <= 32'd0; retry_cnt <= 32'd0;
            next_tick <= 32'd0;
            who <= 8'd0; pc_dbg <= 8'd0; err_cnt <= 8'd0;
            ax <= 16'd0; ay <= 16'd0; az <= 16'd0;
            gx <= 16'd0; gy <= 16'd0; gz <= 16'd0;
            sample_valid <= 1'b0; sample_tick <= 32'd0;
            buf0 <= 8'd0; buf1 <= 8'd0; buf2 <= 8'd0; buf3 <= 8'd0;
            buf4 <= 8'd0; buf5 <= 8'd0; buf6 <= 8'd0; buf7 <= 8'd0;
            buf8 <= 8'd0; buf9 <= 8'd0; buf10 <= 8'd0; buf11 <= 8'd0;
            buf12 <= 8'd0; buf13 <= 8'd0;
        end else begin
            launch <= 1'b0;
            sample_valid <= 1'b0;

            if (hold) begin
                pc <= P_PWR; waiting <= 1'b0; cmd <= C_NONE;
                pwr_cnt <= 32'd0; samp_cnt <= 32'd0; bi <= 4'd0;
                who <= 8'd0; err_cnt <= 8'd0;
                ax <= 16'd0; ay <= 16'd0; az <= 16'd0;
                gx <= 16'd0; gy <= 16'd0; gz <= 16'd0;
            end else begin
                if (waiting) begin
                    if (m_done) begin
                        waiting <= 1'b0;
                        cmd <= C_NONE;

                        if (m_err) begin
                            err_cnt <= err_cnt + 8'd1;
                            pc <= P_ERR;
                        end else if (cmd == C_SEND && m_ack_in) begin
                            err_cnt <= err_cnt + 8'd1;
                            pc <= P_ERR;
                        end else if (pc == P_WHO_RD) begin
                            buf0 <= m_rx;
                            pc <= nxt;
                        end else if (pc == P_RD_B) begin
                            case (bi)
                                4'd0:  buf0  <= m_rx;
                                4'd1:  buf1  <= m_rx;
                                4'd2:  buf2  <= m_rx;
                                4'd3:  buf3  <= m_rx;
                                4'd4:  buf4  <= m_rx;
                                4'd5:  buf5  <= m_rx;
                                4'd6:  buf6  <= m_rx;
                                4'd7:  buf7  <= m_rx;
                                4'd8:  buf8  <= m_rx;
                                4'd9:  buf9  <= m_rx;
                                4'd10: buf10 <= m_rx;
                                4'd11: buf11 <= m_rx;
                                4'd12: buf12 <= m_rx;
                                default: buf13 <= m_rx;
                            endcase
                            if (bi == 4'd13) pc <= P_RD_STOP;
                            else begin bi <= bi + 4'd1; pc <= P_RD_B; end
                        end else begin
                            pc <= nxt;
                        end
                    end
                end else begin
                    case (pc)
                        P_PWR: begin
                            if (pwr_cnt == PWR_CYCLES) begin
                                pwr_cnt <= 32'd0; pc <= P_WHO_S;
                            end else pwr_cnt <= pwr_cnt + 32'd1;
                        end

                        // ------------------------------------------- WHO_AM_I
                        P_WHO_S:  begin cmd <= C_START; launch <= 1; waiting <= 1; nxt <= P_WHO_A;    end
                        P_WHO_A:  begin cmd <= C_SEND; txb <= 8'hD0; launch <= 1; waiting <= 1; nxt <= P_WHO_R; end
                        P_WHO_R:  begin cmd <= C_SEND; txb <= 8'h75; launch <= 1; waiting <= 1; nxt <= P_WHO_RS; end
                        P_WHO_RS: begin cmd <= C_START; launch <= 1; waiting <= 1; nxt <= P_WHO_AR;   end
                        P_WHO_AR: begin cmd <= C_SEND; txb <= 8'hD1; launch <= 1; waiting <= 1; nxt <= P_WHO_RD; end
                        P_WHO_RD: begin cmd <= C_RECV; ack_req <= 1'b0; launch <= 1; waiting <= 1; nxt <= P_WHO_STOP; end
                        P_WHO_STOP: begin cmd <= C_STOP; launch <= 1; waiting <= 1; nxt <= P_WHO_CHK; end
                        P_WHO_CHK: begin
                            who <= buf0;
                            if (buf0 == 8'h68) pc <= P_CFG_S;
                            else begin err_cnt <= err_cnt + 8'd1; pc <= P_ERR; end
                        end

                        // ------------------------------------------- config
                        P_CFG_S:    begin cmd <= C_START; launch <= 1; waiting <= 1; nxt <= P_CFG_A; end
                        P_CFG_A:    begin cmd <= C_SEND; txb <= 8'hD0; launch <= 1; waiting <= 1; nxt <= P_CFG_R; end
                        P_CFG_R:    begin cmd <= C_SEND; txb <= cfg_reg; launch <= 1; waiting <= 1; nxt <= P_CFG_V; end
                        P_CFG_V:    begin cmd <= C_SEND; txb <= cfg_val; launch <= 1; waiting <= 1; nxt <= P_CFG_STOP; end
                        P_CFG_STOP: begin cmd <= C_STOP; launch <= 1; waiting <= 1; nxt <= P_CFG_NEXT; end
                        P_CFG_NEXT: begin
                            if (ci == 3'd0) begin
                                wake_cnt <= 32'd0; pc <= P_WAKE_WAIT;
                            end else if (ci == 3'd4) begin
                                bi <= 4'd0; samp_cnt <= 32'd0; pc <= P_RD_S;
                            end else begin
                                ci <= ci + 3'd1; pc <= P_CFG_S;
                            end
                        end
                        P_WAKE_WAIT: begin
                            if (wake_cnt == WAKE_CYCLES) begin
                                wake_cnt <= 32'd0; ci <= 3'd1; pc <= P_CFG_S;
                            end else wake_cnt <= wake_cnt + 32'd1;
                        end

                        // ------------------------------------------- data burst
                        P_RD_S:    begin
                            /* period is measured from HERE, not from the end of the
                             * burst: next_tick = burst_start + SAMPLE_CYCLES makes
                             * the sample interval 1 ms net of the I2C time.  Setting
                             * it at P_RD_DONE measured 1 ms AFTER the burst, which is
                             * why the board read 1.40 ms (716 Hz) even with the tick
                             * scheduler in place. */
                            burst_start <= free_tick;
                            cmd <= C_START; launch <= 1; waiting <= 1; nxt <= P_RD_A;
                        end
                        P_RD_A:    begin cmd <= C_SEND; txb <= 8'hD0; launch <= 1; waiting <= 1; nxt <= P_RD_R; end
                        P_RD_R:    begin cmd <= C_SEND; txb <= 8'h3B; launch <= 1; waiting <= 1; nxt <= P_RD_RS; end
                        P_RD_RS:   begin cmd <= C_START; launch <= 1; waiting <= 1; nxt <= P_RD_AR; end
                        P_RD_AR:   begin cmd <= C_SEND; txb <= 8'hD1; launch <= 1; waiting <= 1; nxt <= P_RD_B; end
                        P_RD_B:    begin
                            cmd <= C_RECV;
                            ack_req <= (bi != 4'd13);
                            launch <= 1; waiting <= 1; nxt <= P_RD_B;
                        end
                        P_RD_STOP: begin cmd <= C_STOP; launch <= 1; waiting <= 1; nxt <= P_RD_DONE; end
                        P_RD_DONE: begin
                            ax <= {buf0, buf1};
                            ay <= {buf2, buf3};
                            az <= {buf4, buf5};
                            gx <= {buf8, buf9};
                            gy <= {buf10, buf11};
                            gz <= {buf12, buf13};
                            sample_tick  <= free_tick;
                            sample_valid <= 1'b1;
                            /* Schedule on ABSOLUTE ticks, not "wait SAMPLE_CYCLES
                             * after the transaction".  The old P_LOOP counter made
                             * the real period = wait + I2C burst: measured on the
                             * board 2026-10-27 as 1.40 ms = 717 Hz, not the 1 kHz
                             * the design claims.  With an absolute deadline the
                             * period is exactly SAMPLE_CYCLES; if a burst ever takes
                             * longer than that, the next sample starts immediately
                             * (period degrades gracefully instead of drifting). */
                            next_tick <= burst_start + SAMPLE_CYCLES;
                            samp_cnt  <= 32'd0;
                            pc <= P_LOOP;
                        end
                        P_LOOP: begin
                            /* wrap-safe "free_tick >= next_tick" (signed diff) */
                            if ($signed(free_tick - next_tick) >= 0) begin
                                samp_cnt <= 32'd0; bi <= 4'd0; pc <= P_RD_S;
                            end else begin
                                samp_cnt <= samp_cnt + 32'd1;
                            end
                        end

                        P_ERR: begin
                            if (retry_cnt == RETRY_CYCLES) begin
                                retry_cnt <= 32'd0;
                                ci <= 3'd0;
                                bi <= 4'd0;
                                pc <= P_WHO_S;
                            end else retry_cnt <= retry_cnt + 32'd1;
                        end

                        default: pc <= P_PWR;
                    endcase
                end
            end
            pc_dbg <= pc;
        end
    end
endmodule
