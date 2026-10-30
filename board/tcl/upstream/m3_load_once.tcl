# Single-shot, patient loader.  One power cycle = exactly one ps7_init.
#
#   xsdb -eval "source <repo-root>/full_scan_workflow/fpga/ps/m3_load_once.tcl"
#
# What the 2026-10-27 failures taught:
#   * retrying ps7_init inside one power cycle does not help -- each retry leaves
#     the debug APB worse ("AP transaction error", then no APU target at all);
#   * the one attempt that worked was a cycle where the PS had not been
#     re-initialised yet, i.e. a pristine PS.
# So: wait for the board to settle, program the PL once, reset+stop the core once,
# run ps7_init once, write the image directly (no single-word DDR probe -- that
# probe is what kept timing out), and start.
#
# Exit codes: 0 started, 2 failed (power-cycle and run it again), 3 missing file.
set SETTLE_MS 8000          ;# let the BootROM finish before touching the PS
set BUILD  "<repo-root>/fpga_ps_m3"
set BIT    "$BUILD/ps_m3.runs/impl_1/system_wrapper.bit"
set BIN    "<repo-root>/full_scan_workflow/fpga/ps/build_m2b/m2b_ps.bin"
set PSINIT "$BUILD/ps_m3.gen/sources_1/bd/system/ip/system_processing_system7_0_0/ps7_init.tcl"

foreach f [list $BIT $BIN $PSINIT] { if {![file exists $f]} { puts "ONCE_NO_FILE: $f"; exit 3 } }

puts "ONCE_SETTLE ${SETTLE_MS}ms"
after $SETTLE_MS

connect
set dev  [lindex [targets -filter {name =~ "xc7z020*"}] 0]
set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0]
if {$dev eq ""}  { puts "ONCE_NO_BOARD"; exit 2 }
if {$core eq ""} { puts "ONCE_NO_CORE (APB already wedged -- power-cycle)"; exit 2 }

targets -set $dev
fpga -file $BIT
after 1500
puts "ONCE_PL_PROGRAMMED"

targets -set $core
catch {rst -processor}
after 1000
catch {stop}
after 1000
if {[catch {rrd pc} pcv]} { puts "ONCE_CORE_STOP_FAIL: $pcv"; exit 2 }
puts "ONCE_CORE_STOPPED pc=$pcv"

targets -set -filter {name =~ "APU*"}
source $PSINIT
if {[catch {ps7_init} e]} { puts "ONCE_PS7_FAIL: $e"; exit 2 }
catch {ps7_post_config}
after 1000
puts "ONCE_PS7_INIT_OK"

targets -set $core
catch {stop}
after 500
set words [expr {int(([file size $BIN] + 3) / 4)}]
if {[catch {mwr -bin -file $BIN 0x100000 $words} e]} { puts "ONCE_BIN_FAIL: $e"; exit 2 }
puts "ONCE_BIN_WRITTEN ($words words)"
if {[catch {rwr pc 0x100000} e]} { puts "ONCE_PC_FAIL: $e"; exit 2 }
after 200
con
puts "ONCE_STARTED"
exit 0
