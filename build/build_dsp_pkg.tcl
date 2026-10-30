# Build the merged acquisition + motors + on-chip peak DSP design.
# Never programs the board.
#
# PACKAGE-LOCAL COPY of build_dsp.tcl.  The flow is unchanged; only the path
# roots are rewritten so the package can be built from any directory.
#
# 2026-10-25 v2 (P1): the 40-bit word is {valid, frame[12:0], idx[9:0], amp[15:0]}
# so a word can be tied to one acquisition, and peak_dsp resets its NCO phase and
# DC blocker per frame.
#
# Output: build/output/fpga_dsp_v2.
set here [file normalize [file dirname [info script]]]
set root [file normalize [file join $here ..]]
set acq_root [file join $root src rtl]
set motor_root [file join $root src rtl]
set out [file join $root build output fpga_dsp_v2]
if {[file exists $out]} { error "build dir exists: $out" }

create_project dsp_v1 $out -part xc7z020clg400-2
add_files -norecurse [list \
    [file join $acq_root ultrasound_test_core.sv] \
    [file join $acq_root tx_probe_test.sv] \
    [file join $motor_root stepper_axis.sv] \
    [file join $motor_root motor_pair.sv] \
    [file join $motor_root motor_manual_guard.sv] \
    [file join $root src rtl peak_dsp.sv] \
    [file join $root src rtl merged_top.sv] ]
add_files -fileset constrs_1 [file join $root src constraints merged_top.xdc]
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
