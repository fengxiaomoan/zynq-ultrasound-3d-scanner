`timescale 1ns/1ps
// Streaming 1 MHz I/Q demodulator + envelope + windowed peak detector.
//
//   diff        : signed 11-bit ADC difference, sample_valid at 5 MSPS
//   peak_word   : 40 bit {valid, frame[12:0], idx[9:0], amp[15:0]}
//   peak_strobe : one-clock pulse when the window closes
//
// The TX burst is 8 cycles at 1 MHz.  With fs = 5 MHz the NCO has exactly five
// phases, so cos/sin are constant Q7 tables and the multipliers are tiny.
// I/Q are boxcar-averaged over 10 samples (2 us = two carrier periods); the
// envelope is |I|+|Q|.  The peak is searched over samples 280..540
// (56..108 us) and latched when the window closes.
//
// The 40-bit word carries the acquisition frame number so a host can prove that
// the word and the ILA frame it compares against belong to the same frame.  The
// quality byte of the previous format is dropped: it was amp[15:8] and the host
// can shift it out itself.
//
// Every frame is self-contained: the NCO phase and the DC blocker are reset on
// capture_start as well, so the word is a pure function of the 560 samples that
// follow capture_start.  Without that, the phase the free-running NCO happened
// to hold at the frame start changed the |I|+|Q| amplitude by up to 20% and
// moved the peak index by up to 2 samples, which blocks any bit-exact
// comparison against tools/dsp_ref.py.

module peak_dsp #(
    parameter integer WIN_START = 280,
    parameter integer WIN_END   = 540
)(
    input  wire               clk,
    input  wire               rst_n,
    input  wire               sample_valid,
    input  wire signed [10:0] diff,
    input  wire               capture_start,
    input  wire [15:0]        frame_count,
    output reg  [39:0]        peak_word,
    output reg                peak_strobe,
    output reg  [14:0]        peak_idx,
    output reg  [15:0]        peak_amp,
    // taps for peak_centroid (added 2026-10-26): pure observation, no logic change
    output wire [15:0]        sid_o,
    output wire [15:0]        amp_o,
    // Debug snapshot of the datapath at the instant the peak word is latched.
    // Only used by the bring-up build (dsp_debug_read.tcl) to compare the board
    // against tools/dsp_ref.py sample by sample; it does not change behaviour.
    //   [153:138] peak_amp  [137:128] peak_idx  [127:112] amp   [111:96] sid
    //   [95:80]   dc_q4     [79:77]   ph        [76:53]   sum_i [52:29] sum_q
    //   [28:16]   frame_count           [15:0]  sample_valid count since reset
    output reg  [153:0]       dbg_word,
    // Live datapath state for the ILA in bring-up builds (unconnected in the
    // deliverable design): {dc_q4[15:0], ph[2:0], sum_i[23:0], sum_q[23:0],
    //                       amp[15:0], sid[15:0]}
    output wire [98:0]        dbg_live
);

    // ---------------------------------------------------------- sample counter
    reg [15:0] sid;
    reg        active;
    reg [15:0] sv_cnt;              // free-running sample_valid count (debug only)
    always @(posedge clk) begin
        if (!rst_n) begin
            sid    <= 16'd0;
            active <= 1'b0;
        end else if (capture_start) begin
            sid    <= 16'd0;
            active <= 1'b1;
        end else if (sample_valid && active) begin
            sid <= sid + 16'd1;
            // ---- 2026-10-25 P1 fix -----------------------------------------
            // Disarm once the peak window is complete.  Without this the frame
            // never ended for the peak search: sid kept counting past the
            // window, wrapped every 65536 samples (13.1 ms) and latched again on
            // an arbitrary slice of the free-running ADC stream.  On the board
            // that rewrote the word several times per second while frame_count
            // stayed put, so no on-board word could be matched to its ILA frame.
            if (sid == WIN_END - 1) active <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) sv_cnt <= 16'd0;
        else if (sample_valid) sv_cnt <= sv_cnt + 16'd1;
    end

    // ---------------------------------------------------------------- DC block
    // dc_q4 keeps the baseline in Q4; alpha = 1/64.  Cleared per frame so the
    // frame result does not depend on how long the ADC has been running.
    reg  signed [15:0] dc_q4;
    wire signed [15:0] xq4 = $signed({diff, 4'b0000});
    always @(posedge clk) begin
        if (!rst_n || capture_start) dc_q4 <= 16'sd0;
        else if (sample_valid) dc_q4 <= dc_q4 + ((xq4 - dc_q4) >>> 6);
    end
    wire signed [11:0] dc_i = $signed(dc_q4) >>> 4;
    wire signed [11:0] hp   = $signed(diff) - dc_i;

    // ------------------------------------------------------------------- NCO
    reg [2:0] ph;
    always @(posedge clk) begin
        if (!rst_n || capture_start) ph <= 3'd0;
        else if (sample_valid) ph <= (ph == 3'd4) ? 3'd0 : ph + 3'd1;
    end

    reg signed [8:0] co, si;
    always @(*) begin
        case (ph)
            3'd0: begin co =  9'sd128; si =   9'sd0;   end
            3'd1: begin co =   9'sd40; si =  9'sd122;  end
            3'd2: begin co = -9'sd104; si =   9'sd75;  end
            3'd3: begin co = -9'sd104; si =  -9'sd75;  end
            default: begin co = 9'sd40; si = -9'sd122; end
        endcase
    end

    wire signed [20:0] i_prod = hp * co;   // 12 x 9
    wire signed [20:0] q_prod = hp * si;

    // --------------------------------------------------------- 10-tap boxcar
    reg signed [20:0] ibuf [0:9];
    reg signed [20:0] qbuf [0:9];
    reg signed [23:0] sum_i, sum_q;
    integer k;
    always @(posedge clk) begin
        if (!rst_n || capture_start) begin
            sum_i <= 24'sd0;
            sum_q <= 24'sd0;
            for (k = 0; k < 10; k = k + 1) begin
                ibuf[k] <= 21'sd0;
                qbuf[k] <= 21'sd0;
            end
        end else if (sample_valid) begin
            sum_i <= sum_i + i_prod - ibuf[9];
            sum_q <= sum_q + q_prod - qbuf[9];
            for (k = 9; k > 0; k = k - 1) begin
                ibuf[k] <= ibuf[k-1];
                qbuf[k] <= qbuf[k-1];
            end
            ibuf[0] <= i_prod;
            qbuf[0] <= q_prod;
        end
    end

    wire [23:0] abs_i = sum_i[23] ? (~sum_i + 24'd1) : sum_i;
    wire [23:0] abs_q = sum_q[23] ? (~sum_q + 24'd1) : sum_q;
    wire [24:0] mag   = {1'b0, abs_i} + {1'b0, abs_q};
    wire [15:0] amp   = (mag >> 6) > 25'd65535 ? 16'hFFFF : (mag >> 6);
    assign dbg_live   = {dc_q4, ph, sum_i, sum_q, amp, sid};
    assign sid_o      = sid;
    assign amp_o      = amp;

    // ------------------------------------------------------------- peak search
    wire in_win   = (sid >= WIN_START) && (sid < WIN_END);
    wire take_new = in_win && (amp > peak_amp);
    wire [15:0] best_amp = take_new ? amp : peak_amp;
    wire [9:0]  best_idx = take_new ? sid[9:0] : peak_idx[9:0];

    always @(posedge clk) begin
        // peak_strobe is a one-cycle pulse: default it to 0 every clock, so it
        // cannot stick high once the search is disarmed (found 2026-10-25 20:40
        // by the rollover regression: clearing it inside the
        // `sample_valid && active` branch left it high forever after the latch).
        peak_strobe <= 1'b0;
        if (!rst_n) begin
            peak_word   <= 40'd0;
            peak_idx    <= 15'd0;
            peak_amp    <= 16'd0;
            dbg_word    <= 154'd0;
        end else if (capture_start) begin
            peak_word   <= 40'd0;
            peak_idx    <= 15'd0;
            peak_amp    <= 16'd0;
            dbg_word    <= 154'd0;
        end else if (sample_valid && active) begin
            peak_amp    <= best_amp;
            peak_idx    <= {5'd0, best_idx};
            if (sid == WIN_END - 1) begin
                peak_word   <= {1'b1, frame_count[12:0], best_idx, best_amp};
                peak_strobe <= 1'b1;
                dbg_word    <= {best_amp, best_idx, amp, sid, dc_q4, ph,
                                sum_i, sum_q, frame_count[12:0], sv_cnt};
            end
        end
    end

endmodule
