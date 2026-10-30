# Does the design start frames on its own?  Program the v4 debug build, read the
# 40-bit word + frame_count several times BEFORE any control pulse, then pulse
# once and keep reading.  Any change without a pulse means frames self-start.
set BUILD "<repo-root>/fpga_dsp_v2"
set OUT "<repo-root>/full_scan_workflow/live_run/dsp_stable"
file mkdir $OUT

open_hw_manager
connect_hw_server -allow_non_jtag
current_hw_target [lindex [get_hw_targets -quiet] 0]
open_hw_target
set dev [lindex [get_hw_devices -quiet -filter {PART == xc7z020}] 0]
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
set p_live  [probe $control frame_count]
set peak_p  ""
foreach p [get_hw_probes -quiet -of_objects $motors] {
    if {[get_property WIDTH $p] == 40} { set peak_p $p }
}
if {$peak_p eq ""} { error "no 40-bit peak probe" }

proc sample_state {motors peak_p control p_live tag} {
    refresh_hw_vio $motors
    set b [hex_to_bits [string trim [get_property INPUT_VALUE $peak_p]]]
    while {[string length $b] < 40} { set b "0$b" }
    refresh_hw_vio $control
    set live [bits_to_int [hex_to_bits [string trim [get_property INPUT_VALUE $p_live]]]]
    puts [format "%s word=%s frame=%d idx=%d amp=%d live_frame=%d" $tag $b \
        [field $b 1 13] [field $b 14 23] [field $b 24 39] $live]
}

puts "--- before any pulse ---"
for {set i 0} {$i < 3} {incr i} {
    after 500
    sample_state $motors $peak_p $control $p_live "PRE$i"
}

puts "--- one pulse (ctrl=3 for 2 ms, then 0) ---"
set_property OUTPUT_VALUE "3" $c_ctrl
commit_hw_vio $control
after 2
set_property OUTPUT_VALUE "0" $c_ctrl
commit_hw_vio $control

for {set i 0} {$i < 4} {incr i} {
    after 500
    sample_state $motors $peak_p $control $p_live "POST$i"
}

puts "--- second pulse ---"
set_property OUTPUT_VALUE "3" $c_ctrl
commit_hw_vio $control
after 2
set_property OUTPUT_VALUE "0" $c_ctrl
commit_hw_vio $control

for {set i 0} {$i < 3} {incr i} {
    after 500
    sample_state $motors $peak_p $control $p_live "P2_$i"
}

close_hw_manager
exit 0
