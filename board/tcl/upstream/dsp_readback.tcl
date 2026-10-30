# On-board check of the peak DSP: capture one frame, read the 40-bit peak word
# over VIO, and measure the readback time vs one ILA frame upload.
#
#   vivado -mode batch -source dsp_readback.tcl
#
# 2026-10-25 P1: the word is {valid, frame[12:0], idx[9:0], amp[15:0]}.  This
# script also reads the live `frame_count` probe so tools/dsp_hw_compare.py can
# prove the word and the uploaded ILA frame are the same acquisition.
#
# Values are decoded from the probe's bit string, not via expr: Vivado's Tcl
# truncates 40-bit hex literals to 32 bits, which silently produced a wrong
# FPGA_PEAK_WORD on 2026-10-25 15:56.
set BUILD "D:/daxue/FPGA/fpga_dsp_v2"
set OUT "D:/daxue/FPGA/full_scan_workflow/live_run/dsp_hw"
file mkdir $OUT

open_hw_manager
connect_hw_server -allow_non_jtag
current_hw_target [lindex [get_hw_targets -quiet] 0]
open_hw_target
set dev [lindex [get_hw_devices -quiet -filter {PART == xc7z020}] 0]
if {$dev eq ""} { error "no xc7z020" }
current_hw_device $dev
set_property PROGRAM.FILE [file join $BUILD merged_top.bit] $dev
set_property PROBES.FILE [file join $BUILD merged_top.ltx] $dev
program_hw_devices $dev
refresh_hw_device $dev
puts "PROGRAMMED"

proc vio_by_cell {dev cell} {
    foreach v [get_hw_vios -quiet -of_objects $dev] {
        if {[string match $cell [get_property CELL_NAME $v]]} { return $v }
    }
    return ""
}
proc probe {vio name} {
    set p [get_hw_probes -quiet -of_objects $vio -filter "NAME == $name"]
    if {[llength $p] != 1} { error "probe $name not found" }
    return $p
}
proc wr {vio p v w} {
    set_property OUTPUT_VALUE [format %0${w}X $v] $p
    commit_hw_vio $vio
}

# hex string (with or without 0x) -> binary string, MSB first
proc hex_to_bits {h} {
    set h [string toupper [string trim $h]]
    if {[string match 0x* $h]} { set h [string range $h 2 end] }
    set out ""
    foreach c [split $h ""] {
        switch -- $c {
            A {append out 1010} B {append out 1011} C {append out 1100}
            D {append out 1101} E {append out 1110} F {append out 1111}
            default {append out [format %04b [scan $c %d]]}
        }
    }
    return $out
}
# fixed-width binary substring -> unsigned integer (no 32-bit overflow)
proc bits_to_int {b} {
    set v 0
    foreach c [split $b ""] { set v [expr {$v * 2 + $c}] }
    return $v
}
# a value kept at most 40 bits wide, left padded so field offsets are stable
proc field {bits first last} {
    return [bits_to_int [string range $bits $first $last]]
}

set control [vio_by_cell $dev control]
set motors  [vio_by_cell $dev motors_vio]
set c_ctrl  [probe $control ctrl]
set p_live  [probe $control frame_count]

# the new 40-bit input probe (peak_word)
set peak_p ""
foreach p [get_hw_probes -quiet -of_objects $motors] {
    if {[get_property WIDTH $p] == 40} { set peak_p $p }
}
if {$peak_p eq ""} { error "40-bit peak probe not found" }
puts "PEAK_PROBE: [get_property NAME $peak_p]"

set ila [lindex [get_hw_ilas -quiet -of_objects $dev] 0]
set trig [get_hw_probes -quiet -of_objects $ila -filter {NAME == capture_start}]
catch {set_property TRIGGER_COMPARE_VALUE eq1'b1 $trig}
catch {set_property CONTROL.TRIGGER_POSITION 512 $ila}

# ---------------------------------------------------------------- one frame
set t_arm [clock milliseconds]
run_hw_ila $ila
after 200
wr $control $c_ctrl 3 1
after 2
wr $control $c_ctrl 0 1
set waited 0
set fired 0
while {$waited < 3000} {
    after 100
    incr waited 100
    if {[catch {upload_hw_ila_data $ila} err]} { continue }
    set fired 1
    break
}
if {!$fired} { error "ILA did not trigger" }
set csv [file join $OUT frame.csv]
write_hw_ila_data -force -csv_file $csv [get_hw_ila_data]
set t_ila [expr {[clock milliseconds] - $t_arm}]
puts "ILA_FRAME_MS: $t_ila"

# --------------------------------------------------- peak word + frame stamp
after 300
refresh_hw_vio $motors
set raw [string trim [get_property INPUT_VALUE $peak_p]]
puts "FPGA_PEAK_RAW: $raw"
set bits [hex_to_bits $raw]
while {[string length $bits] < 40} { set bits "0$bits" }
if {[string length $bits] != 40} { error "peak probe is not 40 bits: $raw" }
set valid [field $bits 0 0]
set frame [field $bits 1 13]
set idx   [field $bits 14 23]
set amp   [field $bits 24 39]
puts "FPGA_PEAK_VALID: $valid"
puts "FPGA_PEAK_FRAME: $frame"
puts "FPGA_PEAK_IDX:   $idx"
puts "FPGA_PEAK_AMP:   $amp"
puts "FPGA_PEAK_T_US:  [expr {$idx * 0.2}]"

refresh_hw_vio $control
set live_bits [hex_to_bits [string trim [get_property INPUT_VALUE $p_live]]]
set live [bits_to_int $live_bits]
puts "FPGA_LIVE_FRAME: $live"
puts "FPGA_FRAME_MATCH: [expr {(($live % 8192) == $frame) ? 1 : 0}]"

# ------------------------------------------------------- readback timing
set t0 [clock milliseconds]
set n 200
for {set i 0} {$i < $n} {incr i} {
    refresh_hw_vio $motors
    set v [get_property INPUT_VALUE $peak_p]
}
set t1 [clock milliseconds]
set per [expr {($t1 - $t0) / double($n)}]
puts "VIO_READ_PER_CALL_MS: $per"
puts "SPEEDUP_VS_ILA: [expr {$t_ila / max($per, 0.001)}]"

close_hw_manager
exit 0

