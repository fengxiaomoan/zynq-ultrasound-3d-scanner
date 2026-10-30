# F1 simulation entry: three benches, all of them gates.
#   powershell -ExecutionPolicy Bypass -File .\run_sim.ps1
#
#   1. tb_f1            I2C + bring-up + 14-byte burst      -> PASS: ... samples=N
#   2. tb_i2c_recovery  stuck bus -> 9 SCL pulses -> STOP   -> I2C_RECOVERY_PASS
#   3. tb_pose_fusion   RTL == tools/f1_pose_ref.py, bit for bit
#                                                          -> POSE_FUSION_PASS n=.. latency=51
#
# The vectors for (3) are regenerated every run from the PC model, so a change in
# either side shows up as a mismatch instead of silently drifting.
param(
    [string]$VivadoRoot = $env:VIVADO_BIN,
    [string]$WorkDir    = "",
    [string]$Python     = 'python'
)
if (-not $VivadoRoot) { $VivadoRoot = 'D:\Xilinx\2025.1\Vivado\bin' }
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path $here -Parent
$f1   = Join-Path $root 'src\rtl\f1'
$tb   = Join-Path $here 'tb'
$repo = $root
if (-not $WorkDir) { $WorkDir = Join-Path $root 'build\output\sim_f1' }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Run-Step([string]$name, [scriptblock]$body) {
    Write-Host "=== $name ==="
    & $body
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

Push-Location $WorkDir
try {
    # 0) vectors from the bit-exact PC model
    & $Python (Join-Path $repo 'src\host\tools\f1_pose_ref.py') --vectors (Join-Path $WorkDir 'pose_vectors.txt')
    if ($LASTEXITCODE -ne 0) { throw 'f1_pose_ref.py failed' }

    Run-Step 'xvlog' {
        & (Join-Path $VivadoRoot 'xvlog.bat') -sv `
            (Join-Path $f1 'i2c_master.sv') `
            (Join-Path $f1 'mpu6050_bringup.sv') `
            (Join-Path $f1 'pose_fusion.sv') `
            (Join-Path $tb 'tb_mpu6050_model.sv') `
            (Join-Path $tb 'tb_f1.sv') `
            (Join-Path $tb 'tb_i2c_recovery.sv') `
            (Join-Path $tb 'tb_pose_fusion.sv')
    }

    # ---- 1) I2C bring-up
    Run-Step 'xelab tb_f1' { & (Join-Path $VivadoRoot 'xelab.bat') tb_f1 -s tbf1 }
    $log1 = & (Join-Path $VivadoRoot 'xsim.bat') tbf1 -R 2>&1
    $log1 | Select-String -Pattern 'LINE_CHECK|WHO_OK|DATA_OK|PASS:|FAIL'
    if (-not ($log1 -match 'PASS:')) { throw 'tb_f1 did not print PASS' }

    # ---- 2) bus recovery
    Run-Step 'xelab tb_i2c_recovery' { & (Join-Path $VivadoRoot 'xelab.bat') tb_i2c_recovery -s tbrec }
    $log2 = & (Join-Path $VivadoRoot 'xsim.bat') tbrec -R 2>&1
    $log2 | Select-String -Pattern 'TIMEOUT_SEEN|RECOVERY_DONE|NEXT_CMD|I2C_RECOVERY_PASS|FAIL'
    if (-not ($log2 -match 'I2C_RECOVERY_PASS')) { throw 'recovery bench did not pass' }

    # ---- 3) pose fusion, bit exact
    Run-Step 'xelab tb_pose_fusion' { & (Join-Path $VivadoRoot 'xelab.bat') tb_pose_fusion -s tbpose }
    $log3 = & (Join-Path $VivadoRoot 'xsim.bat') tbpose -R 2>&1
    $log3 | Select-String -Pattern 'MISMATCH|SAMPLES=|POSE_FUSION|FAIL'
    if (-not ($log3 -match 'POSE_FUSION_PASS')) { throw 'pose fusion bench did not pass' }

    Write-Host 'SIM_ALL_PASS  (tb_f1, tb_i2c_recovery, tb_pose_fusion)'
}
finally {
    Pop-Location
}
