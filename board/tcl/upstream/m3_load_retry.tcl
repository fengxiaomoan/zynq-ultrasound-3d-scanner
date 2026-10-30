# M3 load with an internal retry, for the board's intermittent "AP transaction
# timeout" during ps7_init.
#
#   xsdb -eval "source D:/daxue/FPGA/full_scan_workflow/fpga/ps/m3_load_retry.tcl"
#
# Sequence: program the PL, stop the core, ps7_init, verify DDR is writable, then
# write the firmware and start it.  If the DDR probe fails, ps7_init is re-run once
# and the probe retried -- that single retry saves a whole power cycle when the
# first ps7_init did not fully take (seen three times on 2026-10-27).
#
# Exit codes: 0 ok, 2 DDR still not writable (power-cycle; if it repeats, unplug
# the MPU module to isolate a supply/pull-up problem), 3 missing file.
set BUILD  "D:/daxue/FPGA/fpga_ps_m3"
set BIT    "$BUILD/ps_m3.runs/impl_1/system_wrapper.bit"
set BIN    "D:/daxue/FPGA/full_scan_workflow/fpga/ps/build_m2b/m2b_ps.bin"
set PSINIT "$BUILD/ps_m3.gen/sources_1/bd/system/ip/system_processing_system7_0_0/ps7_init.tcl"

foreach f [list $BIT $BIN $PSINIT] { if {![file exists $f]} { puts "M3_LOAD_NO_FILE: $f"; exit 3 } }

connect
set dev  [lindex [targets -filter {name =~ "xc7z020*"}] 0]
set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0]
if {$dev eq ""}  { puts "M3_LOAD_NO_BOARD"; exit 2 }
if {$core eq ""} { puts "M3_LOAD_NO_CORE (power-cycle; the debug APB is wedged)"; exit 2 }

targets -set $dev
fpga -file $BIT
after 1000
puts "M3_LOAD_PL_PROGRAMMED"

proc probe_ddr {} {
    if {[catch {mwr -force 0x100000 0x5A5A5A5A} e]} { return 0 }
    if {[catch {set p [mrd -force 0x100000]} e]} { return 0 }
    if {![string match "*5A5A5A5A*" $p]} { return 0 }
    return 1
}

# ps7_init.tcl must be sourced at TOP LEVEL: it defines globals (PCW_SILICON_VER_*)
# that the ps7_init proc reads.  Sourcing it inside a proc puts them in that proc's
# local scope and ps7_init dies with "can't read PCW_SILICON_VER_1_0".
source $PSINIT

proc do_ps7_init {} {
    global core
    targets -set $core
    catch {rst -processor}
    after 300
    catch {stop}
    after 200
    targets -set -filter {name =~ "APU*"}
    ps7_init
    catch {ps7_post_config}
    after 300
}

do_ps7_init
targets -set $core
catch {stop}
after 500
# up to three ps7_init attempts: on this board the first one after a power-up
# frequently does not take ("AP transaction timeout" on the first DDR write), while
# a later attempt in the same session does (observed 2026-10-27).
set ok 0
for {set attempt 0} {$attempt < 3} {incr attempt} {
    if {[probe_ddr]} { set ok 1; break }
    puts "M3_LOAD_DDR_RETRY attempt [expr {$attempt + 1}] (ps7_init again)"
    do_ps7_init
    targets -set $core
    catch {stop}
    after 800
}
if {!$ok} {
    puts "M3_LOAD_DDR_FAIL (power-cycle; if it repeats, unplug the MPU module)"
    exit 2
}
puts "M3_LOAD_DDR_OK"

targets -set $core
set words [expr {int(([file size $BIN] + 3) / 4)}]
if {[catch {mwr -bin -file $BIN 0x100000 $words} e]} { puts "M3_LOAD_BIN_FAIL: $e"; exit 2 }
rwr pc 0x100000
con
puts "M3_LOAD_STARTED ($words words)"
exit 0
