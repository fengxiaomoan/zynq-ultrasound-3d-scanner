// Behavioural MPU6050 I2C slave for the F1 bring-up testbench.
// Register file with WHO_AM_I=0x68 and a fixed pattern at 0x3B..0x48.
`timescale 1ns / 1ps
module mpu6050_model (
    input  wire scl,
    inout  wire sda
);
    localparam [3:0] M_IDLE = 4'd0, M_ADDR = 4'd1, M_ACKA = 4'd2, M_WDATA = 4'd3,
                     M_ACKW = 4'd4, M_RDATA = 4'd5, M_ACKR = 4'd6;

    reg [7:0] mem [0:127];
    reg [7:0] ptr;
    reg [7:0] sh, dout;
    reg [3:0] st;
    reg [3:0] bc;
    reg       rw, ack, drive, first;
    integer   i;

    assign sda = drive ? 1'b0 : 1'bz;

    initial begin
        for (i = 0; i < 128; i = i + 1) mem[i] = 8'h00;
        mem[8'h75] = 8'h68;
        mem[8'h3B] = 8'h12; mem[8'h3C] = 8'h34;
        mem[8'h3D] = 8'h56; mem[8'h3E] = 8'h78;
        mem[8'h3F] = 8'h9A; mem[8'h40] = 8'hBC;
        mem[8'h41] = 8'hDE; mem[8'h42] = 8'hF0;
        mem[8'h43] = 8'h11; mem[8'h44] = 8'h22;
        mem[8'h45] = 8'h33; mem[8'h46] = 8'h44;
        mem[8'h47] = 8'h55; mem[8'h48] = 8'h66;
        ptr = 8'h00; sh = 8'h00; dout = 8'h00;
        st = M_IDLE; bc = 4'd0; rw = 1'b0; ack = 1'b0; drive = 1'b0; first = 1'b0;
    end

    // START / STOP conditions
    always @(negedge sda) if (scl) begin st <= M_ADDR; bc <= 4'd0; drive <= 1'b0; first <= 1'b0; end
    always @(posedge sda) if (scl) begin st <= M_IDLE; drive <= 1'b0; end

    always @(posedge scl) if (st != M_IDLE) begin
        case (st)
            M_ADDR: begin
                sh <= {sh[6:0], sda};
                if (bc == 4'd7) begin
                    st  <= M_ACKA;
                    bc  <= 4'd0;
                    ack <= ({sh[6:0], sda} >> 1) == 7'h68;
                    rw  <= sda;
                    first <= ~sda;   // write address: next byte is the register
                end else bc <= bc + 4'd1;
            end
            M_ACKA: begin
                if (rw) begin dout <= mem[ptr]; bc <= 4'd0; st <= M_RDATA; end
                else st <= M_WDATA;
            end
            M_WDATA: begin
                sh <= {sh[6:0], sda};
                if (bc == 4'd7) begin st <= M_ACKW; bc <= 4'd0; end
                else bc <= bc + 4'd1;
            end
            M_ACKW: begin
                if (first) begin
                    ptr   <= sh;       // register address
                    first <= 1'b0;
                end else begin
                    mem[ptr] <= sh;    // data byte
                    ptr      <= ptr + 8'd1;
                end
                st <= M_WDATA;         // further bytes stay data until a START
                bc <= 4'd0;
            end
            M_RDATA: begin
                if (bc == 4'd7) begin st <= M_ACKR; bc <= 4'd0; end
                else bc <= bc + 4'd1;
            end
            M_ACKR: begin
                if (sda == 1'b0) begin
                    ptr  <= ptr + 8'd1;
                    dout <= mem[ptr + 8'd1];
                    bc   <= 4'd0;
                    st   <= M_RDATA;
                end else begin
                    st <= M_IDLE;
                end
            end
            default: st <= M_IDLE;
        endcase
    end

    always @(negedge scl) if (st != M_IDLE) begin
        case (st)
            M_ADDR:  drive <= 1'b0;   // release SDA for the master's bits
            M_ACKA:  drive <= ack;
            M_WDATA: drive <= 1'b0;   // release after the address ACK
            M_ACKW:  drive <= 1'b1;
            M_RDATA: begin drive <= ~dout[7]; dout <= {dout[6:0], 1'b0}; end
            M_ACKR:  drive <= 1'b0;
            default: drive <= 1'b0;
        endcase
    end

`ifdef DEBUG
    always @(posedge scl) if ($time > 290000 && $time < 400000)
        $display("MODEL t=%0t st=%0d bc=%0d sda=%b drive=%b dout=%02x ptr=%02x",
                 $time, st, bc, sda, drive, dout, ptr);
`endif
endmodule
