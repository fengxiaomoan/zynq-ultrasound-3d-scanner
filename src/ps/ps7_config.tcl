# PS7 configuration for 启明星 V2 (xc7z020clg400-2), taken from the vendor's own
# lwIP example so nothing here is guessed:
#
#   source archive : 4_Source_Code/2_Embedded_Vitis/ZYNQ_Vitis_7020.rar
#   member         : ZYNQ_Vitis_7020/37_lwip_echo_server/lwip_echo_server.gen/
#                    sources_1/bd/system/hw_handoff/system_bd.tcl
#   extracted to   : live_run/_vendor_ps/... (read-only reference copy)
#
# Everything below is the vendor's value verbatim, except the four lines marked
# "OURS", which turn on what a PL-attached design needs (the echo-server example
# is PS-only, so it has FCLK0 disabled and M_AXI_GP0 disabled).
#
# Cross-check against the board's own pin table
# (启明星ZYNQ开发板 IO引脚分配总表.xlsx, sheet "PS IO引脚列表"): ENET on MIO16..27
# + MDC/MDIO on MIO52/53, SD on MIO40..45 + CD on MIO10, QSPI on MIO1..6,
# UART on MIO14/15.  All three agree, so the RGMII/PHY wiring is not a guess.

proc apply_ps7_config { cell } {
  set cfg [list \
    CONFIG.PCW_ACT_APU_PERIPHERAL_FREQMHZ {666.666687} \
    CONFIG.PCW_ACT_DCI_PERIPHERAL_FREQMHZ {10.158730} \
    CONFIG.PCW_ACT_ENET0_PERIPHERAL_FREQMHZ {125.000000} \
    CONFIG.PCW_ACT_QSPI_PERIPHERAL_FREQMHZ {200.000000} \
    CONFIG.PCW_ACT_SDIO_PERIPHERAL_FREQMHZ {100.000000} \
    CONFIG.PCW_ACT_UART_PERIPHERAL_FREQMHZ {100.000000} \
    CONFIG.PCW_ARMPLL_CTRL_FBDIV {40} \
    CONFIG.PCW_CPU_CPU_PLL_FREQMHZ {1333.333} \
    CONFIG.PCW_DDRPLL_CTRL_FBDIV {32} \
    CONFIG.PCW_DDR_DDR_PLL_FREQMHZ {1066.667} \
    CONFIG.PCW_DDR_PERIPHERAL_DIVISOR0 {2} \
    CONFIG.PCW_DDR_RAM_HIGHADDR {0x3FFFFFFF} \
    CONFIG.PCW_IOPLL_CTRL_FBDIV {30} \
    CONFIG.PCW_IO_IO_PLL_FREQMHZ {1000.000} \
    CONFIG.PCW_UIPARAM_ACT_DDR_FREQ_MHZ {533.333374} \
    CONFIG.PCW_UIPARAM_DDR_BANK_ADDR_COUNT {3} \
    CONFIG.PCW_UIPARAM_DDR_BL {8} \
    CONFIG.PCW_UIPARAM_DDR_CL {7} \
    CONFIG.PCW_UIPARAM_DDR_COL_ADDR_COUNT {10} \
    CONFIG.PCW_UIPARAM_DDR_CWL {6} \
    CONFIG.PCW_UIPARAM_DDR_DEVICE_CAPACITY {4096 MBits} \
    CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH {16 Bits} \
    CONFIG.PCW_UIPARAM_DDR_MEMORY_TYPE {DDR 3 (Low Voltage)} \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} \
    CONFIG.PCW_UIPARAM_DDR_ROW_ADDR_COUNT {15} \
    CONFIG.PCW_UIPARAM_DDR_SPEED_BIN {DDR3_1066F} \
    CONFIG.PCW_UIPARAM_DDR_T_FAW {40.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RAS_MIN {35.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RC {48.75} \
    CONFIG.PCW_UIPARAM_DDR_T_RCD {7} \
    CONFIG.PCW_UIPARAM_DDR_T_RP {7} \
    CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_EN_ENET0 {1} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} \
    CONFIG.PCW_ENET0_PERIPHERAL_FREQMHZ {1000 Mbps} \
    CONFIG.PCW_ENET0_PERIPHERAL_CLKSRC {IO PLL} \
    CONFIG.PCW_ENET0_PERIPHERAL_DIVISOR0 {8} \
    CONFIG.PCW_ENET0_PERIPHERAL_DIVISOR1 {1} \
    CONFIG.PCW_ENET0_RESET_ENABLE {0} \
    CONFIG.PCW_ENET_RESET_ENABLE {0} \
    CONFIG.PCW_EN_SDIO0 {1} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_SD0_GRP_CD_ENABLE {1} \
    CONFIG.PCW_SD0_GRP_CD_IO {MIO 10} \
    CONFIG.PCW_SD0_GRP_WP_ENABLE {0} \
    CONFIG.PCW_SD0_GRP_POW_ENABLE {0} \
    CONFIG.PCW_SDIO_PERIPHERAL_DIVISOR0 {10} \
    CONFIG.PCW_SDIO_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_EN_QSPI {1} \
    CONFIG.PCW_QSPI_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_QSPI_QSPI_IO {MIO 1 .. 6} \
    CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1} \
    CONFIG.PCW_QSPI_GRP_SINGLE_SS_IO {MIO 1 .. 6} \
    CONFIG.PCW_SINGLE_QSPI_DATA_MODE {x4} \
    CONFIG.PCW_QSPI_PERIPHERAL_FREQMHZ {200} \
    CONFIG.PCW_QSPI_PERIPHERAL_DIVISOR0 {5} \
    CONFIG.PCW_EN_UART0 {1} \
    CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_UART0_UART0_IO {MIO 14 .. 15} \
    CONFIG.PCW_UART_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_UART_PERIPHERAL_DIVISOR0 {10} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_FCLK_CLK0_BUF {TRUE} \
    CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0 {1} \
    CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1 {1} \
    CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ {50.000000} \
    CONFIG.PCW_CLK0_FREQ {50000000} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR {1} \
  ]
  set_property -dict $cfg $cell
}

# MIO electrical settings, also verbatim from the vendor hand-off.  Kept as a
# separate list because they are 4 lines per pin and drown the block above.
proc apply_ps7_mio { cell } {
  set mio [list]
  # ENET0 RGMII: 16..21 out (fast), 22..27 in (fast), all 1.8 V
  foreach p {16 17 18 19 20 21} {
    lappend mio CONFIG.PCW_MIO_${p}_DIRECTION {out} \
                 CONFIG.PCW_MIO_${p}_IOTYPE {LVCMOS 1.8V} \
                 CONFIG.PCW_MIO_${p}_PULLUP {enabled} \
                 CONFIG.PCW_MIO_${p}_SLEW {fast}
  }
  foreach p {22 23 24 25 26 27} {
    lappend mio CONFIG.PCW_MIO_${p}_DIRECTION {in} \
                 CONFIG.PCW_MIO_${p}_IOTYPE {LVCMOS 1.8V} \
                 CONFIG.PCW_MIO_${p}_PULLUP {enabled} \
                 CONFIG.PCW_MIO_${p}_SLEW {fast}
  }
  # MDIO / MDC
  lappend mio CONFIG.PCW_MIO_52_DIRECTION {out} CONFIG.PCW_MIO_52_IOTYPE {LVCMOS 1.8V} \
              CONFIG.PCW_MIO_52_PULLUP {enabled} CONFIG.PCW_MIO_52_SLEW {slow} \
              CONFIG.PCW_MIO_53_DIRECTION {inout} CONFIG.PCW_MIO_53_IOTYPE {LVCMOS 1.8V} \
              CONFIG.PCW_MIO_53_PULLUP {enabled} CONFIG.PCW_MIO_53_SLEW {slow}
  # SD0 + card detect
  foreach p {40 41 42 43 44 45} {
    lappend mio CONFIG.PCW_MIO_${p}_DIRECTION {inout} \
                 CONFIG.PCW_MIO_${p}_IOTYPE {LVCMOS 1.8V} \
                 CONFIG.PCW_MIO_${p}_PULLUP {enabled} \
                 CONFIG.PCW_MIO_${p}_SLEW {slow}
  }
  lappend mio CONFIG.PCW_MIO_10_DIRECTION {in} CONFIG.PCW_MIO_10_IOTYPE {LVCMOS 3.3V} \
              CONFIG.PCW_MIO_10_PULLUP {enabled} CONFIG.PCW_MIO_10_SLEW {slow}
  # UART0
  lappend mio CONFIG.PCW_MIO_14_DIRECTION {in} CONFIG.PCW_MIO_14_IOTYPE {LVCMOS 3.3V} \
              CONFIG.PCW_MIO_14_PULLUP {enabled} CONFIG.PCW_MIO_14_SLEW {slow} \
              CONFIG.PCW_MIO_15_DIRECTION {out} CONFIG.PCW_MIO_15_IOTYPE {LVCMOS 3.3V} \
              CONFIG.PCW_MIO_15_PULLUP {enabled} CONFIG.PCW_MIO_15_SLEW {slow}
  # QSPI
  lappend mio CONFIG.PCW_MIO_1_DIRECTION {out} CONFIG.PCW_MIO_1_IOTYPE {LVCMOS 3.3V} \
              CONFIG.PCW_MIO_1_PULLUP {enabled} CONFIG.PCW_MIO_1_SLEW {slow} \
              CONFIG.PCW_MIO_6_DIRECTION {out} CONFIG.PCW_MIO_6_IOTYPE {LVCMOS 3.3V} \
              CONFIG.PCW_MIO_6_PULLUP {disabled} CONFIG.PCW_MIO_6_SLEW {slow}
  foreach p {2 3 4 5} {
    lappend mio CONFIG.PCW_MIO_${p}_DIRECTION {inout} \
                 CONFIG.PCW_MIO_${p}_IOTYPE {LVCMOS 3.3V} \
                 CONFIG.PCW_MIO_${p}_PULLUP {disabled} \
                 CONFIG.PCW_MIO_${p}_SLEW {slow}
  }
  set_property -dict $mio $cell
}
