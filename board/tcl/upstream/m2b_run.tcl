# M2b: load the PS firmware over JTAG and start it (xsdb, no SD card needed).
#
#   D:\Xilinx\2025.1\Vivado\bin\xsdb.bat -eval "source D:/daxue/FPGA/full_scan_workflow/fpga/ps/m2b_run.tcl"
#
# The path must be absolute (or the shell must be cd'd to fpga/ps): xsdb resolves
# a relative `source` against the shell's current directory, not against this
# file.
#
# Why the binary + `rwr pc` instead of `dow` (learned 2026-10-27): `dow` on this
# board intermittently fails with "Memory write error at 0x100000. AP
# transaction timeout" and leaves the PS debug APB wedged ("DAP APB AP
# transaction error"), needing a power cycle.  Writing the raw binary from the
# APU context and setting the PC directly has been reliable, and it also avoids
# the "MMU section translation fault" that `dow` hits when an old image left the
# core's MMU on.
#
# If `targets` shows "DAP (APB AP transaction error ...)" and no APU: issue a
# system reset through the DAP target itself first (see below); if that does not
# bring the APU back, power-cycle the board.

set BUILD  "D:/daxue/FPGA/fpga_ps_m2"
set BIT    "$BUILD/ps_m2.runs/impl_1/system_wrapper.bit"
set BIN    "D:/daxue/FPGA/full_scan_workflow/fpga/ps/build_m2b/m2b_ps.bin"
set PSINIT "$BUILD/ps_m2.gen/sources_1/bd/system/ip/system_processing_system7_0_0/ps7_init.tcl"
# M3 = the same image plus F1 (MPU6050).  One image, one load: set
#   $env:M2B_STAGE = "m3"
# before invoking xsdb and the paths below point at fpga_ps_m3 / ps_m3; the
# default stays M2b so every existing command keeps working unchanged.
set STAGE  "m2"
if {[info exists ::env(M2B_STAGE)]} { set STAGE $::env(M2B_STAGE) }
if {$STAGE eq "m3"} {
    set BUILD  "D:/daxue/FPGA/fpga_ps_m3"
    set BIT    "$BUILD/ps_m3.runs/impl_1/system_wrapper.bit"
    set PSINIT "$BUILD/ps_m3.gen/sources_1/bd/system/ip/system_processing_system7_0_0/ps7_init.tcl"
}
set CORE   "ARM Cortex-A9 MPCore #0"
set ENTRY  0x100000

connect
set dev [lindex [targets -filter {name =~ "xc7z020*"}] 0]
if {$dev eq ""} { error "M2B_RUN_NO_BOARD: no xc7z020 on the JTAG chain" }

# Check the inputs BEFORE touching the board.  Reprogramming the PL or running
# ps7_init under a *running* firmware silently breaks its PS peripherals (the
# CPU keeps executing from DDR, frames keep flowing, but UART/GEM die) -- that
# is what looked like "the network dies after a while" on 2026-10-27.  Failing
# here keeps a live image untouched.
if {![file exists $BIN]} { error "M2B_RUN_NO_BIN: $BIN (run fpga/ps/build_m2b.py)" }
if {![file exists $PSINIT]} { error "M2B_RUN_NO_PSINIT: $PSINIT" }
if {![file exists $BIT]} { error "M2B_RUN_NO_BIT: $BIT" }

# Right after a power-up the JTAG chain sometimes has not enumerated yet.  Give
# it up to 10 s instead of immediately issuing a DAP `rst -system` -- that reset
# makes the following `fpga -file` fail with "DONE PIN is not HIGH" (2026-10-27).
for {set i 0} {$i < 20} {incr i} {
    if {[llength [targets -filter {name =~ "APU*"}]] > 0} { break }
    after 500
}

if {[llength [targets -filter {name =~ "APU*"}]] == 0} {
    set dap [lindex [targets -filter {name =~ "DAP*"}] 0]
    if {$dap ne ""} {
        puts "M2B_DAP_RECOVER: no APU, resetting the PS through the DAP"
        catch {targets -set $dap}
        catch {rst -system}
        after 2500
    }
}
if {[llength [targets -filter {name =~ "APU*"}]] == 0} {
    error "M2B_RUN_PS_WEDGED: no APU target -- power-cycle the board and retry"
}

# Program the PL first, with no preceding `rst -system`: on this board a system
# reset immediately before `fpga -file` makes configuration fail with
# "DONE PIN is not HIGH" (2026-10-27).  A fresh power-up therefore uses this
# order; for a *reload* without power cycling prefer power-cycling, because the
# old image's L2 lines can shadow the newly written DDR image.
targets -set $dev
fpga -file $BIT
after 2000
puts "M2B_PL_PROGRAMMED"

# Stop the core BEFORE ps7_init: re-initialising the DDR controller while the
# old firmware is still executing out of DDR is what leaves 0x100000 unwritable
# ("AP transaction timeout", seen repeatedly on reloads; a fresh power-up is
# always fine).  Hold the core in reset, then re-init the PS, then write.
set core [lindex [targets -filter [list name =~ $CORE]] 0]
if {$core eq ""} { set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0] }
if {$core eq ""} { error "M2B_RUN_NO_CORE: Cortex-A9 #0 not found" }
targets -set $core
catch {rst -processor}
after 300
catch {stop}
puts "M2B_CORE_STOPPED"

targets -set -filter {name =~ "APU*"}
source $PSINIT
ps7_init
catch {ps7_post_config}
puts "M2B_PS7_INIT_OK"

targets -set $core
set words [expr {int(([file size $BIN] + 3) / 4)}]

# Pre-flight: if DDR is not writable (PS debug port wedged, ps7_init not applied),
# fail here with a clear message.  Without this, xsdb's mwr fails on the 200 KB
# buffer and dumps the whole binary to the console, which looks like garbage.
if {[catch {mwr -force 0x100000 0x5A5A5A5A} e]} {
    error "M2B_DDR_NOT_WRITABLE: $e -- power-cycle the board"
}
if {[catch {set probe [mrd -force 0x100000]} e2]} {
    error "M2B_DDR_NOT_READABLE: $e2 -- power-cycle the board"
}
if {![string match "*5A5A5A5A*" $probe]} {
    error "M2B_DDR_BAD_READBACK: $probe -- power-cycle the board"
}
puts "M2B_DDR_OK"

mwr -bin -file $BIN $ENTRY $words
puts "M2B_BIN_WRITTEN ($words words)"

rwr pc $ENTRY
con
puts "M2B_RUN_STARTED"
puts "  http://192.168.1.10/   (PC needs an address on 192.168.1.0/24, no gateway)"
puts "  UART0: === M2B_PS start === / M2B_PS_ALIVE"
