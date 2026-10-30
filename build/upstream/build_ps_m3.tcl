# M3: M2b image + F1 (MPU6050 -> pose_fusion -> AXI pose window).
#
#   vivado -mode batch -nojournal -nolog -notrace -source fpga/ps/build_ps_m3.tcl
#
# This is build_ps_m2.tcl with four additions and NOTHING else changed; the
# datapath instance, PS7 config, VIO/ILA configs and address map are identical to
# the image the M2b evidence was measured on (fpga_ps_m2).
#
#   1. merged_top_bd_f1.v instead of merged_top_bd.v (same shim + F1 block);
#   2. f1 sources (i2c_master / mpu6050_bringup / pose_fusion);
#   3. scl/sda become external ports, constrained by f1_pins.xdc (T10/T11);
#   4. the 128-bit pose word goes to acq_axi_regs' independent 1 kHz channel
#      (registers 0x30..0x3C), so the 176-bit frame payload is untouched.
#
# Output: D:/daxue/FPGA/fpga_ps_m3.  fpga_ps_m2 is never opened or written, so
# the M2b image keeps working as the fallback.
set here [file normalize [file dirname [info script]]]
set root [file normalize [file join $here .. ..]]
set out  "D:/daxue/FPGA/fpga_ps_m3"

set acq_root "D:/daxue/FPGA/FPGA_Contest_Starter_v1.0.0/AAA-running/13_ultrasound_ila_test_20261019"
set motor_root "D:/daxue/FPGA/FPGA_Contest_Starter_v1.0.0/11_motor_control_20261019"

source [file join $here ps7_config.tcl]

if {[file exists $out]} {
    puts "NOTE: removing scratch project $out"
    file delete -force $out
}
create_project ps_m3 $out -part xc7z020clg400-2 -force
set_property target_language Verilog [current_project]

# ------------------------------------------------------------------ RTL sources
add_files -norecurse [list \
    [file join $acq_root rtl ultrasound_test_core.sv] \
    [file join $acq_root rtl tx_probe_test.sv] \
    [file join $motor_root rtl stepper_axis.sv] \
    [file join $motor_root rtl motor_pair.sv] \
    [file join $motor_root rtl motor_manual_guard.sv] \
    [file join $here .. rtl peak_dsp.sv] \
    [file join $here .. rtl peak_centroid.sv] \
    [file join $here .. rtl merged_top.sv] \
    [file join $here merged_top_bd_f1.v] [file join $here acq_axi_regs.v] \
    [file join $here .. f1 i2c_master.sv] \
    [file join $here .. f1 mpu6050_bringup.sv] \
    [file join $here .. f1 pose_fusion.sv] ]

# ------------------------------------------------------------------- IP cores
create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name ultrasound_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN {2} CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {7} CONFIG.C_PROBE_IN1_WIDTH {16} \
    CONFIG.C_PROBE_OUT0_WIDTH {2} CONFIG.C_PROBE_OUT0_INIT_VAL {0x0}] [get_ips ultrasound_vio]

create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ultrasound_ila
set_property -dict [list CONFIG.C_NUM_OF_PROBES {10} CONFIG.C_DATA_DEPTH {8192} \
    CONFIG.C_PROBE0_WIDTH {10} CONFIG.C_PROBE1_WIDTH {10} CONFIG.C_PROBE2_WIDTH {11} \
    CONFIG.C_PROBE3_WIDTH {2} CONFIG.C_PROBE4_WIDTH {1} CONFIG.C_PROBE5_WIDTH {1} \
    CONFIG.C_PROBE6_WIDTH {1} CONFIG.C_PROBE7_WIDTH {13} CONFIG.C_PROBE8_WIDTH {1} \
    CONFIG.C_PROBE9_WIDTH {1}] [get_ips ultrasound_ila]

create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name merged_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_OUT {7} \
    CONFIG.C_PROBE_OUT0_WIDTH {5} \
    CONFIG.C_PROBE_OUT1_WIDTH {18} \
    CONFIG.C_PROBE_OUT2_WIDTH {18} \
    CONFIG.C_PROBE_OUT3_WIDTH {32} \
    CONFIG.C_PROBE_OUT4_WIDTH {16} \
    CONFIG.C_PROBE_OUT5_WIDTH {16} \
    CONFIG.C_PROBE_OUT6_WIDTH {1} \
    CONFIG.C_PROBE_OUT3_INIT_VAL {250000} \
    CONFIG.C_NUM_PROBE_IN {10} \
    CONFIG.C_PROBE_IN0_WIDTH {2} \
    CONFIG.C_PROBE_IN1_WIDTH {2} \
    CONFIG.C_PROBE_IN2_WIDTH {2} \
    CONFIG.C_PROBE_IN3_WIDTH {2} \
    CONFIG.C_PROBE_IN4_WIDTH {32} \
    CONFIG.C_PROBE_IN5_WIDTH {32} \
    CONFIG.C_PROBE_IN6_WIDTH {32} \
    CONFIG.C_PROBE_IN7_WIDTH {32} \
    CONFIG.C_PROBE_IN8_WIDTH {40} \
    CONFIG.C_PROBE_IN9_WIDTH {56} \
] [get_ips merged_vio]

# ------------------------------------------------------------------ block design
create_bd_design system

set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
apply_ps7_config $ps
apply_ps7_mio $ps

create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0 DDR
create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO
connect_bd_intf_net [get_bd_intf_ports DDR] [get_bd_intf_pins processing_system7_0/DDR]
connect_bd_intf_net [get_bd_intf_ports FIXED_IO] [get_bd_intf_pins processing_system7_0/FIXED_IO]

set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0]
set_property -dict [list CONFIG.C_GPIO_WIDTH {32} CONFIG.C_ALL_OUTPUTS {1} \
                         CONFIG.C_IS_DUAL {0}] $gpio

set xbar [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0]
set_property -dict [list CONFIG.NUM_MI {2} CONFIG.NUM_SI {1}] $xbar

connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] \
                    [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] \
                    [get_bd_intf_pins axi_gpio_0/S_AXI]

set fclk [get_bd_pins processing_system7_0/FCLK_CLK0]
set rstn [get_bd_pins processing_system7_0/FCLK_RESET0_N]
foreach p {
    processing_system7_0/M_AXI_GP0_ACLK
    axi_interconnect_0/ACLK
    axi_interconnect_0/S00_ACLK
    axi_interconnect_0/M00_ACLK
    axi_interconnect_0/M01_ACLK
    axi_gpio_0/s_axi_aclk
} { connect_bd_net $fclk [get_bd_pins $p] }
foreach p {
    axi_interconnect_0/ARESETN
    axi_interconnect_0/S00_ARESETN
    axi_interconnect_0/M00_ARESETN
    axi_interconnect_0/M01_ARESETN
    axi_gpio_0/s_axi_aresetn
} { connect_bd_net $rstn [get_bd_pins $p] }

# ------------------------------------ the M2b datapath + F1, as one module cell
set top_cell [create_bd_cell -type module -reference merged_top_bd_f1 merged_top_0]
# Port names must stay bare so merged_top.xdc keeps matching by name.
foreach p {
    sys_clk sys_rst_n ad1_data ad2_data ad1_otr ad2_otr
    ad1_clk ad2_clk ad1_oe ad2_oe tx_burst lift_coils ball_coils
    scl sda
} {
    set before [get_bd_ports -quiet]
    make_bd_pins_external [get_bd_pins merged_top_0/$p]
    foreach np [get_bd_ports -quiet] {
        if {[lsearch -exact $before $np] < 0} {
            puts "  external port [file tail $np] -> $p"
            set_property name $p $np
        }
    }
}

# ------------------------------------------- AXI readout of the DSP words + pose
set regs [create_bd_cell -type module -reference acq_axi_regs acq_regs_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M01_AXI] \
                    [get_bd_intf_pins acq_regs_0/S_AXI]
connect_bd_net $fclk [get_bd_pins acq_regs_0/aclk]
connect_bd_net $rstn [get_bd_pins acq_regs_0/aresetn]
connect_bd_net [get_bd_ports sys_clk]   [get_bd_pins acq_regs_0/clk]
connect_bd_net [get_bd_ports sys_rst_n] [get_bd_pins acq_regs_0/rst_n]
foreach {tap src} {
    peak_word  dbg_peak_word
    cent_word  dbg_cent_word
    pose_rot   dbg_pose_rot
    pose_lift  dbg_pose_lift
    frame_done dbg_frame_done
    f1_pose_word  dbg_f1_pose_word
    f1_pose_valid dbg_f1_pose_valid
} {
    connect_bd_net [get_bd_pins merged_top_0/$src] [get_bd_pins acq_regs_0/$tap]
}

connect_bd_net [get_bd_pins acq_regs_0/o_sel_ext] [get_bd_pins merged_top_0/ext_ctrl_sel]
connect_bd_net [get_bd_pins acq_regs_0/o_trig]    [get_bd_pins merged_top_0/ext_trig]
connect_bd_net [get_bd_pins acq_regs_0/o_tx_en]   [get_bd_pins merged_top_0/ext_tx_en]

assign_bd_address
puts "=== address map ==============================================="
foreach s [get_bd_addr_segs -quiet] {
    puts [format "  %-52s %s" $s [get_property OFFSET $s]]
}

validate_bd_design
save_bd_design

set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
add_files -fileset constrs_1 [file join $here .. merged_top.xdc]
add_files -fileset constrs_1 [file join $here m1b_adc.xdc]
# F1 pins live in their own file so the dsp_v2/c1 builds (no scl/sda) still parse.
add_files -fileset constrs_1 [file join $here f1_pins.xdc]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "=== BD external ports (must match merged_top.xdc + f1_pins.xdc) ===="
foreach p [get_bd_ports] {
    puts [format "  %-16s %s" $p [get_property DIR $p]]
}

# ---------------------------------------------------------------------- build
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} { error "synthesis failed" }
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { error "implementation failed" }

open_run impl_1
report_io -file [file join $out io.rpt]
report_utilization -file [file join $out utilization.rpt]
report_timing_summary -file [file join $out timing.rpt]
write_hw_platform -fixed -force -file [file join $out ps_m3.xsa]

# Pin diff gate: the PL pins must be the M2b set plus exactly T10/T11.  Anything
# else means a constraint did not land on the BD port and the board could be
# driven on the wrong balls.
#
# 2026-10-27: the first version of this block matched `port dir pin` at the start
# of a line; Vivado 2025.1 writes a pipe table (`| T10 | scl | ... |`), so both
# reports parsed to an empty list and the gate printed its header and "passed"
# without comparing anything.  The parser now lives in io_pin_diff.tcl, which
# errors out when a report yields no rows, and this call turns any unexpected
# difference into a build failure instead of a note in the log.
source [file join $here io_pin_diff.tcl]
set m2 "D:/daxue/FPGA/fpga_ps_m2/io.rpt"
if {[file exists $m2]} {
    puts "=== pin diff vs fpga_ps_m2 (expect T10/T11 only) =============="
    set bad [io_pin_diff $m2 [file join $out io.rpt]]
    if {$bad == 2} {
        error "M3_PIN_DIFF_UNPARSED: io.rpt format changed; fix io_pin_diff.tcl before trusting any build"
    }
    if {$bad != 0} {
        error "M3_PIN_DIFF_FAIL: $bad unexpected pin change(s) -- do not burn this image"
    }
    puts "M3_PIN_DIFF_OK"
} else {
    puts "NOTE: no baseline $m2 -- pin diff skipped; run tools/m3_pin_diff.py afterwards"
}

puts "M3_BUILD_DONE $out"
puts "WNS [get_property STATS.WNS [get_runs impl_1]]"
puts "WHS [get_property STATS.WHS [get_runs impl_1]]"
close_project
exit 0
