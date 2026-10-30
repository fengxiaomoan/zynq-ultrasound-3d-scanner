# DSP presence / coarse-range readout: pulse one frame per point, read the 40-bit
# word, print index/amp/frame.  Also measures the sustainable frame rate so the
# "streaming" claim is measured, not assumed.
#
#   vivado -mode batch -source dsp_presence.tcl -tclargs --frames 3 --period-ms 20
#   vivado -mode batch -source dsp_presence.tcl -tclargs --frames 20 --period-ms 10 --out live_run/presence/rate.csv
#
# The presence decision itself is NOT taken here: tools/dsp_presence.py applies
# the threshold that the session's A/B produced (an absolute amp threshold drifts
# between sessions, see P0_P1_NEXT_STEPS_20261025.md 5d).
set BUILD "D:/daxue/FPGA/fpga_dsp_v2"
set n_frames 3
set period_ms 20
set out_file ""
set k 0
foreach a $argv {
    switch -- $a {
        --frames { set n_frames [lindex $argv [expr {$k+1}]] }
        --period-ms { set period_ms [lindex $argv [expr {$k+1}]] }
        --out { set out_file [lindex $argv [expr {$k+1}]] }
    }
    incr k
}
puts "ARGS frames=$n_frames period_ms=$period_ms out=$out_file"

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
proc bits_to_int {b} {
    set v 0
    foreach c [split $b ""] { set v [expr {$v * 2 + $c}] }
    return $v
}
proc field {bits first last} { return [bits_to_int [string range $bits $first $last]] }

set control [vio_by_cell $dev control]
set motors  [vio_by_cell $dev motors_vio]
set c_ctrl  [probe $control ctrl]
set peak_p  ""
foreach p [get_hw_probes -quiet -of_objects $motors] {
    if {[get_property WIDTH $p] == 40} { set peak_p $p }
}
if {$peak_p eq ""} { error "no 40-bit peak probe" }

proc read_word {motors peak_p} {
    refresh_hw_vio $motors
    set b [hex_to_bits [string trim [get_property INPUT_VALUE $peak_p]]]
    while {[string length $b] < 40} { set b "0$b" }
    return $b
}

if {$out_file ne ""} {
    file mkdir [file dirname $out_file]
    set fh [open $out_file w]
    puts $fh "k,frame,idx,amp,t_us,t_ms"
} else {
    set fh ""
}

set prev_frame -1
set missed 0
set frames -1
set t_first [clock milliseconds]
for {set i 0} {$i < $n_frames} {incr i} {
    set t0 [clock milliseconds]
    set_property OUTPUT_VALUE "3" $c_ctrl
    commit_hw_vio $control
    after 1
    set_property OUTPUT_VALUE "0" $c_ctrl
    commit_hw_vio $control
    set b [read_word $motors $peak_p]
    set frame [field $b 1 13]
    set idx   [field $b 14 23]
    set amp   [field $b 24 39]
    set t_ms [expr {[clock milliseconds] - $t0}]
    puts [format "PRESENCE_FRAME: k=%d frame=%d idx=%d amp=%d t_us=%.1f read_ms=%d" \
          $i $frame $idx $amp [expr {$idx * 0.2}] $t_ms]
    if {$fh ne ""} { puts $fh "$i,$frame,$idx,$amp,[expr {$idx * 0.2}],$t_ms" }
    if {$prev_frame >= 0} {
        set d [expr {$frame - $prev_frame}]
        if {$d == 1} { incr frames }
        if {$d != 1} { incr missed }
    }
    set prev_frame $frame
    set spent [expr {[clock milliseconds] - $t0}]
    set wait [expr {$period_ms - $spent}]
    if {$wait > 0} { after $wait }
}
set t_total [expr {[clock milliseconds] - $t_first}]
puts [format "RATE: %d frames in %d ms -> %.1f Hz (requested %.1f Hz)" \
      $n_frames $t_total [expr {1000.0 * $n_frames / max($t_total,1)}] [expr {1000.0 / $period_ms}]]
puts "FRAME_STEP_MISSES: $missed (0 = every pulse produced exactly one new frame)"
if {$fh ne ""} { close $fh }

close_hw_manager
exit 0
