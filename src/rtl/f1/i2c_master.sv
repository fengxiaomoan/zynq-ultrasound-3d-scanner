// Byte-level I2C master, open-drain, single master.
// One command at a time: start / send / recv / stop.  The controller waits for
// `done` before issuing the next command.  SCL is only ever pulled low; the
// pull-up (external) makes it high, and a slave may stretch it low.
//
// 2026-10-26 F1 bring-up: used for MPU6050 at 100 kHz.  Q = quarter period in
// clk cycles, so SCL = CLK_HZ / (4*Q).  Default 50 MHz / 100 kHz -> Q=125.
`timescale 1ns / 1ps
module i2c_master #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer SCL_HZ = 100_000
) (
    input  wire       clk,
    input  wire       rst,       // synchronous, active high
    input  wire       start,     // 1-cycle pulse
    input  wire       stop,      // 1-cycle pulse
    input  wire       send,      // 1-cycle pulse
    input  wire       recv,      // 1-cycle pulse
    input  wire       ack_out,   // for recv: 1 = master ACKs this byte
    input  wire [7:0] tx_data,
    output reg  [7:0] rx_data,
    output reg        ack_in,    // for send: 1 = slave NACKed
    output reg        busy,
    output reg        done,      // 1-cycle pulse when the command finishes
    output reg        err,       // sticky: bus stuck / timeout
    output reg        scl_oe,    // 1 = pull SCL low
    output reg        sda_oe,    // 1 = pull SDA low
    input  wire       scl_i,
    input  wire       sda_i
);
    localparam integer Q  = CLK_HZ / (SCL_HZ * 4);
    // One timeout window covers a whole byte plus ACK (9 bits * 4 phases),
    // with margin for a slave that stretches the clock.
    localparam integer TO = Q * 64;

    localparam [3:0] S_IDLE = 4'd0, S_START = 4'd1, S_TX = 4'd2, S_ACKTX = 4'd3,
                     S_RX = 4'd4, S_ACKRX = 4'd5, S_STOP = 4'd6, S_REC = 4'd7;

    reg [3:0]  state;
    reg [1:0]  phase;
    reg [2:0]  bitc;
    reg [15:0] qcnt;
    reg [15:0] tocnt;
    reg [7:0]  shreg;
    reg        ack_lat;
    reg [3:0]  rec_bit;

    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE; phase <= 2'd0; bitc <= 3'd0; qcnt <= 16'd0; tocnt <= 16'd0;
            scl_oe <= 1'b0; sda_oe <= 1'b0; busy <= 1'b0; done <= 1'b0;
            err <= 1'b0; ack_in <= 1'b0; rx_data <= 8'd0; shreg <= 8'd0; ack_lat <= 1'b0;
            rec_bit <= 4'd0;
        end else begin
            done <= 1'b0;
            // `err` is STICKY between commands (cleared when the next command
            // starts): a recovery after a stuck bus must still be visible to the
            // caller that looks at err together with done.

            if (state == S_IDLE) begin
                tocnt <= 16'd0;
                // Keep the bus state: after START SDA must stay low, after a
                // byte SCL must stay low.  Releasing here would fake a STOP.
                if (start) begin
                    err <= 1'b0;
                    state <= S_START; phase <= 2'd0; qcnt <= 16'd0; busy <= 1'b1;
                end else if (send) begin
                    err <= 1'b0;
                    shreg <= tx_data; bitc <= 3'd0; state <= S_TX; phase <= 2'd0;
                    qcnt <= 16'd0; busy <= 1'b1;
                end else if (recv) begin
                    err <= 1'b0;
                    shreg <= 8'd0; bitc <= 3'd0; ack_lat <= ack_out; state <= S_RX;
                    phase <= 2'd0; qcnt <= 16'd0; busy <= 1'b1;
                end else if (stop) begin
                    err <= 1'b0;
                    state <= S_STOP; phase <= 2'd0; qcnt <= 16'd0; busy <= 1'b1;
                end
            end else begin
                tocnt <= tocnt + 16'd1;

                if (tocnt > TO) begin
                    // Bus stuck (SCL held low) or a slave never responded.  Do not
                    // just release the lines: a slave that was mid-byte holds SDA
                    // low and the next START is then illegal.  Clock 9 extra SCL
                    // pulses with SDA released so the slave shifts its byte out and
                    // lets go, then issue a STOP (I2C-bus specification 3.1.16).
                    err      <= 1'b1;
                    state    <= S_REC;
                    rec_bit  <= 4'd0;
                    phase    <= 2'd0;
                    qcnt     <= 16'd0;
                    tocnt    <= 16'd0;
                    scl_oe   <= 1'b0;
                    sda_oe   <= 1'b0;
                end else begin
                    case (state)
                        // ---------------------------------------------------- START
                        S_START: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b0; sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin
                                        if (scl_i) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    end else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    sda_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    scl_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin
                                        state <= S_IDLE; busy <= 1'b0; done <= 1'b1;
                                        qcnt <= 16'd0; phase <= 2'd0;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // ------------------------------------------------------- TX
                        S_TX: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= ~shreg[7];
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                2'd2: begin
                                    if (qcnt == Q - 1) begin phase <= 2'd3; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    scl_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin
                                        shreg <= {shreg[6:0], 1'b0};
                                        qcnt  <= 16'd0;
                                        phase <= 2'd0;
                                        if (bitc == 3'd7) state <= S_ACKTX;
                                        else bitc <= bitc + 3'd1;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // ----------------------------------------------------- ACK/TX
                        S_ACKTX: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                2'd2: begin
                                    if (qcnt == Q - 1) begin ack_in <= sda_i; phase <= 2'd3; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    scl_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin
                                        state <= S_IDLE; busy <= 1'b0; done <= 1'b1;
                                        qcnt <= 16'd0; phase <= 2'd0;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // ------------------------------------------------------- RX
                        S_RX: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                2'd2: begin
                                    if (qcnt == Q - 1) begin
                                        shreg <= {shreg[6:0], sda_i};
                                        phase <= 2'd3; qcnt <= 16'd0;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    scl_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin
                                        qcnt  <= 16'd0;
                                        phase <= 2'd0;
                                        if (bitc == 3'd7) state <= S_ACKRX;
                                        else bitc <= bitc + 3'd1;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // ----------------------------------------------------- ACK/RX
                        S_ACKRX: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= ack_lat;
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                2'd2: begin
                                    if (qcnt == Q - 1) begin phase <= 2'd3; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    scl_oe <= 1'b1; sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin
                                        rx_data <= shreg;
                                        state <= S_IDLE; busy <= 1'b0; done <= 1'b1;
                                        qcnt <= 16'd0; phase <= 2'd0;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // ----------------------------------------------------- STOP
                        S_STOP: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= 1'b1;
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin
                                        state <= S_IDLE; busy <= 1'b0; done <= 1'b1;
                                        qcnt <= 16'd0; phase <= 2'd0;
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        // -------------------------------------------------- RECOVERY
                        // 9 SCL pulses with SDA released, then the STOP: the slave
                        // finishes shifting out its byte and lets SDA go.  S_STOP
                        // ends the command (done/busy); err stays set.
                        S_REC: begin
                            case (phase)
                                2'd0: begin
                                    scl_oe <= 1'b1; sda_oe <= 1'b0;
                                    if (qcnt == Q - 1) begin phase <= 2'd1; qcnt <= 16'd0; end
                                    else qcnt <= qcnt + 16'd1;
                                end
                                2'd1: begin
                                    scl_oe <= 1'b0;
                                    if (qcnt == Q - 1 && scl_i) begin phase <= 2'd2; qcnt <= 16'd0; end
                                    else if (scl_i) qcnt <= qcnt + 16'd1;
                                end
                                default: begin
                                    if (qcnt == Q - 1) begin
                                        qcnt  <= 16'd0;
                                        phase <= 2'd0;
                                        if (rec_bit == 4'd8) begin
                                            state  <= S_STOP;
                                            scl_oe <= 1'b1;
                                            sda_oe <= 1'b1;
                                        end else begin
                                            rec_bit <= rec_bit + 4'd1;
                                        end
                                    end else qcnt <= qcnt + 16'd1;
                                end
                            endcase
                        end

                        default: state <= S_IDLE;
                    endcase
                end
            end
        end
    end
endmodule
