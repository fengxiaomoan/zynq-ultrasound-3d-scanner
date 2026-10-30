// tb_i2c_recovery: the bus-recovery path of i2c_master (9 SCL pulses + STOP).
//
// Scenario: a slave (or a short) holds SCL low, so the master's START never sees
// a high SCL and times out.  A blind release would leave SDA low and make the
// next START illegal, so the master must clock 9 extra SCL pulses (with SDA
// released) and then issue a STOP.  This bench proves that happens, and that
// `err` stays set until the next command starts.
`timescale 1ns / 1ps
module tb_i2c_recovery;
    reg clk = 1'b0;
    always #10 clk = ~clk;                 // 50 MHz

    reg rst = 1'b1;
    reg stuck = 1'b1;                      // TB holds SCL low: the "stuck slave"

    wire scl, sda;
    pullup (scl);
    pullup (sda);

    reg  start = 1'b0, stop = 1'b0, send = 1'b0, recv = 1'b0, ack = 1'b0;
    reg  [7:0] tx = 8'd0;
    wire [7:0] rx;
    wire ack_in, busy, done, err;
    wire scl_oe, sda_oe;

    assign scl = (scl_oe | stuck) ? 1'b0 : 1'bz;
    assign sda = sda_oe ? 1'b0 : 1'bz;

    i2c_master #(.CLK_HZ (50_000_000), .SCL_HZ (100_000)) dut (
        .clk (clk), .rst (rst),
        .start (start), .stop (stop), .send (send), .recv (recv),
        .ack_out (ack), .tx_data (tx), .rx_data (rx),
        .ack_in (ack_in), .busy (busy), .done (done), .err (err),
        .scl_oe (scl_oe), .sda_oe (sda_oe),
        .scl_i (scl), .sda_i (sda)
    );

    integer rises = 0;
    always @(posedge scl) rises = rises + 1;

    integer rises_at_err = 0;

    // pulses must be launched just after a negedge, otherwise the 1-cycle pulse
    // can miss the posedge that samples it
    task automatic pulse_start;
        begin @(negedge clk); start = 1'b1; @(negedge clk); start = 1'b0; end
    endtask
    task automatic pulse_stop;
        begin @(negedge clk); stop = 1'b1; @(negedge clk); stop = 1'b0; end
    endtask
    // a command's done is a 1-cycle pulse: sample it at negedges
    task automatic wait_done;
        integer guard;
        begin
            guard = 0;
            @(negedge clk);
            while (done !== 1'b1 && guard < 100000) begin
                @(negedge clk); guard = guard + 1;
            end
            if (done !== 1'b1) begin
                $display("FAIL: no done (state=%0d busy=%b err=%b)", dut.state, busy, err);
                $finish;
            end
        end
    endtask

    initial begin
        #100 rst = 1'b0;
        @(negedge clk);

        // 1) issue a START on a stuck bus -> must time out into recovery
        pulse_start();

        wait (err === 1'b1);
        rises_at_err = rises;
        $display("TIMEOUT_SEEN rises=%0d busy=%b", rises, busy);
        if (busy !== 1'b1) begin
            $display("FAIL: timeout did not keep the command busy (recovery is a command)");
            $finish;
        end

        // 2) let the "slave" let go, recovery can finish now
        #20_000;
        stuck = 1'b0;

        wait_done();
        $display("RECOVERY_DONE pulses=%0d (>=%0d) err=%b busy=%b scl_oe=%b sda_oe=%b",
                 rises - rises_at_err, 9, err, busy, scl_oe, sda_oe);

        if ((rises - rises_at_err) < 9) begin
            $display("FAIL: fewer than 9 recovery clocks");
            $finish;
        end
        if (err !== 1'b1) begin
            $display("FAIL: err cleared too early");
            $finish;
        end
        if (scl_oe !== 1'b0 || sda_oe !== 1'b0) begin
            $display("FAIL: bus not released after recovery");
            $finish;
        end

        // 3) the bus is free again: a new command must clear err and complete
        #2000;
        pulse_start();
        wait_done();
        $display("NEXT_CMD err=%b busy=%b", err, busy);
        if (err !== 1'b0) begin
            $display("FAIL: err not cleared by the next command");
            $finish;
        end
        pulse_stop();
        wait_done();
        $display("I2C_RECOVERY_PASS pulses=%0d", rises - rises_at_err);
        $finish;
    end

    initial begin
        #5_000_000;
        $display("FAIL: global timeout");
        $finish;
    end
endmodule
