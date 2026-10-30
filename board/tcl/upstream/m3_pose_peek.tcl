# M3 pre-flight: read the F1 pose window (0x4000_0030..0x3C) over JTAG and check
# that the PL is really producing attitude samples -- BEFORE blaming the firmware.
#
#   D:\Xilinx\2025.1\Vivado\bin\xsdb.bat -eval "source D:/daxue/FPGA/full_scan_workflow/fpga/ps/m3_pose_peek.tcl"
#
# Assumes the M3 bitstream is configured and ps7_init has run (m2b_run.tcl does
# both).  The CPU is stopped while reading and resumed afterwards: the pose path
# lives entirely in the PL, so `seq` must keep advancing even with the CPU halted.
# That is also the cheapest demonstration that the F1 channel is independent of
# the firmware.

set BASE 0x40000000

proc rd32 {addr} {
    set out [mrd -force $addr]
    if {[llength $out] == 0} { error "MRD_FAIL at [format 0x%08X $addr]" }
    # xsdb prints "4000003C:   00004D50" (address, colon, value).  The first
    # version of this file took token 0 and treated it as the value, which made
    # every read fail silently -- the 2026-10-27 board run showed no POSE output
    # at all.  Accept both that form and a bare 0x... just in case the tool change.
    set txt [join $out " "]
    if {[regexp {:\s*([0-9a-fA-F]+)} $txt -> hex]} {
        return [expr {"0x$hex" & 0xFFFFFFFF}]
    }
    if {[regexp {0x([0-9a-fA-F]+)} $txt -> hex]} {
        return [expr {"0x$hex" & 0xFFFFFFFF}]
    }
    error "MRD_UNPARSED: $out"
}

proc s16 {v} {
    set v [expr {$v & 0xFFFF}]
    if {$v >= 32768} { return [expr {$v - 65536}] }
    return $v
}

proc deg {c} { return [format "%.2f" [expr {$c * 90.0 / 16384.0}]] }

proc read_pose {} {
    global BASE
    # The PL refreshes the window at 1 kHz while this read takes microseconds, so
    # a torn snapshot is possible; retry a few times instead of giving up.
    for {set attempt 0} {$attempt < 5} {incr attempt} {
        set h1 [rd32 [expr {$BASE + 0x3C}]]
        set lo [rd32 [expr {$BASE + 0x30}]]
        set mid [rd32 [expr {$BASE + 0x34}]]
        set tk [rd32 [expr {$BASE + 0x38}]]
        set h2 [rd32 [expr {$BASE + 0x3C}]]
        if {$h1 != $h2} { continue }
        set magic [expr {($h1 >> 16) & 0xFFFF}]
        set seq   [expr {($h1 >> 8) & 0xFF}]
        set flags [expr {$h1 & 0xFF}]
        # 0x30 = {yaw[31:16], 8'h00, err[7:0]}; 0x34 = {roll[31:16], pitch[15:0]}
        set yaw   [s16 [expr {$lo >> 16}]]
        set err   [expr {$lo & 0xFF}]
        set roll  [s16 [expr {$mid >> 16}]]
        set pitch [s16 $mid]
        return [list $magic $seq $flags $roll $pitch $yaw $err $tk]
    }
    return [list -1 0 0 0 0 0 0 0]
}

connect
set core [lindex [targets -filter {name =~ "ARM Cortex-A9*#0*"}] 0]
if {$core eq ""} { error "M3_PEEK_NO_CORE: no Cortex-A9 #0 (is the board configured?)" }
targets -set $core
catch {stop}

set p [read_pose]
set magic [lindex $p 0]
set seq   [lindex $p 1]
set flags [lindex $p 2]
set err   [lindex $p 6]

if {$magic < 0} {
    puts "M3_PEEK_FAIL: header changed during the read (retry)"
    catch {con}
    exit 1
}
if {$magic != 0x4D50} {
    puts [format "M3_PEEK_FAIL: magic=0x%04X (expected 0x4D50) -- this is not an M3 image, or acq_regs is not at 0x4000_0000" $magic]
    catch {con}
    exit 1
}

puts [format "POSE flags=0x%02X (valid=%d init=%d i2c_err=%d stuck=%d) seq=%d err_cnt=%d" \
      $flags [expr {$flags & 1}] [expr {($flags >> 1) & 1}] [expr {($flags >> 2) & 1}] \
      [expr {($flags >> 3) & 1}] $seq $err]
puts [format "POSE roll=%s pitch=%s yaw=%s deg  (tick=%d)" \
      [deg [lindex $p 3]] [deg [lindex $p 4]] [deg [lindex $p 5]] [lindex $p 7]]

# sample rate: 10 windows of 100 ms; seq is 8-bit, so a 1 s window would alias
if {($flags & 1) == 0} {
    puts "POSE_WARN: valid=0 -- MPU6050 not answering (check 3.3V/GND/SCL/SDA, AD0=GND)."
    puts "POSE_SAMPLES=0"
    catch {con}
    exit 2
}

set prev $seq
set total 0
for {set i 0} {$i < 10} {incr i} {
    after 100
    set s [expr {[rd32 [expr {$BASE + 0x3C}]] >> 8 & 0xFF}]
    set d [expr {($s - $prev) & 0xFF}]
    incr total $d
    set prev $s
}
puts "POSE_SAMPLES=$total in 10x100ms (expect ~1000 at the 1 ms period)"
if {$total < 700 || $total > 1300} {
    puts "POSE_WARN: sample rate outside 700..1300 Hz -- check SCL_HZ/400 kHz and err_cnt"
}

catch {con}
if {($flags & 1) == 0} { exit 2 }
puts "M3_POSE_PEEK_PASS"
exit 0
