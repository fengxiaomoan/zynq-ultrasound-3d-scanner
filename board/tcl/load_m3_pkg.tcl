# Load the M3 image (PL + PS firmware) over JTAG and start it (xsdb, no SD card).
#
#   D:\Xilinx\2025.1\Vivado\bin\xsdb.bat -eval "source <package>/board/tcl/load_m3_pkg.tcl"
#
# PACKAGE-LOCAL COPY of m2b_run.tcl.  Flow unchanged; paths point at the files
# shipped in this package.  The `mwr -bin` + `rwr pc` sequence is used instead of
# `dow` because `dow` intermittently fails on this board with
# "AP transaction timeout" and wedges the PS debug APB.
#
# Usage rules:
#   * power-cycle before a fresh load; a reload in the same power cycle can be
#     shadowed by old L2 lines;
#   * if `targets` shows a wedged DAP and no APU, power-cycle rather than
#     retrying blindly;
#   * after the load, verify ping + /api/status BEFORE running a scan.

set here   [file normalize [file dirname [info script]]]
set root   [file normalize [file join $here .. ..]]
set BIT    [file join $root board bitstream ps_m3_system_wrapper.bit]
set BIN    [file join $root board firmware m2b_ps.bin]
set PSINIT [file join $root board xsa ps7_init.tcl]
set CORE   "ARM Cortex-A9 MPCore #0"
set ENTRY  0x100000

connect
set dev [lindex [targets -filter {name =~ "xc7z020*"}] 0]
if {$dev eq ""} { error "M3_RUN_NO_BOARD: no xc7z020 on the JTAG chain" }

# Check inputs BEFORE touching the board: reprogramming the PL or running
# ps7_init under a running firmware silently breaks its PS peripherals.
if {![file exists $BIN]}    { error "M3_RUN_NO_BIN: $BIN (run src/ps/build_m2b.py)" }
if {![file exists $PSINIT]} { error "M3_RUN_NO_PSINIT: $PSINIT" }
if {![file exists $BIT]}    { error "M3_RUN_NO_BIT: $BIT" }

# Right after power-up the JTAG chain may not have enumerated yet.
for {set i 0} {$i < 20} {incr i} {
    if {[llength [targets -filter {name =~ "APU*"}]] > 0} { break }
    after 500
}

if {[llength [targets -filter {name =~ "APU*"}]] == 0} {
    set dap [lindex [targets -filter {name =~ "DAP*"}] 0]
    if {$dap ne ""} {
        puts "M3_DAP_RECOVER: no APU, resetting the PS through the DAP"
        catch {targets -set $dap}
        catch {rst -system}
        after 2500
    }
}
if {[llength [targets -filter {name =~ "APU*"}]] == 0} {
    error "M3_RUN_PS_WEDGED: no APU target -- power-cycle the board and retry"
}

# Program the PL first, with no preceding `rst -system`.
targets -set $dev
fpga -file $BIT
after 2000
puts "M3_PL_PROGRAMMED"

# Stop the core BEFORE ps7_init: re-initialising DDR while the old firmware is
# still executing out of DDR leaves 0x100000 unwritable.
set core [lindex [targets -filter [list name =~ $CORE]] 0]
if {$core eq ""} { set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0] }
if {$core eq ""} { error "M3_RUN_NO_CORE: Cortex-A9 #0 not found" }
targets -set $core
catch {rst -processor}
after 300
catch {stop}
puts "M3_CORE_STOPPED"

targets -set -filter {name =~ "APU*"}
source $PSINIT
ps7_init
catch {ps7_post_config}
puts "M3_PS7_INIT_OK"

targets -set $core
set words [expr {int(([file size $BIN] + 3) / 4)}]

# Pre-flight: fail with a clear message if DDR is not writable.
if {[catch {mwr -force 0x100000 0x5A5A5A5A} e]} {
    error "M3_DDR_NOT_WRITABLE: $e -- power-cycle the board"
}
if {[catch {set probe [mrd -force 0x100000]} e2]} {
    error "M3_DDR_NOT_READABLE: $e2 -- power-cycle the board"
}
if {![string match "*5A5A5A5A*" $probe]} {
    error "M3_DDR_BAD_READBACK: $probe -- power-cycle the board"
}
puts "M3_DDR_OK"

mwr -bin -file $BIN $ENTRY $words
puts "M3_BIN_WRITTEN ($words words)"

rwr pc $ENTRY
con
puts "M3_RUN_STARTED"
puts "  http://192.168.1.10/   (PC needs an address on 192.168.1.0/24, no gateway)"
puts "  UART0: === M2B_PS start === / M2B_PS_ALIVE"
