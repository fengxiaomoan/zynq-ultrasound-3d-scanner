# Reload ONLY the PS firmware, without re-programming the PL or re-running ps7_init.
#
#   xsdb -eval "source D:/daxue/FPGA/full_scan_workflow/fpga/ps/m3_fw_reload.tcl"
#
# Why this exists: a firmware-only change (e.g. a decode fix) does not need the
# whole load ritual, and every extra `fpga -file` / `ps7_init` on this board is a
# chance to wedge the debug APB (2026-10-27: two loads in a row timed out).  DDR is
# already initialised by the previous ps7_init and the PL keeps its configuration,
# so writing the binary and resetting the PC is enough.
#
# Caveat: this is only valid in the SAME power cycle as the original load.  After a
# power cycle use m2b_run.tcl (or m3_timeline.tcl) instead.
set BIN "D:/daxue/FPGA/full_scan_workflow/fpga/ps/build_m2b/m2b_ps.bin"
if {![file exists $BIN]} { error "FW_RELOAD_NO_BIN: $BIN" }

connect
set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0]
if {$core eq ""} {
    error "FW_RELOAD_NO_CORE: no Cortex-A9 #0 -- the debug APB is wedged; power-cycle and use m2b_run.tcl"
}
targets -set $core
catch {stop}
after 300

set words [expr {int(([file size $BIN] + 3) / 4)}]
if {[catch {mwr -bin -file $BIN 0x100000 $words} e]} {
    error "FW_RELOAD_WRITE_FAIL: $e (power-cycle and use m2b_run.tcl)"
}
puts "FW_RELOAD_WRITTEN $words words"
rwr pc 0x100000
after 100
con
puts "FW_RELOAD_STARTED"
exit 0
