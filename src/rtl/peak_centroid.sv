// peak_centroid: window-centroid arrival time, fixed point.
//
// Replaces the window argmax as the *measurement*, without touching the exit
// path P1.1 already verified bit for bit: the 40-bit peak_word is untouched and
// this module drives its own VIO probe.
//
// Mirrors tools/dsp_ref.py::centroid_reference() exactly:
//
//     base = floor(sum(amp[WIN_START:WIN_END]) / NF)
//     w_k  = max(amp_k - base, 0)
//     idx  = floor(sum(k*w_k) / sum(w_k))
//     t    = idx * 0.2 us
//
// Why a centroid (measured on 1248 real frames, docs/DSP路径复现_20261026.md):
// argmax -> 2.73 mm layer spread, 28.8% outliers, because the 1 MHz narrowband
// envelope has several near-equal multipath peaks.  Centroid -> 1.30 mm, 6%.
// Bandwidth is NOT the limiter: wideband+argmax is 3.86 mm, wideband+centroid
// 1.31 mm, narrowband+centroid 1.30 mm.  So no FIR is needed.
//
// Timing: the window is samples 280..539 (260 samples, 107.8 us end).  Two
// passes over a 260x16 buffer plus two 48-bit serial divisions take ~700 clocks
// = 14 us, against the 2800 clks (56 us) left in the 163.84 us frame.  The
// frame period is unchanged.

module peak_centroid #(
    parameter integer WIN_START = 280,
    parameter integer WIN_END   = 540,
    parameter integer SUM_W_W   = 18,   // measured max 85,897  -> 17 bit
    parameter integer SUM_KW_W  = 27    // measured max 3.3e7   -> 25 bit
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        capture_start,
    input  wire        sample_valid,
    input  wire [15:0] sid,          // sample index within the frame
    input  wire [15:0] amp,          // 16-bit |I|+|Q| envelope from peak_dsp
    output reg         cent_valid,   // one-cycle pulse when the result is ready
    output reg  [9:0]  cent_idx,     // arrival index, samples
    output reg  [SUM_W_W-1:0]  cent_sum_w,
    output reg  [SUM_KW_W-1:0] cent_sum_kw
);

    localparam integer NF = WIN_END - WIN_START;

    localparam [2:0] S_IDLE = 3'd0,   // waiting for capture_start
                     S_ACC  = 3'd1,   // pass 1: buffer + sum for the baseline
                     S_BGO  = 3'd2,   // assert div_go for base = sum_amp / NF
                     S_BWT  = 3'd3,   // wait for that division
                     S_CENT = 3'd4,   // pass 2: accumulate w and k*w
                     S_IGO  = 3'd5,   // assert div_go for idx = sum_kw / sum_w
                     S_IWT  = 3'd6,   // wait, then latch the result

                     S_DONE = 3'd7;

    reg [2:0]  st;
    reg [15:0] win_buf [0:NF-1];     // not `buf`: that is a Verilog primitive name
    reg [15:0] addr;                 // pass-2 read address
    reg [15:0] rd;                   // registered buffer read
    reg [15:0] base;
    reg [24:0] sum_amp;
    reg [SUM_W_W-1:0]  sum_w;
    reg [SUM_KW_W-1:0] sum_kw;

    // ---- serial restoring divider, driven only by the FSM below ------------
    reg        div_go;               // one-cycle start pulse
    reg        div_busy;
    reg [47:0] div_num;
    // 18 bit: the second division uses sum(w) as the denominator, and sum(w)
    // reaches 85,897 on real frames (measured), i.e. more than 16 bits.
    reg [17:0] div_den;
    reg [47:0] div_quo;
    reg [47:0] sh;                   // dividend shift register
    reg [47:0] rem;                  // running remainder
    reg [47:0] quo;
    reg [17:0] den;                  // 18 bit: sum(w) reaches 85,897
    reg [6:0]  bitc;

    wire [47:0] rem_next = (rem << 1) | {47'd0, sh[47]};
    wire [47:0] den48    = {30'd0, den};
    wire        ge       = (rem_next >= den48);
    wire [47:0] rem_sub  = rem_next - den48;

    wire in_win  = (sid >= WIN_START) && (sid < WIN_END);
    wire win_end = (sid == WIN_END - 1) && sample_valid;
    // 9-bit addresses on purpose: indexing win_buf with the raw 16-bit sid/addr
    // lets synthesis infer a 65,536-deep memory (1 Mbit, 30+ BRAMs).  The
    // difference is 0..259 inside the window and 9-bit wrap-around is exact.
    wire [8:0] waddr = sid[8:0] - WIN_START[8:0];
    wire [8:0] raddr = addr[8:0];
    wire [15:0] w_now = (rd > base) ? (rd - base) : 16'd0;
    // k*w, sized explicitly: max is 539*65535 = 35.3e6, i.e. 26 bits
    wire [31:0] kw_now = (WIN_START + addr - 16'd1) * {16'd0, w_now};

    always @(posedge clk) begin
        if (!rst_n) begin
            st          <= S_IDLE;
            cent_valid  <= 1'b0;
            cent_idx    <= 10'd0;
            cent_sum_w  <= {SUM_W_W{1'b0}};
            cent_sum_kw <= {SUM_KW_W{1'b0}};
            sum_amp     <= 25'd0;
            sum_w       <= {SUM_W_W{1'b0}};
            sum_kw      <= {SUM_KW_W{1'b0}};
            addr        <= 16'd0;
            rd          <= 16'd0;
            base        <= 16'd0;
            div_go      <= 1'b0;
            div_busy    <= 1'b0;
            div_num     <= 48'd0;
            div_den     <= 16'd0;
            div_quo     <= 48'd0;
            sh          <= 48'd0;
            rem         <= 48'd0;
            quo         <= 48'd0;
            den         <= 16'd0;
            bitc        <= 7'd0;
        end else begin
            cent_valid <= 1'b0;
            div_go     <= 1'b0;

            // ---------------- serial divider (single owner of sh/rem/quo/bitc)
            if (div_busy) begin
                rem  <= ge ? rem_sub : rem_next;
                quo  <= {quo[46:0], ge};
                sh   <= {sh[46:0], 1'b0};
                bitc <= bitc + 7'd1;
                if (bitc == 7'd47) begin
                    div_busy <= 1'b0;
                    div_quo  <= {quo[46:0], ge};
                end
            end else if (div_go) begin
                sh       <= div_num;
                den      <= div_den;
                rem      <= 48'd0;
                quo      <= 48'd0;
                bitc     <= 7'd0;
                div_busy <= 1'b1;
            end

            // ---------------- control FSM
            case (st)
                S_IDLE: if (capture_start) begin
                    sum_amp <= 25'd0;
                    addr    <= 16'd0;
                    st      <= S_ACC;
                end

                // pass 1: buffer every window sample and accumulate the baseline
                S_ACC: begin
                    if (sample_valid && in_win) begin
                        win_buf[waddr] <= amp;
                        sum_amp <= sum_amp + {9'd0, amp};
                    end
                    if (win_end) st <= S_BGO;
                end

                S_BGO: begin
                    div_num <= {23'd0, sum_amp};
                    div_den <= NF[15:0];
                    div_go  <= 1'b1;
                    st      <= S_BWT;
                end

                S_BWT: if (!div_busy && !div_go) begin
                    base   <= div_quo[15:0];
                    sum_w  <= {SUM_W_W{1'b0}};
                    sum_kw <= {SUM_KW_W{1'b0}};
                    addr   <= 16'd0;
                    st     <= S_CENT;
                end

                // pass 2: one buffered sample per clock.  rd lag`addr` by one, so
                // the sample at address a is valid on the cycle after addr=a.
                S_CENT: begin
                    if (addr < NF[15:0]) rd <= win_buf[raddr];
                    if (addr > 16'd0) begin
                        sum_w  <= sum_w + {{(SUM_W_W-16){1'b0}}, w_now};
                        sum_kw <= sum_kw + kw_now[SUM_KW_W-1:0];
                    end
                    if (addr == NF[15:0]) st <= S_IGO;
                    else addr <= addr + 16'd1;
                end

                S_IGO: begin
                    div_num <= {21'd0, sum_kw};
                    div_den <= (sum_w == 0) ? 18'd1 : sum_w;
                    div_go  <= 1'b1;
                    st      <= S_IWT;
                end

                S_IWT: if (!div_busy && !div_go) begin
                    // valid mirrors dsp_ref.centroid_reference(): a flat window
                    // (sum(w)==0) has no centroid and must not be used.
                    cent_idx    <= (sum_w == 0) ? 10'd0 : div_quo[9:0];
                    cent_sum_w  <= sum_w;
                    cent_sum_kw <= sum_kw;
                    cent_valid  <= (sum_w != 0);
                    st          <= S_DONE;
                end

                S_DONE: st <= S_IDLE;

                default: st <= S_IDLE;
            endcase
        end
    end

endmodule
