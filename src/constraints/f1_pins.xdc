# F1 pins for the merged (M3) image: MPU6050 on the camera-header SCCB bus.
#
# Kept in its own file (added only by build_ps_m3.tcl) because merged_top.xdc is
# shared with the fpga_dsp_v2 / fpga_dsp_c1 builds, which have no scl/sda ports;
# putting these lines there would break those builds ("no port scl").
#
# T10/T11 are the vendor's cam_scl/cam_sda (LVCMOS33, weak pull-ups in the pad).
# The GY-521 supplies its own 4.7k pull-ups; keep VCC at 3.3V only.
set_property PACKAGE_PIN T10 [get_ports scl]
set_property PACKAGE_PIN T11 [get_ports sda]
set_property IOSTANDARD LVCMOS33 [get_ports {scl sda}]
set_property PULLTYPE PULLUP [get_ports {scl sda}]

# I2C is asynchronous to sys_clk: the byte engine samples it mid-bit, and the
# slave may stretch the clock.  Timing analysis across these ports is meaningless.
set_false_path -from [get_ports {scl sda}]
set_false_path -to   [get_ports {scl sda}]
