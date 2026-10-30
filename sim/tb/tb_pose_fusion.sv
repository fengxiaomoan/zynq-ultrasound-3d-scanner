// tb_pose_fusion: replays tools/f1_pose_ref.py vectors through pose_fusion.sv and
// compares bit for bit.
//
// This is the E6 gate: the vectors carry the *PC model's* outputs, so a mismatch
// means either the RTL or the model is wrong -- there is no tolerance knob.
// It also measures the sample_valid -> pose_valid latency of every sample and
// fails if it is not constant (that is E1, "fixed latency", in simulation).
//
//   xvlog ../<repo>/fpga/f1/pose_fusion.sv tb_pose_fusion.sv
//   xelab tb_pose_fusion -s tb_pose -debug typical
//   xsim tb_pose -R -testplusarg "VEC=pose_vectors.txt"
`timescale 1ns / 1ps
module tb_pose_fusion;
    localparam integer DT_MIN = 10_000;
    localparam integer DT_MAX = 200_000;

    reg clk = 1'b0;
    always #10 clk = ~clk;               // 50 MHz

    reg rst = 1'b1;

    reg  signed [15:0] ax = 16'sd0, ay = 16'sd0, az = 16'sd0;
    reg  signed [15:0] gx = 16'sd0, gy = 16'sd0, gz = 16'sd0;
    reg  [31:0] tick = 32'd0;
    reg         sample_valid = 1'b0;

    wire signed [15:0] roll, pitch, yaw;
    wire [7:0]  seq, flags;
    wire [31:0] pose_tick, sample_cnt;
    wire        pose_valid;
    wire [5:0]  state_dbg;

    pose_fusion dut (
        .clk (clk), .rst (rst),
        .sample_valid (sample_valid), .tick (tick),
        .ax (ax), .ay (ay), .az (az), .gx (gx), .gy (gy), .gz (gz),
        .err_cnt (8'd0), .bus_stuck (1'b0),
        .roll (roll), .pitch (pitch), .yaw (yaw),
        .seq (seq), .pose_tick (pose_tick), .pose_valid (pose_valid),
        .flags (flags), .sample_cnt (sample_cnt), .state_dbg (state_dbg)
    );

    integer fd, rr, n, bad, lat_min, lat_max, lat_last, lat;
    integer v_ax, v_ay, v_az, v_gx, v_gy, v_gz, v_dt, e_r, e_p, e_y;
    reg [1023:0] vecpath;

    task automatic send(input integer rax, ray, raz, rgx, rgy, rgz, rdt,
                        input integer er, ep, ey);
        integer cyc;
        begin
            // let pose_valid from the previous sample fall and the FSM park in
            // S_IDLE, otherwise a 1-cycle sample_valid pulse can land while the
            // FSM is still finishing (it only samples in S_IDLE)
            repeat (2) @(negedge clk);
            // 16-bit two's complement from the decimal vector fields
            ax = rax[15:0]; ay = ray[15:0]; az = raz[15:0];
            gx = rgx[15:0]; gy = rgy[15:0]; gz = rgz[15:0];
            tick = tick + rdt[31:0];
            @(negedge clk); sample_valid = 1'b1;
            @(negedge clk); sample_valid = 1'b0;
            cyc = 0;
            while (pose_valid !== 1'b1 && cyc < 400) begin
                @(negedge clk);
                cyc = cyc + 1;
            end
            if (pose_valid !== 1'b1) begin
                $display("FAIL: no pose_valid after %0d samples", n);
                $finish;
            end
            lat = cyc + 1;
            if (lat < lat_min) lat_min = lat;
            if (lat > lat_max) lat_max = lat;
            lat_last = lat;

            n = n + 1;
            if (roll !== er[15:0] || pitch !== ep[15:0] || yaw !== ey[15:0]) begin
                bad = bad + 1;
                if (bad <= 8)
                    $display("MISMATCH n=%0d rtl=%0d/%0d/%0d ref=%0d/%0d/%0d acc=%0d/%0d ax=%0d ay=%0d az=%0d dt=%0d",
                             n, roll, pitch, yaw, er, ep, ey,
                             dut.roll_a, dut.pitch_a, ax, ay, az, rdt);
            end
        end
    endtask

    initial begin
        n = 0; bad = 0; lat_min = 1_000_000; lat_max = 0; lat_last = 0; lat = 0;

        if (!$value$plusargs("VEC=%s", vecpath)) vecpath = "pose_vectors.txt";
        fd = $fopen(vecpath, "r");
        if (fd == 0) begin
            $display("FAIL: cannot open vector file");
            $finish;
        end

        #100 rst = 1'b0;
        @(negedge clk);

        rr = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d",
                     v_ax, v_ay, v_az, v_gx, v_gy, v_gz, v_dt, e_r, e_p, e_y);
        while (rr == 10) begin
            send(v_ax, v_ay, v_az, v_gx, v_gy, v_gz, v_dt, e_r, e_p, e_y);
            rr = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d",
                         v_ax, v_ay, v_az, v_gx, v_gy, v_gz, v_dt, e_r, e_p, e_y);
        end
        $fclose(fd);

        $display("SAMPLES=%0d MISMATCHES=%0d LATENCY_MIN=%0d LATENCY_MAX=%0d CYCLES=%0d",
                 n, bad, lat_min, lat_max, lat_last);
        if (bad == 0 && n > 0 && lat_min == lat_max)
            $display("POSE_FUSION_PASS n=%0d latency=%0d cycles", n, lat_min);
        else if (bad == 0)
            $display("POSE_FUSION_FAIL: latency not constant (%0d..%0d)",
                     lat_min, lat_max);
        else
            $display("POSE_FUSION_FAIL: %0d of %0d samples differ", bad, n);
        $finish;
    end

    initial begin
        #50_000_000;
        $display("FAIL: global timeout");
        $finish;
    end
endmodule
