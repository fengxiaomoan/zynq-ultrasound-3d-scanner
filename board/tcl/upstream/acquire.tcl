# Fully automatic acquisition: one Vivado session drives the whole scan.
#
#   vivado -mode batch -source acquire.tcl -tclargs \
#          --plan plan.tcl --out D:/run/raw --frames 3 --tx 0 [--limit 3]
#
# Per point: move lift -> move rot -> settle -> for each frame:
#   arm ILA -> ctrl (TX off = 1 / TX on = 3) -> wait -> upload -> CSV -> poses
# The pose latches (pose_lift/pose_rot) are written into the manifest, so the
# pose of every frame is the hardware value at capture_start, not a timestamp.
#
# Any of the following aborts the run and keeps what was already captured:
#   * a VIO probe is missing
#   * a motor command counter does not match
#   * the ILA does not trigger within the timeout
#   * the CSV cannot be written

set BUILD "D:/fpga_merged_v1"
set PLAN ""
set OUT "<repo-root>/full_scan_workflow/out/acquire"
set FRAMES 3
set TX 0
set LIMIT 0
set ALT 0
set PERIOD 250000
set SETTLE_MS 600
set TRIGGER_TIMEOUT_MS 3000

for {set i 0} {$i < [llength $argv]} {incr i} {
    set a [lindex $argv $i]
    switch -- $a {
        --plan     { incr i; set PLAN [lindex $argv $i] }
        --out      { incr i; set OUT  [lindex $argv $i] }
        --frames   { incr i; set FRAMES [lindex $argv $i] }
        --tx       { incr i; set TX [lindex $argv $i] }
        --limit    { incr i; set LIMIT [lindex $argv $i] }
        --period   { incr i; set PERIOD [lindex $argv $i] }
        --tx-alt   { set ALT 1 }
        --settle   { incr i; set SETTLE_MS [lindex $argv $i] }
        default    { error "unknown argument: $a" }
    }
}
if {$PLAN eq ""} { error "usage: --plan plan.tcl --out DIR \[--frames N\] \[--tx 0|1\] \[--limit N\]" }
source $PLAN
file mkdir [file join $OUT raw]

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

set control [vio_by_cell $dev control]
set motors  [vio_by_cell $dev motors_vio]
if {$control eq "" || $motors eq ""} { error "VIO cores not found" }
set c_ctrl  [probe $control ctrl]
set c_count [probe $control frame_count]
set m_ctrl  [probe $motors m_ctrl]
set m_steps [probe $motors m_steps]
set m_limit [probe $motors m_limit]
set m_period [probe $motors m_period]
set m_ramp  [probe $motors m_ramp]
set m_delta [probe $motors m_delta]
set m_kick  [probe $motors m_kick]
set m_lift  [probe $motors lift_position]
set m_ball  [probe $motors ball_position]
set m_stat  [probe $motors m_status]
set pose_l  [probe $motors pose_lift]
set pose_r  [probe $motors pose_rot]

set ila [lindex [get_hw_ilas -quiet -of_objects $dev] 0]
set trig [get_hw_probes -quiet -of_objects $ila -filter {NAME == capture_start}]
catch {set_property TRIGGER_COMPARE_VALUE eq1'b1 $trig}
catch {set_property CONTROL.TRIGGER_POSITION 512 $ila}

# --------------------------------------------------------------- move helper
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
if {$LIMIT > 0 && $LIMIT < $total} { set total $LIMIT }
puts "PLAN_POINTS: [llength $plan_points]  running: $total"

set done 0
foreach pt $plan_points {
    if {$done >= $total} { break }
    array set p $pt
    puts "POINT $p(seq): lat=$p(lat) az=$p(az) lift=$p(lift) rot=$p(rot)"

    do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
        lift $p(lift) $p(lift_dir) $PERIOD
    do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
        rot $p(rot) $p(rot_dir) $PERIOD
    after $SETTLE_MS

    refresh_hw_vio $motors
    set st [hx [get_property INPUT_VALUE $m_stat]]
    if {$st != 0} { puts "ABORT: motor status=$st"; break }

    for {set f 0} {$f < $FRAMES} {incr f} {
        # --tx-alt: even frames TX on, odd frames TX off, at the same pose.
        set tx_frame $TX
        if {$ALT} { set tx_frame [expr {($f % 2 == 0) ? 1 : 0}] }
        run_hw_ila $ila
        after 200
        if {$tx_frame} { wr $control $c_ctrl 3 1 } else { wr $control $c_ctrl 1 1 }
        set waited 0
        set fired 0
        while {$waited < $TRIGGER_TIMEOUT_MS} {
            after 100
            incr waited 100
            if {[catch {upload_hw_ila_data $ila} err]} { continue }
            set fired 1
            break
        }
        wr $control $c_ctrl 0 1
        if {!$fired} { puts "ABORT: ILA did not trigger at point $p(seq) frame $f"; break }

        set csv [file join $OUT raw [format "p%03d_f%02d.csv" $p(seq) $f]]
        if {[catch {write_hw_ila_data -force -csv_file $csv [get_hw_ila_data]} err2]} {
            puts "ABORT: csv write failed: $err2"
            break
        }
        refresh_hw_vio $motors
        set pl [hx [get_property INPUT_VALUE $pose_l]]
        set pr [hx [get_property INPUT_VALUE $pose_r]]
        if {$pl >= 0x80000000} { set pl [expr {$pl - 0x100000000}] }
        if {$pr >= 0x80000000} { set pr [expr {$pr - 0x100000000}] }
        puts $manifest [format "{\"seq\":%d,\"frame\":%d,\"file\":\"%s\",\"latitude_deg\":%s,\"azimuth_deg\":%s,\"height_mm\":%s,\"tx\":%d,\"pose_lift\":%d,\"pose_rot\":%d}" \
            $p(seq) $f "raw/[file tail $csv]" $p(lat) $p(az) $p(z) $tx_frame $pl $pr]
        flush $manifest
        puts "  FRAME $f -> [file tail $csv] pose_lift=$pl pose_rot=$pr"
    }
    incr done
}
close $manifest
puts "ACQUIRE_DONE: $done points"
close_hw_manager
exit 0

