# Rebuild the peak_dsp regression: vector -> reference word -> xsim.
#
#   powershell -File fpga\tb\run_sim.ps1
#   powershell -File fpga\tb\run_sim.ps1 -Csv live_run\zcheck\raw\p002_f00.csv
#
# Prints the reference 40-bit word (tools/dsp_ref.py) and the RTL 40-bit word
# (xsim); they must be equal. The testbench drives frame number 0, so the
# reference is always computed with frame=0 here. The frame-field check in
# sim_v2_20261025.log was made with a temporary testbench copy (frame=17),
# because xsim's command line did not accept --testplusarg in this install.
param(
    [string]$Csv = "",
    [string]$VivadoBin = $env:VIVADO_BIN
)
if (-not $VivadoBin) { $VivadoBin = "D:\Xilinx\2025.1\Vivado\bin" }
$here = $PSScriptRoot
$root = Split-Path $here -Parent
$rtl = Join-Path $root "src\rtl\peak_dsp.sv"
if (-not $Csv) { $Csv = Join-Path $root "sim\vectors\frame.csv" }
$csvPath = if ([System.IO.Path]::IsPathRooted($Csv)) { $Csv } else { Join-Path $root $Csv }

Push-Location $root
    python (Join-Path $root "src\host\tools\dsp_ref.py") $csvPath $here 0
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "dsp_ref.py failed" }
Pop-Location

Push-Location $here
    & (Join-Path $VivadoBin "xvlog.bat") $rtl (Join-Path $root "src\rtl\peak_centroid.sv") (Join-Path $here "tb\tb_peak_dsp.sv")
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "xvlog failed" }
    & (Join-Path $VivadoBin "xelab.bat") -debug typical tb_peak_dsp -s tb_sim
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "xelab failed" }
    & (Join-Path $VivadoBin "xsim.bat") tb_sim -R
    $rc = $LASTEXITCODE
Pop-Location
exit $rc
