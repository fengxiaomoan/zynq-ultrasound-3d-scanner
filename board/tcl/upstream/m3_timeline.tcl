# M3 timeline: load the image, run the firmware, and watch it for 6 s without ever
# re-entering the debug port with a second session.
#
#   xsdb -eval "source <repo-root>/full_scan_workflow/fpga/ps/m3_timeline.tcl"
#
# Why (2026-10-27 19:0x): the one-shot load reported success but the board froze
# about a second later, and a *second* xsdb session then failed to read the AXI
# range with "AP transaction error".  This script keeps one session for the whole
# sequence and only touches PS-side registers (APB GPIO) while the CPU is running,
# so the debug port is not disturbed; the AXI range is read once at the end with
# the core halted.
#
# Reads:
#   0x41200000  firmware heartbeat: frames kept in the ring
#   0x41200008  firmware heartbeat: last ACQ STATUS
#   0x40000000  ACQ STATUS (after stop)
#   0x4000003C  F1 pose header (after stop) -- 0x4D50 in the high half once a sample
#               has been latched; 0 means the PL never produced one
set BUILD  "<repo-root>/fpga_ps_m3"
set BIT    "$BUILD/ps_m3.runs/impl_1/system_wrapper.bit"
set BIN    "<repo-root>/full_scan_workflow/fpga/ps/build_m2b/m2b_ps.bin"
set PSINIT "$BUILD/ps_m3.gen/sources_1/bd/system/ip/system_processing_system7_0_0/ps7_init.tcl"

foreach f [list $BIT $BIN $PSINIT] {
    if {![file exists $f]} { error "M3_TL_NO_FILE: $f" }
}

proc rd32 {addr} {
    set out [mrd -force $addr]
    set txt [join $out " "]
    if {[regexp {:\s*([0-9a-fA-F]+)} $txt -> hex]} { return [expr {"0x$hex" & 0xFFFFFFFF}] }
    if {[regexp {0x([0-9a-fA-F]+)} $txt -> hex]} { return [expr {"0x$hex" & 0xFFFFFFFF}] }
    error "MRD_UNPARSED: $out"
}

connect
set dev  [lindex [targets -filter {name =~ "xc7z020*"}] 0]
set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0]
if {$dev eq ""}  { error "M3_TL_NO_BOARD" }
if {$core eq ""} { error "M3_TL_NO_CORE" }

targets -set $dev
fpga -file $BIT
after 1000
puts "TL_PL_PROGRAMMED"

targets -set $core
catch {rst -processor}
after 300
catch {stop}
targets -set -filter {name =~ "APU*"}
source $PSINIT
ps7_init
catch {ps7_post_config}
after 300
puts "TL_PS7_INIT_OK"

# Before the firmware runs: the PL is autonomous, so if F1 were sampling we would
# already see the pose header.
#
# 2026-10-27: an AXI read through a halted-core DAP has twice wedged this board's
# debug APB ("AP transaction timeout", then no APU target until a power cycle).
# The firmware heartbeat (PS-side APB) is enough to prove the image runs, so the
# pre-run AXI peek is opt-in: set ::probe_axi 1 if you want it.
set pre_stat -1
set pre -1
if {![info exists ::probe_axi]} { set ::probe_axi 0 }
if {$::probe_axi == 0} {
    puts "TL_PRE_SKIPPED (AXI peek disabled; set ::probe_axi 1 to enable)"
} else {
    if {[catch {set pre_stat [rd32 0x40000000]} e]} {
        puts "TL_PRE_STATUS_FAIL: $e"
    } else {
        puts [format "TL_PRE_ACQ_STATUS=0x%08X" $pre_stat]
    }
    if {[catch {set pre [rd32 0x4000003C]} e]} {
        puts "TL_PRE_POSE_FAIL: $e"
    } else {
        puts [format "TL_PRE_RUN_POSE_HDR=0x%08X (0x4D50xxxx means a sample already latched)" $pre]
    }
}

targets -set $core
set words [expr {int(([file size $BIN] + 3) / 4)}]
if {[catch {mwr -bin -file $BIN 0x100000 $words} e]} { error "TL_BIN_WRITE_FAIL: $e" }
rwr pc 0x100000
con
puts "TL_RUN_STARTED"

set prev_frames -1
for {set i 0} {$i < 12} {incr i} {
    after 500
    set frames [rd32 0x41200000]
    set st     [rd32 0x41200008]
    puts [format "TL t=%4dms frames=%d status=0x%08X" [expr {($i + 1) * 500}] $frames $st]
    if {$frames == $prev_frames} {
        # the heartbeat only refreshes once a second, so a single repeat is normal
    }
    set prev_frames $frames
}

catch {stop}
after 200
set a -1
set pp -1
if {[catch {set a [rd32 0x40000000]} e]} { puts "TL_FINAL_STATUS_FAIL: $e" } \
    else { puts [format "TL_FINAL_ACQ_STATUS=0x%08X" $a] }
if {[catch {set pp [rd32 0x4000003C]} e]} { puts "TL_FINAL_POSE_FAIL: $e" } \
    else { puts [format "TL_FINAL_POSE_HDR=0x%08X" $pp] }
set p $pp
if {(($p >> 16) == 0x4D50) && (($p & 0xFFFF) != 0)} {
    puts "TL_VERDICT F1_LATCHED"
} elseif {($p >> 16) == 0x4D50} {
    puts "TL_VERDICT F1_NO_SAMPLE_YET (magic present, seq/flags still 0: MPU not answering)"
} else {
    puts [format "TL_VERDICT NOT_AN_M3_POSE_WINDOW (0x%08X)" $p]
}
exit 0
