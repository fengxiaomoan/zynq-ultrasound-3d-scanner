`timescale 1ns/1ps
// Feed one real ILA frame (560 samples at 5 MSPS) through peak_dsp and print
// the 40-bit result.  samples.hex holds signed 11-bit values in two's
// complement, one per line.
module tb_peak_dsp;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg sample_valid = 1'b0;
    reg signed [10:0] diff = 11'sd0;
    reg capture_start = 1'b0;
    reg [15:0] frame_count = 16'd0;

    wire [39:0] peak_word;
    wire        peak_strobe;
    wire [14:0] peak_idx;
    wire [15:0] peak_amp;
    wire [153:0] dbg_word;
    wire [98:0]  dbg_live;

    // ---- C1: window centroid, fed by the same amp stream (2026-10-26)
    wire [15:0] sid_o, amp_o;
    wire        cent_valid;
    wire [9:0]  cent_idx;
    wire [17:0] cent_sum_w;
    wire [26:0] cent_sum_kw;
    reg  [9:0]  cent_idx_lat;
    reg  [17:0] cent_sum_w_lat;
    reg  [26:0] cent_sum_kw_lat;
    integer     cent_strobes;
    always @(posedge clk) if (cent_valid) begin
        cent_idx_lat    <= cent_idx;
        cent_sum_w_lat  <= cent_sum_w;
        cent_sum_kw_lat <= cent_sum_kw;
        cent_strobes    = cent_strobes + 1;
    end

    peak_centroid cent (
        .clk(clk), .rst_n(rst_n), .capture_start(capture_start),
        .sample_valid(sample_valid), .sid(sid_o), .amp(amp_o),
        .cent_valid(cent_valid), .cent_idx(cent_idx),
        .cent_sum_w(cent_sum_w), .cent_sum_kw(cent_sum_kw));

    peak_dsp dut (
        .clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .diff(diff),
        .capture_start(capture_start), .frame_count(frame_count),
        .peak_word(peak_word), .peak_strobe(peak_strobe),
        .peak_idx(peak_idx), .peak_amp(peak_amp),
        .sid_o(sid_o), .amp_o(amp_o),
        .dbg_word(dbg_word), .dbg_live(dbg_live));

    always #10 clk = ~clk;   // 50 MHz

    reg signed [19:0] ip_dbg; reg [2:0] ph_dbg;
    always @(posedge clk) if (sample_valid) begin ip_dbg <= dut.i_prod; ph_dbg <= dut.ph; end
    reg signed [10:0] mem [0:1023];
    integer i;
    reg [39:0] word_at_frame_end;
    integer strobes;
    always @(posedge clk) if (peak_strobe) strobes = strobes + 1;

    initial begin
        strobes = 0;
        cent_strobes = 0;
        $readmemh("samples.hex", mem);
        if ($test$plusargs("vcd")) begin
            $dumpfile("tb_peak_dsp.vcd");
            $dumpvars(0, tb_peak_dsp);
        end
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (5) @(posedge clk);
        // the frame number is what the host reads back from the control VIO
        if (!$value$plusargs("frame=%d", frame_count)) frame_count = 16'd0;
        capture_start = 1'b1;
        @(posedge clk);
        capture_start = 1'b0;

        for (i = 0; i < 560; i = i + 1) begin
            @(negedge clk);
            diff = mem[i];
            sample_valid = 1'b1;
            @(posedge clk);
            @(negedge clk);
            sample_valid = 1'b0;
            repeat (9) @(posedge clk);   // 5 MSPS: one sample per 10 clocks
        end
        word_at_frame_end = peak_word;

        // 2026-10-25 P1: keep the ADC running past the frame.  Before the fix
        // the peak search never disarmed, sid wrapped after 65536 samples
        // (13.1 ms) and latched a second time on junk - that is what happened on
        // the board.  The word must not change and there must be one strobe.
        for (i = 0; i < 66000; i = i + 1) begin
            @(negedge clk);
            diff = ((i * 37) & 11'h7FF) - 11'sd1024;
            sample_valid = 1'b1;
            @(posedge clk);
            @(negedge clk);
            sample_valid = 1'b0;
            repeat (9) @(posedge clk);
        end

        repeat (5) @(posedge clk);
        $display("PEAK_WORD=%010h FRAME=%0d IDX=%0d AMP=%0d",
                 word_at_frame_end, word_at_frame_end[38:26],
                 peak_word[25:16], peak_word[15:0]);
        $display("STROBES=%0d WORD_AT_END=%010h WORD_STABLE=%b",
                 strobes, peak_word, peak_word == word_at_frame_end);
        $display("CENT_IDX=%0d CENT_SUM_W=%0d CENT_SUM_KW=%0d CENT_STROBES=%0d",
                 cent_idx_lat, cent_sum_w_lat, cent_sum_kw_lat, cent_strobes);
        $finish;
    end

endmodule




