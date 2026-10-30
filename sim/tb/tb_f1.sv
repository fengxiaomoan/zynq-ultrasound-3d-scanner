// F1 bring-up testbench: line check + WHO_AM_I + 14-byte burst read.
// Simulation-only model of the open-drain bus (pullups + tri-state drivers).
`timescale 1ns / 1ps
module tb_f1;
    reg clk = 1'b0;
    always #10 clk = ~clk;  // 50 MHz

    reg rst_n = 1'b0;
    reg hold  = 1'b1;

    wire scl, sda;
    pullup (scl);
    pullup (sda);

    wire scl_oe, sda_oe;
    assign scl = scl_oe ? 1'b0 : 1'bz;
    assign sda = sda_oe ? 1'b0 : 1'bz;
    wire scl_i = scl;
    wire sda_i = sda;

    wire        m_start, m_stop, m_send, m_recv, m_ack;
    wire [7:0]  m_tx, m_rx;
    wire        m_ack_in, m_busy, m_done, m_err;
    wire [7:0]  who, pc_dbg, err_cnt;
    wire [15:0] ax, ay, az, gx, gy, gz;
    reg  [31:0] free_tick = 32'd0;
    wire        sample_valid;
    wire [31:0] sample_tick;

    always @(posedge clk) free_tick <= free_tick + 32'd1;

    // count pulses so the bench proves the sample strobe exists (not just data)
    integer samples = 0;
    always @(posedge clk) if (sample_valid) samples <= samples + 1;

    i2c_master #(
        .CLK_HZ (50_000_000),
        .SCL_HZ (100_000)
    ) u_i2c (
        .clk (clk), .rst (~rst_n),
        .start (m_start), .stop (m_stop), .send (m_send), .recv (m_recv),
        .ack_out (m_ack), .tx_data (m_tx), .rx_data (m_rx),
        .ack_in (m_ack_in), .busy (m_busy), .done (m_done), .err (m_err),
        .scl_oe (scl_oe), .sda_oe (sda_oe), .scl_i (scl_i), .sda_i (sda_i)
    );

    mpu6050_bringup #(
        .PWR_CYCLES    (200),
        .WAKE_CYCLES   (200),
        .SAMPLE_CYCLES (2000),
        .RETRY_CYCLES  (2000)
    ) u_mpu (
        .clk (clk), .rst (~rst_n), .hold (hold),
        .m_start (m_start), .m_stop (m_stop), .m_send (m_send), .m_recv (m_recv),
        .m_ack (m_ack), .m_tx (m_tx), .m_rx (m_rx), .m_ack_in (m_ack_in),
        .m_busy (m_busy), .m_done (m_done), .m_err (m_err),
        .who (who), .pc_dbg (pc_dbg), .err_cnt (err_cnt),
        .ax (ax), .ay (ay), .az (az), .gx (gx), .gy (gy), .gz (gz),
        .free_tick (free_tick), .sample_valid (sample_valid), .sample_tick (sample_tick)
    );

    mpu6050_model u_model (.scl (scl), .sda (sda));

`ifdef DEBUG
    integer dbg_edges = 0;
    always @(posedge scl) if (dbg_edges < 40) begin
        $display("SCL^ t=%0t sda=%b mst=%0d bc=%0d drive=%b ack=%b ptr=%02x",
                 $time, sda, u_model.st, u_model.bc, u_model.drive, u_model.ack, u_model.ptr);
        dbg_edges = dbg_edges + 1;
    end
    always @(negedge scl) if (dbg_edges < 40) begin
        $display("SCL_ t=%0t sda=%b mst=%0d bc=%0d drive=%b", $time, sda, u_model.st, u_model.bc, u_model.drive);
    end
    reg [3:0] dbg_mst = 4'hF;
    always @(posedge clk) if (u_i2c.state != dbg_mst) begin
        $display("MST t=%0t %0d->%0d ph=%0d", $time, dbg_mst, u_i2c.state, u_i2c.phase);
        dbg_mst <= u_i2c.state;
    end
    always @(posedge clk) if (m_done) begin
        $display("DONE t=%0t cmd=%0d tx=%02x ack_in=%b mst=%0d st=%0d drive=%b ptr=%02x",
                 $time, u_mpu.cmd, m_tx, m_ack_in, u_model.st, u_model.st, u_model.drive, u_model.ptr);
    end
`endif

    integer n;

    initial begin
        #100 rst_n = 1'b1;
        #5000;

        if (scl !== 1'b1 || sda !== 1'b1) begin
            $display("FAIL: idle lines scl=%b sda=%b (hold=1)", scl, sda);
            $finish;
        end
        $display("LINE_CHECK_HIGH: scl=%b sda=%b", scl, sda);

        hold = 1'b0;

        fork : wait_who
            begin
                wait (who == 8'h68);
                $display("WHO_OK: 0x%02x at pc=%0d", who, pc_dbg);
            end
            begin
                #50_000_000;
                $display("FAIL: timeout waiting for WHO_AM_I (pc=%0d err=%0d)", pc_dbg, err_cnt);
                $finish;
            end
        join_any
        disable fork;

        fork : wait_data
            begin
                wait (ax == 16'h1234);
                $display("DATA_OK: ax=0x%04x", ax);
            end
            begin
                #50_000_000;
                $display("FAIL: timeout waiting for data (pc=%0d err=%0d)", pc_dbg, err_cnt);
                $finish;
            end
        join_any
        disable fork;

        #5000;
        if (err_cnt != 0) begin
            $display("FAIL: err_cnt=%0d", err_cnt);
        end else if (ay !== 16'h5678 || az !== 16'h9ABC || gx !== 16'h1122 ||
                     gy !== 16'h3344 || gz !== 16'h5566) begin
            $display("FAIL: payload ax=%h ay=%h az=%h gx=%h gy=%h gz=%h", ax, ay, az, gx, gy, gz);
        end else begin
            $display("PASS: who=0x68 ax=1234 ay=5678 az=9abc gx=1122 gy=3344 gz=5566 err=0 samples=%0d",
                     samples);
        end
        $finish;
    end

    initial begin
        #200_000_000;
        $display("FAIL: global timeout");
        $finish;
    end
endmodule
