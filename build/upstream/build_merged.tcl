# Build the merged acquisition + motor design. Never programs the board.
#
# Sources: the validated 13号 acquisition core and the validated jog-build motor
# modules, unchanged.  Only merged_top.sv is new.
set here "<repo-root>/full_scan_workflow/fpga"
set acq_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/AAA-running/13_ultrasound_ila_test_20261019"
set motor_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/11_motor_control_20261019"
set out "D:/fpga_merged_v1"
if {[file exists $out]} { error "build dir exists: $out" }

create_project merged_v1 $out -part xc7z020clg400-2
add_files -norecurse [list \
    [file join $acq_root rtl ultrasound_test_core.sv] \
    [file join $acq_root rtl tx_probe_test.sv] \
    [file join $motor_root rtl stepper_axis.sv] \
    [file join $motor_root rtl motor_pair.sv] \
    [file join $motor_root rtl motor_manual_guard.sv] \
    [file join $here rtl merged_top.sv] ]
add_files -fileset constrs_1 [file join $here merged_top.xdc]
set_property top merged_top [current_fileset]

# Acquisition control VIO: identical to the 13号 build.
create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name ultrasound_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN {2} CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {7} CONFIG.C_PROBE_IN1_WIDTH {16} \
    CONFIG.C_PROBE_OUT0_WIDTH {2} CONFIG.C_PROBE_OUT0_INIT_VAL {0x0}] [get_ips ultrasound_vio]

# ILA: identical depth and probe widths to the 13号 build.
create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ultrasound_ila
set_property -dict [list CONFIG.C_NUM_OF_PROBES {10} CONFIG.C_DATA_DEPTH {8192} \
    CONFIG.C_PROBE0_WIDTH {10} CONFIG.C_PROBE1_WIDTH {10} CONFIG.C_PROBE2_WIDTH {11} \
    CONFIG.C_PROBE3_WIDTH {2} CONFIG.C_PROBE4_WIDTH {1} CONFIG.C_PROBE5_WIDTH {1} \
    CONFIG.C_PROBE6_WIDTH {1} CONFIG.C_PROBE7_WIDTH {13} CONFIG.C_PROBE8_WIDTH {1} \
    CONFIG.C_PROBE9_WIDTH {1}] [get_ips ultrasound_ila]

# Motor VIO: same jog registers as motor_jog_v2 plus the two pose latches.
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
    CONFIG.C_NUM_PROBE_IN {8} \
    CONFIG.C_PROBE_IN0_WIDTH {2} \
    CONFIG.C_PROBE_IN1_WIDTH {2} \
    CONFIG.C_PROBE_IN2_WIDTH {2} \
    CONFIG.C_PROBE_IN3_WIDTH {2} \
    CONFIG.C_PROBE_IN4_WIDTH {32} \
    CONFIG.C_PROBE_IN5_WIDTH {32} \
    CONFIG.C_PROBE_IN6_WIDTH {32} \
    CONFIG.C_PROBE_IN7_WIDTH {32} \
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
# Same capture-register check as the 13号 build: the instance name must stay "acq".
set cap_regs [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ acq/sample1_reg* || NAME =~ acq/sample2_reg* || NAME =~ acq/sample_otr_reg* || NAME =~ acq/diff_reg*)}]
if {[llength $cap_regs] != 33} { error "ADC capture register coverage mismatch: [llength $cap_regs]" }
report_timing_summary -report_unconstrained -file [file join $out timing.rpt]
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
puts "BUILD_PASS: merged acquisition + motors; no hardware programming performed."
