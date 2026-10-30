# Build: merged acquisition + motors + peak_dsp + peak_centroid (C1).
# Never programs the board.
#
# Same design as build_dsp.tcl (P1.1, bit-exact 40-bit word) plus one module:
#
#   peak_centroid  window centroid of the same 16-bit envelope stream, exposed on
#                  a *second* VIO probe so the verified 40-bit word is untouched:
#                  cent_word = {valid, idx[9:0], sum_w[17:0], sum_kw[26:0]} = 56 bit
#
# Why: on 1248 real frames the window argmax is 2.73 mm spread / 28.8% outliers,
# the window centroid is 1.30 mm / 3.8% (docs/DSP路径复现_20261026.md).  The
# centroid is what makes a continuous (never-stopping) scan possible: a 15 deg
# step at 2.5 ms/step takes 0.43 s, while an ILA frame takes 0.5 s.
#
# The centroid module is verified bit-exactly against tools/dsp_ref.py BEFORE any
# board time is spent:
#
#   python tools/centroid_hw_check.py --csv live_run/cyl_full/raw/p048_f00.csv
#
# (p048_f00 is the frame with the largest sum(w) in cyl_full, 85,897, which is
# the case that exposed the 16-bit denominator truncation in the first draft.)
#
# Output goes to fpga_dsp_c1 and is kept separate from fpga_dsp_v2, whose
# bitstream and LTX are the P1.1 evidence and must not change.
set here "<repo-root>/full_scan_workflow/fpga"
set acq_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/AAA-running/13_ultrasound_ila_test_20261019"
set motor_root "<repo-root>/FPGA_Contest_Starter_v1.0.0/11_motor_control_20261019"
set out "<repo-root>/fpga_dsp_c1"
if {[file exists $out]} { error "build dir exists: $out" }

create_project dsp_c1 $out -part xc7z020clg400-2
add_files -norecurse [list \
    [file join $acq_root rtl ultrasound_test_core.sv] \
    [file join $acq_root rtl tx_probe_test.sv] \
    [file join $motor_root rtl stepper_axis.sv] \
    [file join $motor_root rtl motor_pair.sv] \
    [file join $motor_root rtl motor_manual_guard.sv] \
    [file join $here rtl peak_dsp.sv] \
    [file join $here rtl peak_centroid.sv] \
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

# Motor VIO: 7 outputs + 10 inputs (the 10th is the 56-bit centroid word).
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
puts "BUILD_PASS: merged + peak_dsp + peak_centroid (C1); no hardware programming performed."
