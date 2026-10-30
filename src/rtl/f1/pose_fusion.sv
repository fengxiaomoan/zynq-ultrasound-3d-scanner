// pose_fusion: MPU6050 raw samples -> roll/pitch/yaw, integer only, bit-exact.
//
// Why integer-only: the project's credibility rests on "the board's number can be
// recomputed on a PC, bit for bit" (E6).  A float pipeline would make that claim
// untestable, so every step here is fixed-point and tools/f1_pose_ref.py replays
// the *same* integer steps; tb_pose_fusion.sv then compares the two directly.
//
// Angle unit ("counts"): 90 deg = 16384, i.e. 1 count = 0.005493 deg.  This is
// exactly the 16-bit field of the pose word in the design doc ("degrees x
// 182.044"), so the AXI value needs no scaling in the firmware or the page.
//
// Conventions (must match the firmware and the page):
//   Z up, gravity = -Z at rest (az = +8192 at +-4 g)
//   roll  = atan2(ay, az)                 about X
//   pitch = atan2(-ax, sqrt(ay^2+az^2))   about Y
//   yaw   = integral of gz only (no magnetometer -> it drifts, on purpose)
//
// Per sample the latency is FIXED (52 cycles after sample_valid); nothing in the
// timing depends on the data:
//   1  capture + dt
//   16 integer sqrt (digit by digit) -> magnitude for the pitch denominator
//   15 CORDIC rotations -> roll      (vector (|az|,|ay|), quadrant from signs)
//   15 CORDIC rotations -> pitch     (vector (mag,|ax|),  quadrant from signs)
//   3  gyro integrate (one multiplier, reused for roll/pitch/yaw)
//   1  complementary blend + wrap + saturate
`timescale 1ns / 1ps
module pose_fusion #(
    parameter integer DT_MIN  = 10_000,   // 0.2 ms in 50 MHz ticks
    parameter integer DT_MAX  = 200_000,  // 4 ms
    parameter integer WARMUP  = 32,       // samples of accel-only attitude
    // counts += gyro_lsb * ticks * GYRO_K >>> GYRO_S
    // 20 ns * 16384/90 / 65.5 LSB/(deg/s) * 2^36 = 3819.6 -> 3820 (+0.01%)
    parameter integer GYRO_K  = 3820,
    parameter integer GYRO_S  = 36
) (
    input  wire               clk,
    input  wire               rst,

    input  wire               sample_valid,   // 1-cycle pulse: ax..gz are new
    input  wire [31:0]        tick,           // free-running 50 MHz counter
    input  wire signed [15:0] ax,
    input  wire signed [15:0] ay,
    input  wire signed [15:0] az,
    input  wire signed [15:0] gx,
    input  wire signed [15:0] gy,
    input  wire signed [15:0] gz,
    input  wire [7:0]         err_cnt,        // from mpu6050_bringup
    input  wire               bus_stuck,      // from i2c_master

    output reg  signed [15:0] roll,
    output reg  signed [15:0] pitch,
    output reg  signed [15:0] yaw,
    output reg  [7:0]         seq,
    output reg  [31:0]        pose_tick,
    output reg                pose_valid,     // 1-cycle pulse: outputs are new
    output reg  [7:0]         flags,
    output reg  [31:0]        sample_cnt,
    output wire [5:0]         state_dbg       // for ILA/VIO bring-up
);
    // ---------------------------------------------------------------- constants
    // atan(2^-i) in counts (90 deg = 16384).  i=0 is 45 deg = 8192 exactly.
    function signed [19:0] atan_i(input [3:0] i);
        begin
            case (i)
                4'd0:  atan_i = 20'sd8192;
                4'd1:  atan_i = 20'sd4836;
                4'd2:  atan_i = 20'sd2555;
                4'd3:  atan_i = 20'sd1297;
                4'd4:  atan_i = 20'sd651;
                4'd5:  atan_i = 20'sd326;
                4'd6:  atan_i = 20'sd163;
                4'd7:  atan_i = 20'sd81;
                4'd8:  atan_i = 20'sd41;
                4'd9:  atan_i = 20'sd20;
                4'd10: atan_i = 20'sd10;
                4'd11: atan_i = 20'sd5;
                4'd12: atan_i = 20'sd3;
                4'd13: atan_i = 20'sd1;
                default: atan_i = 20'sd0;      // i = 14
            endcase
        end
    endfunction

    // wrap a counts value into [-32768, +32768); one pass is enough because a
    // single update can never move more than half a turn.
    function signed [31:0] wrap32(input signed [31:0] v);
        begin
            if (v >= 32'sd32768)       wrap32 = v - 32'sd65536;
            else if (v < -32'sd32768)  wrap32 = v + 32'sd65536;
            else                       wrap32 = v;
        end
    endfunction

    // saturate the 32-bit accumulator to the 16-bit pose-word field
    function signed [15:0] sat16(input signed [31:0] v);
        begin
            if (v > 32'sd32767)       sat16 = 16'sd32767;
            else if (v < -32'sd32768) sat16 = -16'sd32768;
            else                      sat16 = v[15:0];
        end
    endfunction

    localparam [2:0] S_IDLE = 3'd0, S_SQRT = 3'd1, S_AT1 = 3'd2,
                     S_AT2  = 3'd3, S_GYR = 3'd4, S_FIL = 3'd5;

    reg [2:0]  st;
    reg [4:0]  i;
    reg [1:0]  gsel;

    // ----------------------------------------------------------- sample capture
    reg  signed [15:0] a_x, a_y, a_z, g_x, g_y, g_z;
    reg  [31:0] last_tick;
    reg  [31:0] dt_l;          // dt of THIS sample, latched in S_IDLE
    reg  [7:0]  warm;
    reg  [31:0] sq_l;          // ay^2 + az^2
    reg         sx, sy;        // signs of the two atan2 inputs (1 = negative)

    // ------------------------------------------------------------------- sqrt
    reg [18:0] rem;
    reg [15:0] root;

    // --------------------------------------------------------------- cordic
    reg signed [19:0] cx, cy, cz;
    reg signed [19:0] mag;     // sqrt result: X input of the pitch atan2

    // --------------------------------------------------------------- angles
    reg signed [15:0] roll_a, pitch_a;

    // -------------------------------------------------------------- integrator
    reg signed [31:0] acc_roll, acc_pitch, acc_yaw;

    wire [31:0] dt_raw = tick - last_tick;
    wire [31:0] dt = (dt_raw < DT_MIN) ? DT_MIN :
                     ((dt_raw > DT_MAX) ? DT_MAX : dt_raw);

    // ---------------------------------------------------------- sqrt next value
    wire [31:0] sq_bits_w  = (sq_l >> (30 - 2 * i)) & 32'd3;
    wire [18:0] rem_step_w = {rem[16:0], 2'b00} | {17'd0, sq_bits_w[1:0]};
    wire [17:0] trial_w    = {root[15:0], 2'b01};
    wire        sqrt_ge_w  = (rem_step_w >= {1'b0, trial_w});
    wire [18:0] rem_next_w = sqrt_ge_w ? (rem_step_w - {1'b0, trial_w})
                                       : rem_step_w;
    wire [15:0] root_next_w = sqrt_ge_w ? {root[14:0], 1'b1} : {root[14:0], 1'b0};

    // -------------------------------------------------------- cordic next value
    wire signed [19:0] cx_n_w = (cy >= 0) ? (cx + (cy >>> i)) : (cx - (cy >>> i));
    wire signed [19:0] cy_n_w = (cy >= 0) ? (cy - (cx >>> i)) : (cy + (cx >>> i));
    wire signed [19:0] cz_n_w = (cy >= 0) ? (cz + atan_i(i[3:0]))
                                          : (cz - atan_i(i[3:0]));
    wire signed [19:0] phi_n_w = (cz_n_w >= 0) ? cz_n_w : -cz_n_w;

    // quadrant fix-up: |vector| angle in [0,16384] placed by the input signs
    wire signed [31:0] theta_n_w =
        (!sx && !sy) ?  $signed({12'd0, phi_n_w}) :
        (!sx &&  sy) ? -$signed({12'd0, phi_n_w}) :
        ( sx && !sy) ?  (32'sd32768 - $signed({12'd0, phi_n_w})) :
                       -(32'sd32768 - $signed({12'd0, phi_n_w}));

    // --------------------------------------------------- one reused multiplier
    wire signed [15:0] gsel_g = (gsel == 2'd0) ? g_x :
                                (gsel == 2'd1) ? g_y : g_z;
    wire signed [48:0] prod_w = gsel_g * $signed({1'b0, dt_l});
    wire signed [63:0] wide_w = prod_w * GYRO_K;
    wire signed [31:0] dgyro  = wide_w >>> GYRO_S;

    assign state_dbg = {3'd0, st};

    always @(posedge clk) begin
        if (rst) begin
            st <= S_IDLE; i <= 5'd0; gsel <= 2'd0;
            a_x <= 16'sd0; a_y <= 16'sd0; a_z <= 16'sd0;
            g_x <= 16'sd0; g_y <= 16'sd0; g_z <= 16'sd0;
            last_tick <= 32'd0; warm <= 8'd0;
            dt_l <= 32'd50000;
            sq_l <= 32'd0; sx <= 1'b0; sy <= 1'b0;
            rem <= 19'd0; root <= 16'd0;
            cx <= 20'sd0; cy <= 20'sd0; cz <= 20'sd0; mag <= 20'sd0;
            roll_a <= 16'sd0; pitch_a <= 16'sd0;
            acc_roll <= 32'sd0; acc_pitch <= 32'sd0; acc_yaw <= 32'sd0;
            roll <= 16'sd0; pitch <= 16'sd0; yaw <= 16'sd0;
            seq <= 8'd0; pose_tick <= 32'd0; pose_valid <= 1'b0;
            flags <= 8'd0; sample_cnt <= 32'd0;
        end else begin
            pose_valid <= 1'b0;

            case (st)
                // ------------------------------------------------------- capture
                S_IDLE: begin
                    if (sample_valid) begin
                        a_x <= ax; a_y <= ay; a_z <= az;
                        g_x <= gx; g_y <= gy; g_z <= gz;
                        last_tick <= tick;
                        dt_l <= dt;
                        pose_tick <= tick;
                        sq_l  <= (ay * ay) + (az * az);   // both squares >= 0
                        i     <= 5'd0;
                        rem   <= 19'd0;
                        root  <= 16'd0;
                        st    <= S_SQRT;
                    end
                end

                // ------------------------------------ integer sqrt, digit by digit
                S_SQRT: begin
                    if (i == 5'd15) begin
                        mag <= $signed({4'd0, root_next_w});
                        i   <= 5'd0;
                        st  <= S_AT1;
                        // atan2(ay, az): X = |az|, Y = |ay|
                        cx  <= (a_z[15]) ? -$signed({{4{a_z[15]}}, a_z})
                                         :  $signed({{4{a_z[15]}}, a_z});
                        cy  <= (a_y[15]) ? -$signed({{4{a_y[15]}}, a_y})
                                         :  $signed({{4{a_y[15]}}, a_y});
                        sx  <= a_z[15];
                        sy  <= a_y[15];
                        cz  <= 20'sd0;
                    end else begin
                        rem  <= rem_next_w;
                        root <= root_next_w;
                        i    <= i + 5'd1;
                    end
                end

                // ------------------------------------------------- CORDIC atan2
                S_AT1, S_AT2: begin
                    if (i == 5'd14) begin            // 15 rotations done
                        if (st == S_AT1) begin
                            roll_a <= sat16(theta_n_w);
                            // atan2(-ax, mag): X = mag >= 0, Y = |ax| with the sign
                            // of (-ax) kept in sy (the CORDIC itself runs on |Y|)
                            cx <= mag;
                            cy <= (a_x[15]) ? -$signed({{4{a_x[15]}}, a_x})
                                            :  $signed({{4{a_x[15]}}, a_x});
                            sx <= 1'b0;
                            // sign of (-ax): ax > 0 -> y < 0; ax == 0 -> y is +0,
                            // which must NOT count as negative (the PC model takes
                            // the sign of the value, not of the input bit)
                            sy <= (a_x != 16'sd0) & ~a_x[15];
                            cz <= 20'sd0;
                            i  <= 5'd0;
                            st <= S_AT2;
                        end else begin
                            pitch_a <= sat16(theta_n_w);
                            gsel <= 2'd0;
                            i    <= 5'd0;
                            st   <= S_GYR;
                        end
                    end else begin
                        cx <= cx_n_w;
                        cy <= cy_n_w;
                        cz <= cz_n_w;
                        i  <= i + 5'd1;
                    end
                end

                // ------------------------------------------------ gyro integrate
                S_GYR: begin
                    case (gsel)
                        2'd0: acc_roll  <= wrap32(acc_roll  + dgyro);
                        2'd1: acc_pitch <= wrap32(acc_pitch + dgyro);
                        default: acc_yaw <= wrap32(acc_yaw + dgyro);
                    endcase
                    if (gsel == 2'd2) begin
                        gsel <= 2'd0;
                        st   <= S_FIL;
                    end else begin
                        gsel <= gsel + 2'd1;
                    end
                end

                // --------------------------- complementary blend, outputs, flags
                S_FIL: begin
                    if (warm < WARMUP[7:0]) begin
                        roll  <= roll_a;
                        pitch <= pitch_a;
                        yaw   <= 16'sd0;
                        acc_roll  <= roll_a;
                        acc_pitch <= pitch_a;
                        acc_yaw   <= 32'sd0;
                        warm <= warm + 8'd1;
                    end else begin
                        // alpha = 31/32 -> one exact shift, no rounding question
                        roll  <= sat16(wrap32(acc_roll  +
                                    (wrap32(roll_a  - acc_roll ) >>> 5)));
                        pitch <= sat16(wrap32(acc_pitch +
                                    (wrap32(pitch_a - acc_pitch) >>> 5)));
                        yaw   <= sat16(acc_yaw);
                        acc_roll  <= wrap32(acc_roll  +
                                    (wrap32(roll_a  - acc_roll ) >>> 5));
                        acc_pitch <= wrap32(acc_pitch +
                                    (wrap32(pitch_a - acc_pitch) >>> 5));
                    end
                    seq        <= seq + 8'd1;
                    pose_valid <= 1'b1;
                    sample_cnt <= sample_cnt + 32'd1;
                    /* flags[3:0] = {bus_stuck, i2c_err, init_done, valid}; [7:4] = 0.
                     * 2026-10-27: the first version concatenated 7 bits into this
                     * 8-bit register, so every flag shifted one place and the top
                     * bit was padded with 0 -- readable only by luck. */
                    flags      <= {4'b0000, bus_stuck, (err_cnt != 8'd0),
                                   (warm >= WARMUP[7:0]), 1'b1};
                    st <= S_IDLE;
                end

                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
