# Build the whole package: M3 bitstream + reports, optionally DSP and PS firmware.
#
#   pwsh -File build\build_all.ps1
#   pwsh -File build\build_all.ps1 -SkipDsp -SkipFirmware
#
# Fails fast; never programs the board.

param(
    [string]$VivadoBin = $env:VIVADO_BIN,
    [string]$XilinxRoot = $env:XILINX_ROOT,
    [switch]$SkipDsp,
    [switch]$SkipFirmware
)
$ErrorActionPreference = 'Stop'
if (-not $VivadoBin) { $VivadoBin = 'D:\Xilinx\2025.1\Vivado\bin' }
if (-not $XilinxRoot) { $XilinxRoot = 'D:\Xilinx\2025.1' }

$here = $PSScriptRoot
$root = Split-Path $here -Parent
$out  = Join-Path $here 'output'
New-Item -ItemType Directory -Force -Path $out | Out-Null

$vivado = Join-Path $VivadoBin 'vivado.bat'
if (-not (Test-Path $vivado)) { throw "Vivado not found: $vivado (set VIVADO_BIN)" }

Write-Host '=== 1/3 M3 bitstream ==='
& $vivado -mode batch -nojournal -notrace `
    -source (Join-Path $here 'build_ps_m3_pkg.tcl') `
    -log (Join-Path $out 'build_m3.log')
if ($LASTEXITCODE -ne 0) { throw "M3 build failed ($LASTEXITCODE)" }

if (-not $SkipDsp) {
    Write-Host '=== 2/3 DSP bitstream ==='
    & $vivado -mode batch -nojournal -notrace `
        -source (Join-Path $here 'build_dsp_pkg.tcl') `
        -log (Join-Path $out 'build_dsp.log')
    if ($LASTEXITCODE -ne 0) { throw "DSP build failed ($LASTEXITCODE)" }
}

if (-not $SkipFirmware) {
    Write-Host '=== 3/3 PS firmware ==='
    $env:XILINX_ROOT = $XilinxRoot
    python (Join-Path $root 'src\ps\build_m2b.py')
    if ($LASTEXITCODE -ne 0) { throw "firmware build failed ($LASTEXITCODE)" }
}

Write-Host 'BUILD_ALL_OK'
Write-Host "  M3 : $out\fpga_ps_m3"
Write-Host "  DSP: $out\fpga_dsp_v2"
Write-Host "  FW : $out\firmware"
