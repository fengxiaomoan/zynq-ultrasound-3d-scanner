# 源码

```
src/
├─ rtl/            # 可综合 RTL
├─ constraints/    # XDC
├─ ps/             # PS 裸机 C、lwIP 页面、构建
└─ host/           # Python 主机：wscan、工具、姿态网页
```

---

## 1. RTL 阅读顺序

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `rtl/ultrasound_test_core.sv` | 帧状态机、ADC 分频、TX 触发、锁定时间 |
| 2 | `rtl/tx_probe_test.sv` | 1 MHz、8 周期 burst |
| 3 | `rtl/peak_dsp.sv` | DC 阻断、I/Q、包络、窗内峰值、40 位锁存、停机 |
| 4 | `rtl/peak_centroid.sv` | 窗内加权质心、56 位字 |
| 5 | `rtl/merged_top.sv` | 顶层：采集 + 电机 + 位姿锁存 + DSP + VIO/ILA |
| 6 | `rtl/acq_axi_regs.v` | AXI 寄存器、176 bit 帧记录、CDC、姿态窗口、自主触发 |
| 7 | `rtl/merged_top_bd_f1.v` | BD 壳：把 `merged_top`、`acq_axi_regs`、姿态字接起来 |
| 8 | `rtl/f1/pose_fusion.sv` | CORDIC atan2、整数 sqrt、α=31/32、51 拍流水 |
| 9 | `rtl/f1/i2c_master.sv` | 400 kHz I2C、9 脉冲恢复 |
| 10 | `rtl/f1/mpu6050_bringup.sv` | 寄存器初始化、14 字节 burst、绝对 tick 排程 |

复用的外部模块（原样收入）：

- `ultrasound_test_core.sv`、`tx_probe_test.sv`：13 号采集布局；
- `stepper_axis.sv`、`motor_pair.sv`、`motor_manual_guard.sv`：11 号电机布局。

---

## 2. PS 软件

| 文件 | 作用 |
|---|---|
| `ps/sw/src/acq.c/.h` | AXI 帧读取、SEQ 双读、ACK、arm/period、姿态窗口 |
| `ps/sw/src/alg.c/.h` | 可移植 C 算法（与 Python 逐字节一致） |
| `ps/sw/src/model.c/.h` | 环形缓冲 → 分箱 → `/state` JSON（含网格/残差） |
| `ps/sw/src/net.c/.h` | lwIP raw HTTP：`/`、`/state`、`/api/*` |
| `ps/sw/src/main.c` | 主循环：读帧 → 入环 → 轮询网络 |
| `ps/sw/src/page_html.h` | 由 `src/host/tools/live_model_page.html` 生成（不要手改） |
| `ps/sw/host/*.c` | 主机侧：同一份 `alg.c`/`model.c` → CSV/JSON |
| `ps/build_m2b.py` | sdtgen + empyro 全自动构建 ELF/BIN |
| `../build/upstream/build_ps_m3.tcl` | 原始 M3 构建（绝对路径，仅参考） |

构建入口在 `build/build_ps_m3_pkg.tcl`（包内相对路径）。

---

## 3. 主机算法

| 文件 | 作用 |
|---|---|
| `host/wscan/frames.py` | ILA CSV 解码、基线/带通/包络/取峰、`dsp_samples()` |
| `host/wscan/geom.py` | 平板标定、双基地射线求交、标准球弧拟合 |
| `host/wscan/pipeline.py` | 质量门、逐点观测、旋转体/网格建模 |
| `host/wscan/vertical.py` | 圆柱/圆锥、镜面点、已知形状反演 |
| `host/wscan/profile.py` | 扫描计划/窗口/参数 |
| `host/wscan/report.py` | `REPORT.md` + 自包含 `index.html` |
| `host/run_workflow.py` | CLI：plan/simulate/axisym/ingest |
| `host/tools/dsp_ref.py` | 峰值 DSP 逐位参考模型 |
| `host/tools/dsp_hw_compare.py` | 板端字 vs 参考同帧比对 |
| `host/tools/robust_scan.py` | 每点多帧中值 + 方位中值 + 离群剔除 |
| `host/tools/live_model_page.html` | 页面源（生成 `page_html.h`） |
| `host/viewer/` | MPU6050 姿态驱动三维网页（`server.py` + WebGL + 测试） |
| `host/live_view.py` + `live_page.html` | 边扫边看：tail 采集目录，增量显示 A/B 扫与模型 |
| `host/tests/test_workflow.py` | 工作流单元测试（profile/geom/pipeline） |
| `host/README.md` | 主机侧运行方式与目录说明 |

---

## 4. 约束

| 文件 | 内容 |
|---|---|
| `constraints/merged_top.xdc` | 时钟/复位/ADC/TX/电机/ILA |
| `constraints/m1b_adc.xdc` | ADC 输入 |
| `constraints/f1_pins.xdc` | `scl T10` / `sda T11` |

M3 相对 M2b 只多 T10/T11；完整引脚见 `build/reports/m3_io.rpt`。
