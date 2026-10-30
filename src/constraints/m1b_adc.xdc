# Extra constraints for the M1b (block-design) build ONLY.
#
# Why this file exists
# --------------------
# merged_top.xdc is correct and must stay untouched (it sign-offs fpga_dsp_c1).
# But wrapping merged_top in a block design changed how Vivado interprets the
# ADC input paths:
#
#   fpga_dsp_c1 : adc_clk2_out -> sys_clk  requirement 200.000 ns, slack +88.594
#   fpga_ps_m1b : adc_clk2_out -> sys_clk  requirement  20.000 ns, slack -92.418
#
# Same RTL, same XDC, same input delay (100 ns).  Inside the BD the divide_by-10
# relationship from create_generated_clock -source sys_clk was no longer applied,
# so the tool demanded that a word launched by the 5 MHz ADC edge be captured by
# the very next 50 MHz edge.  That is not what the hardware does: the ADC presents
# one 10-bit word per adc_clock edge, i.e. every 200 ns = 10 sys_clk cycles, and
# the acquisition core latches once per ADC cycle.
#
# So the relationship is stated explicitly instead of being assumed.  This does
# not relax anything that is real: the launch data still has a full 200 ns to
# arrive (the same window c1 was signed off with).
#
# Hold: 9 multicycles keeps the hold check at the original launch edge, which is
# the standard pairing for a 10x setup multicycle.
set_multicycle_path -setup 10 -from [get_clocks adc_clk_out]
set_multicycle_path -hold   9 -from [get_clocks adc_clk_out]
set_multicycle_path -setup 10 -from [get_clocks adc_clk2_out]
set_multicycle_path -hold   9 -from [get_clocks adc_clk2_out]
