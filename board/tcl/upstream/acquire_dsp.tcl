# DSP acquisition: per point, one TX frame per read, 40-bit VIO word only.
# No ILA, no CSV: ~5 ms of readback per frame instead of ~500 ms.
#
#   vivado -mode batch -source acquire_dsp.tcl -tclargs \
#          --plan plan_p0_dsp.tcl --out live_run/p0_dsp --frames 3 [--settle 600]
#
# Word: {valid(1), frame(13), idx(10), amp(16)}
#   t_us = idx * 0.2   (56-108 us window)
set BUILD "D:/daxue/FPGA/fpga_dsp_v2"
set PLAN ""
set OUT "D:/daxue/FPGA/full_scan_workflow/live_run/p0_dsp"
set FRAMES 3
set PERIOD 125000
set SETTLE_MS 600

for {set i 0} {$i < [llength $argv]} {incr i} {
    set a [lindex $argv $i]
    switch -- $a {
        --plan   { incr i; set PLAN [lindex $argv $i] }
        --out    { incr i; set OUT  [lindex $argv $i] }
        --frames { incr i; set FRAMES [lindex $argv $i] }
        --period { incr i; set PERIOD [lindex $argv $i] }
        --settle { incr i; set SETTLE_MS [lindex $argv $i] }
        default  { error "unknown argument: $a" }
    }
}
if {$PLAN eq ""} { error "usage: --plan plan.tcl --out DIR \[--frames N\]" }
source $PLAN
file mkdir $OUT

# ------------------------------------------------------------------ connect
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
puts "PROGRAMMED [file join $BUILD merged_top.bit]"

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
proc kick {vio p} {
    if {[expr {[get_property OUTPUT_VALUE $p] != 0}]} { set v 0 } else { set v 1 }
    set_property OUTPUT_VALUE [format %01X $v] $p
    commit_hw_vio $vio
}
proc hx {v} {
    set v [string trim $v]
    if {$v eq ""} { return 0 }
    return [expr "0x$v"]
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
if {$control eq "" || $motors eq ""} { error "VIO cores not found" }
set c_ctrl  [probe $control ctrl]
set m_ctrl  [probe $motors m_ctrl]
set m_steps [probe $motors m_steps]
set m_limit [probe $motors m_limit]
set m_period [probe $motors m_period]
set m_ramp  [probe $motors m_ramp]
set m_delta [probe $motors m_delta]
set m_kick  [probe $motors m_kick]
set m_stat  [probe $motors m_status]
set pose_l  [probe $motors pose_lift]
set pose_r  [probe $motors pose_rot]
set peak_p  [probe $motors peak_word]

proc do_move {motors m_ctrl m_steps m_limit m_period m_ramp m_delta m_kick axis steps dir period} {
    if {$steps <= 0} { return 1 }
    if {$steps > 120000} { error "steps $steps above the RTL ceiling" }
    wr $motors $m_ctrl 0 2
    after 50
    wr $motors $m_period $period 8
    wr $motors $m_ramp 0 4
    wr $motors $m_delta 0 4
    wr $motors $m_limit $steps 5
    wr $motors $m_steps $steps 5
    set base 0
    if {$axis eq "rot"} { set base [expr {$base | 4}] }
    if {$dir} { set base [expr {$base | 8}] }
    wr $motors $m_ctrl $base 2
    after 50
    wr $motors $m_ctrl [expr {$base | 1}] 2
    after 50
    wr $motors $m_ctrl [expr {$base | 3}] 2
    set ms [expr {int(ceil($steps * $period / 50000.0)) + 400}]
    set waited 0
    while {$waited < $ms} {
        after 100
        kick $motors $m_kick
        incr waited 100
    }
    wr $motors $m_ctrl $base 2
    after 50
    return 1
}

# ------------------------------------------------------------------ the scan
set manifest [open [file join $OUT manifest.jsonl] w]
set total [llength $plan_points]
puts "PLAN_POINTS: $total"
set done 0
foreach pt $plan_points {
    array set p $pt
    puts "POINT $p(seq): az=$p(az) z=$p(z) lift=$p(lift) rot=$p(rot)"
    do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
        lift $p(lift) $p(lift_dir) $PERIOD
    do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
        rot $p(rot) $p(rot_dir) $PERIOD
    after $SETTLE_MS
    refresh_hw_vio $motors
    set st [hx [get_property INPUT_VALUE $m_stat]]
    if {$st != 0} { puts "ABORT: motor status=$st"; break }

    for {set f 0} {$f < $FRAMES} {incr f} {
        wr $control $c_ctrl 3 1
        after 1
        wr $control $c_ctrl 0 1
        after 2
        refresh_hw_vio $motors
        set b [hex_to_bits [get_property INPUT_VALUE $peak_p]]
        while {[string length $b] < 40} { set b "0$b" }
        set valid [field $b 0 0]
        set wframe [field $b 1 13]
        set idx   [field $b 14 23]
        set amp   [field $b 24 39]
        set pl [hx [get_property INPUT_VALUE $pose_l]]
        set pr [hx [get_property INPUT_VALUE $pose_r]]
        if {$pl >= 0x80000000} { set pl [expr {$pl - 0x100000000}] }
        if {$pr >= 0x80000000} { set pr [expr {$pr - 0x100000000}] }
        set t_us [expr {$idx * 0.2}]
        puts $manifest [format "{\"seq\":%d,\"frame\":%d,\"word_frame\":%d,\"valid\":%d,\"idx\":%d,\"amp\":%d,\"t_us\":%.1f,\"latitude_deg\":%s,\"azimuth_deg\":%s,\"height_mm\":%s,\"pose_lift\":%d,\"pose_rot\":%d}" \
            $p(seq) $f $wframe $valid $idx $amp $t_us $p(lat) $p(az) $p(z) $pl $pr]
        flush $manifest
        puts "  F$f wf=$wframe valid=$valid idx=$idx t=$t_us amp=$amp"
    }
    incr done
}
close $manifest
puts "ACQUIRE_DONE: $done points"
close_hw_manager
exit 0
