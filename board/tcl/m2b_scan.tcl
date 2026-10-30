# m2b_scan.tcl — drive the stage for the M2b (PS) path.
#
# The PS firmware owns the frame trigger (CTRL.sel_ext=1) and the readout; this
# script only moves the motors through the `motors` VIO core, exactly the way
# fpga/acquire_continuous.tcl does.  VIO triggers are ignored while sel_ext=1,
# so the two paths do not fight.
#
#   vivado -mode batch -nojournal -nolog -notrace -source fpga/ps/m2b_scan.tcl \
#     -tclargs --revs 1 --period 125000 --layers 1
#
# Options
#   --revs N        revolutions per layer (default 1)
#   --period P      step period in 50 MHz cycles (default 125000 = 35.16 deg/s)
#   --layers L      layers to run (default 1); layer k>0 first moves the lift
#                   by --lift-delta (default 4096 counts = 2 mm, down)
#   --lift-delta D  signed lift move between layers (default 4096, direction down)
#   --settle MS     settle after a lift move (default 600)
#   --restore       undo the lift moves at the end
#
# The PS side needs no changes: it keeps triggering at PERIOD_MS and binning by
# pose_rot; /state then shows 24 azimuth cells per layer instead of one.

set REVS 1
set PERIOD 125000
set LAYERS 1
set LIFT_DELTA 4096
set ROOT [file normalize [file join [file dirname [info script]] .. ..]]
set SETTLE 600
set RESTORE 0

for {set i 0} {$i < [llength $argv]} {incr i} {
    set a [lindex $argv $i]
    switch -- $a {
        --revs       { incr i; set REVS [lindex $argv $i] }
        --period     { incr i; set PERIOD [lindex $argv $i] }
        --layers     { incr i; set LAYERS [lindex $argv $i] }
        --lift-delta { incr i; set LIFT_DELTA [lindex $argv $i] }
        --settle     { incr i; set SETTLE [lindex $argv $i] }
        --restore    { set RESTORE 1 }
        default      { error "unknown argument: $a" }
    }
}

set CPR 4096

open_hw_manager
connect_hw_server -allow_non_jtag
set tgt [lindex [get_hw_targets -quiet] 0]
if {$tgt eq ""} { error "M2B_SCAN_NO_TARGET" }
current_hw_target $tgt
open_hw_target
set dev [lindex [get_hw_devices -quiet -filter {PART == xc7z020}] 0]
if {$dev eq ""} { error "M2B_SCAN_NO_DEVICE (is the PL programmed?)" }
current_hw_device $dev
# the VIO cores only get their names from the probes file
set ltx [file join $ROOT board bitstream ps_m3_system_wrapper.ltx]
if {[file exists $ltx]} { set_property PROBES.FILE $ltx $dev }
refresh_hw_device -quiet $dev
puts "M2B_SCAN_DEVICE [get_property PART $dev]"

# ---- VIO helper procs (same protocol as fpga/acquire_continuous.tcl) --------
proc vio_by_cell {dev cell} {
    foreach v [get_hw_vios -quiet -of_objects $dev] {
        if {[string match "*$cell" [get_property CELL_NAME $v]]} { return $v }
    }
    return ""
}
proc probe {vio name} {
    set p [get_hw_probes -quiet -of_objects $vio -filter "NAME == $name"]
    if {[llength $p] != 1} {
        set p [get_hw_probes -quiet -of_objects $vio -filter "NAME =~ *$name"]
    }
    if {[llength $p] != 1} { error "probe $name not found" }
    return $p
}
proc wr {vio p v w} {
    set_property OUTPUT_VALUE [format %0${w}X $v] $p
    commit_hw_vio $vio
}
proc hx {v} {
    set v [string trim $v]
    if {$v eq ""} { return 0 }
    if {[string match 0x* $v]} { return [expr {$v}] }
    return [expr {"0x$v"}]
}
proc do_move {motors m_ctrl m_steps m_limit m_period m_ramp m_delta m_kick axis steps dir period} {
    if {$steps <= 0} { return 0 }
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
    return $base
}

set motors [vio_by_cell $dev motors_vio]
if {$motors eq ""} {
    # The debug hub is sometimes not registered on the first attach (the PL was
    # loaded by xsdb, not by this Vivado session).  Re-open the target and retry
    # once, as the error message suggests.
    puts "M2B_SCAN_VIO_RETRY"
    catch {close_hw_target}
    catch {disconnect_hw_server}
    after 1500
    connect_hw_server -allow_non_jtag
    set tgt [lindex [get_hw_targets -quiet] 0]
    current_hw_target $tgt
    open_hw_target
    set dev [lindex [get_hw_devices -quiet -filter {PART == xc7z020}] 0]
    current_hw_device $dev
    if {[file exists $ltx]} { set_property PROBES.FILE $ltx $dev }
    refresh_hw_device -quiet $dev
    set motors [vio_by_cell $dev motors_vio]
}
if {$motors eq ""} { error "M2B_SCAN_NO_MOTORS_VIO" }
set m_ctrl   [probe $motors m_ctrl]
set m_steps  [probe $motors m_steps]
set m_limit  [probe $motors m_limit]
set m_period [probe $motors m_period]
set m_ramp   [probe $motors m_ramp]
set m_delta  [probe $motors m_delta]
set m_kick   [probe $motors m_kick]
set m_busy   [probe $motors m_busy]
set m_stat   [probe $motors m_status]
set live_l   [probe $motors lift_position]
set live_r   [probe $motors ball_position]

proc wait_busy {motors m_busy timeout_ms} {
    # The RTL takes a few cycles to raise busy; closing the hw session before
    # that resets the VIO outputs and aborts the move (observed: a "one
    # revolution" move stopped after ~800 counts).
    set t0 [clock milliseconds]
    while {1} {
        refresh_hw_vio $motors
        if {[hx [get_property INPUT_VALUE $m_busy]] != 0} { return 1 }
        if {[expr {[clock milliseconds] - $t0}] > $timeout_ms} { return 0 }
        after 20
    }
}

proc kick {vio p} {
    if {[expr {[get_property OUTPUT_VALUE $p] != 0}]} { set v 0 } else { set v 1 }
    set_property OUTPUT_VALUE [format %01X $v] $p
    commit_hw_vio $vio
}

# The stepper has a ~2 s watchdog at 50 MHz: a move that is not "fed" stops
# after ~800 steps (400 steps/s).  The original acquisition script feeds it with
# kick every 20 frames; here we feed it every 100 ms while waiting.
proc sleep_for_move {motors m_kick steps period {margin_ms 1200}} {
    set ms [expr {int($steps * $period / 50000) + $margin_ms}]
    set t0 [clock milliseconds]
    puts "M2B_SCAN_WAIT ${ms}ms"
    while {1} {
        kick $motors $m_kick
        after 100
        if {[expr {[clock milliseconds] - $t0}] >= $ms} { break }
    }
}

proc wait_idle {motors m_busy timeout_ms} {
    set t0 [clock milliseconds]
    while {1} {
        refresh_hw_vio $motors
        if {[hx [get_property INPUT_VALUE $m_busy]] == 0} { return }
        if {[expr {[clock milliseconds] - $t0}] > $timeout_ms} { return }
        after 100
    }
}

set rev_counts [expr {$REVS * $CPR}]
set lift_net 0
puts "M2B_SCAN_START layers=$LAYERS revs=$REVS period=$PERIOD lift_delta=$LIFT_DELTA"

for {set layer 0} {$layer < $LAYERS} {incr layer} {
    if {$layer > 0} {
        if {$LIFT_DELTA > 0} {
            do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
                lift [expr {abs($LIFT_DELTA)}] 0 $PERIOD
            set lift_net [expr {$lift_net + $LIFT_DELTA}]
        } else {
            do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
                lift [expr {abs($LIFT_DELTA)}] 1 $PERIOD
            set lift_net [expr {$lift_net + $LIFT_DELTA}]
        }
        wait_busy $motors $m_busy 2000
        sleep_for_move $motors $m_kick [expr {abs($LIFT_DELTA)}] $PERIOD
        after $SETTLE
        puts "M2B_SCAN_LAYER $layer lift_moved net=$lift_net"
    }
    set r0 [hx [get_property INPUT_VALUE $live_r]]
    do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
        rot $rev_counts 1 $PERIOD
    wait_busy $motors $m_busy 2000
    sleep_for_move $motors $m_kick $rev_counts $PERIOD
    refresh_hw_vio $motors
    set r1 [hx [get_property INPUT_VALUE $live_r]]
    puts "M2B_SCAN_LAYER $layer done rot $r0 -> $r1"
}

if {$RESTORE && $lift_net != 0} {
    if {$lift_net > 0} {
        do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
            lift $lift_net 0 $PERIOD
    } else {
        do_move $motors $m_ctrl $m_steps $m_limit $m_period $m_ramp $m_delta $m_kick \
            lift [expr {abs($lift_net)}] 1 $PERIOD
    }
    wait_idle $motors $m_busy 20000
    puts "M2B_SCAN_LIFT_RESTORED"
}

puts "M2B_SCAN_DONE layers=$LAYERS"
close_hw_manager
exit 0
