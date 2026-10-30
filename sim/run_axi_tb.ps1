# acq_axi_regs regression (M2b frame channel + M3 pose channel).
#   powershell -ExecutionPolicy Bypass -File .\run_axi_tb.ps1
#
# Gate: must end with TB_PASS.  It covers the M2a/M2b behaviour (trigger cadence,
# SEQ, missed accounting, ACK, payload bit-exactness) AND the F1 pose window
# (0x30..0x3C coherent, independent of the 90 Hz frame latch).
param(
    [string]$VivadoRoot = $env:VIVADO_BIN,
    [string]$WorkDir    = ""
)
if (-not $VivadoRoot) { $VivadoRoot = 'D:\Xilinx\2025.1\Vivado\bin' }
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path $here -Parent
if (-not $WorkDir) { $WorkDir = Join-Path $root 'build\output\sim_axi' }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Push-Location $WorkDir
try {
    & (Join-Path $VivadoRoot 'xvlog.bat') -sv (Join-Path $root 'src\rtl\acq_axi_regs.v') (Join-Path $here 'tb\tb_acq_axi_regs.sv')
    if ($LASTEXITCODE -ne 0) { throw 'xvlog failed' }
    & (Join-Path $VivadoRoot 'xelab.bat') tb_acq_axi_regs -s tbaxi
    if ($LASTEXITCODE -ne 0) { throw 'xelab failed' }
    $log = & (Join-Path $VivadoRoot 'xsim.bat') tbaxi -R 2>&1
    $log | Select-String -Pattern 'PASS|FAIL|TB_PASS|TB_FAIL'
    if (-not ($log -match 'TB_PASS')) { throw 'acq_axi_regs TB did not pass' }
    Write-Host 'AXI_TB_PASS'
}
finally {
    Pop-Location
}
