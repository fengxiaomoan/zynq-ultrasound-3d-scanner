# F1 bring-up: MPU6050 on the camera-header SCCB bus.
# T10/T11 are the vendor's cam_scl/cam_sda (LVCMOS33).  The pins carry weak
# pull-ups so the bus is high when both ends release it; the module supplies its
# own 4.7k pull-ups as well.
set_property PACKAGE_PIN U18 [get_ports sys_clk]
set_property IOSTANDARD LVCMOS33 [get_ports sys_clk]
create_clock -name sys_clk -period 20.000 [get_ports sys_clk]

set_property PACKAGE_PIN N16 [get_ports sys_rst_n]
set_property IOSTANDARD LVCMOS33 [get_ports sys_rst_n]

set_property PACKAGE_PIN T10 [get_ports scl]
set_property PACKAGE_PIN T11 [get_ports sda]
set_property IOSTANDARD LVCMOS33 [get_ports {scl sda}]
set_property PULLTYPE PULLUP [get_ports {scl sda}]

# I2C is asynchronous to sys_clk and sampled mid-bit by the byte engine.
set_false_path -from [get_ports {scl sda}]
set_false_path -to [get_ports {scl sda}]
set_false_path -from [get_ports sys_rst_n] -to [get_cells -hier -filter {NAME =~ *rst_sync_reg*}]
