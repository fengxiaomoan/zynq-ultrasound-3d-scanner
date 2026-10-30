# Pin-level diff between two report_io files, for the M3 gate.
#
# Kept in its own file so it can be sourced both by build_ps_m3.tcl and by a
# standalone test (Vivado's Tcl is the only interpreter guaranteed here).
#
# 2026-10-27: the first version lived inside build_ps_m3.tcl and matched
# `port dir pin` at the beginning of a line.  Vivado 2025.1 writes
# `| T10 | scl | ... |`, so both reports parsed to an empty table and the diff
# silently "passed".  This version parses the pipe-table and ERRORS OUT when a
# report yields no rows, because a gate that cannot see is worse than no gate.

proc io_read_pins {path} {
    set pins [dict create]
    if {![file exists $path]} { return $pins }
    set f [open $path r]
    while {[gets $f line] >= 0} {
        if {[regexp {^\|\s*([A-Z]+\d+)\s*\|\s*([^|]+?)\s*\|} $line -> pin sig]} {
            set sig [string trim $sig]
            if {$sig ne ""} { dict set pins $sig $pin }
        }
    }
    close $f
    return $pins
}

# Returns 0 when only `allowed` ports were added and nothing was lost or moved.
# Prints every difference; the caller decides whether to error out.
proc io_pin_diff {base_rpt new_rpt {allowed {scl sda}}} {
    set old [io_read_pins $base_rpt]
    set new [io_read_pins $new_rpt]
    if {[dict size $old] == 0 || [dict size $new] == 0} {
        puts "PIN_DIFF_UNPARSED base=[dict size $old] new=[dict size $new]"
        return 2
    }

    set bad 0
    set added {}
    foreach sig [lsort [dict keys $new]] {
        if {![dict exists $old $sig]} {
            set pin [dict get $new $sig]
            if {[lsearch -exact $allowed $sig] >= 0} {
                puts "  ADDED pin: $sig $pin"
            } else {
                puts "  ADDED pin (UNEXPECTED): $sig $pin"
                incr bad
            }
            lappend added $sig
        }
    }
    foreach sig [lsort [dict keys $old]] {
        if {![dict exists $new $sig]} {
            puts "  LOST  pin: $sig [dict get $old $sig]"
            incr bad
        } elseif {[dict get $old $sig] ne [dict get $new $sig]} {
            puts "  MOVED pin: $sig [dict get $old $sig] -> [dict get $new $sig]"
            incr bad
        }
    }
    puts "PIN_DIFF base=[dict size $old] new=[dict size $new] added=[llength $added] allowed=[join $allowed ,]"
    return $bad
}
