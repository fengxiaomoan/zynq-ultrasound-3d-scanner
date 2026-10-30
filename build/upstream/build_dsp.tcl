# Build the merged acquisition + motors + on-chip peak DSP design.
# Never programs the board.
#
# Adds peak_dsp.sv (1 MHz I/Q demod -> envelope -> windowed peak) and a 40-bit
# VIO input probe.  Everything else is the validated merged build.
#
# 2026-10-25 v2 (P1): the 40-bit word is {valid, frame[12:0], idx[9:0], amp[15:0]}
# so a word can be tied to one acquisition, and peak_dsp resets its NCO phase and
# DC blocker per frame.  v1 stays at D:/fpga_dsp_v1 for reference.
#
# The v2 output lives inside the workspace on purpose: this session's command
# sandbox cannot write to the D: root, so D:/fpga_dsp_v2 could not be created.
set here "<repo-root>/full_scan_workflow/fpga"
set acq_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/AAA-running/13_ultrasound_ila_test_20261019"
set motor_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/11_motor_control_20261019"
set out "<repo-root>/fpga_dsp_v2"
if {[file exists $out]} { error "build dir exists: $out" }

create_project dsp_v1 $out -part xc7z020clg400-2
add_files -norecurse [list \
    [file join $acq_root rtl ultrasound_test_core.sv] \
    [file join $acq_root rtl tx_probe_test.sv] \
    [file join $motor_root rtl stepper_axis.sv] \
    [file join $motor_root rtl motor_pair.sv] \
    [file join $motor_root rtl motor_manual_guard.sv] \
    [file join $here rtl peak_dsp.sv] \
    [file join $here rtl merged_top.sv] ]
add_files -fileset constrs_1 [file join $here merged_top.xdc]
set_property top merged_top [current_fileset]

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

# Motor VIO + 40-bit peak word as the 9th input probe.
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
    CONFIG.C_NUM_PROBE_IN {9} \
    CONFIG.C_PROBE_IN0_WIDTH {2} \
    CONFIG.C_PROBE_IN1_WIDTH {2} \
    CONFIG.C_PROBE_IN2_WIDTH {2} \
    CONFIG.C_PROBE_IN3_WIDTH {2} \
    CONFIG.C_PROBE_IN4_WIDTH {32} \
    CONFIG.C_PROBE_IN5_WIDTH {32} \
    CONFIG.C_PROBE_IN6_WIDTH {32} \
    CONFIG.C_PROBE_IN7_WIDTH {32} \
    CONFIG.C_PROBE_IN8_WIDTH {40} \
] [get_ips merged_vio]

generate_target all [get_ips]
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} { error "synthesis failed" }
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { error "implementation failed" }

open_run impl_1
set cap_regs [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ acq/sample1_reg* || NAME =~ acq/sample2_reg* || NAME =~ acq/sample_otr_reg* || NAME =~ acq/diff_reg*)}]
if {[llength $cap_regs] != 33} { error "ADC capture register coverage mismatch: [llength $cap_regs]" }
report_timing_summary -report_unconstrained -file [file join $out timing.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_utilization -file [file join $out utilization_flat.rpt]
report_drc -file [file join $out drc.rpt]
report_cdc -file [file join $out cdc.rpt]
report_io -file [file join $out io.rpt]
set maxp [get_timing_paths -delay_type max -max_paths 1]
set minp [get_timing_paths -delay_type min -max_paths 1]
if {[llength $maxp]==0 || [llength $minp]==0} { error "missing timing paths" }
if {[get_property SLACK $maxp] < 0 || [get_property SLACK $minp] < 0} { error "timing failed" }
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == {Critical Warning}}]]} {
    error "serious DRC"
}
write_debug_probes -force [file join $out merged_top.ltx]
write_bitstream [file join $out merged_top.bit]
puts "BUILD_PASS: merged acquisition + motors + peak_dsp; no hardware programming performed."
