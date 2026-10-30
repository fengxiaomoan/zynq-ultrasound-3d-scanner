# 基于 AMD Zynq-7020 的实时超声三维扫描与形态异常检测系统

**2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · AMD 自主选题（初级组）**

> 一句话：用 1 MHz 单阵元水浸超声 + 双轴机械扫描 + Zynq-7020，把“确定性采集、板上定点 DSP、位姿锁存、网页三维呈现、姿态交互”做成一条可测量、可复现、可解释的闭环。

> **仓库**：<https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner>（当前私有，验收后转公开）
> **演示视频**（约 58 MB，不进仓库）：[Releases → v1.0-assets](https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner/releases/tag/v1.0-assets)

> **提交包位置**：`..\upload\ultrasound_3d_scanner\`（已按 3.3.5.4 整理，未压缩）。
> 本目录是工作副本，多保留了演示视频 mp4、Word 版 docx 与 `submission/` 暂存。

---

## 1. 这个项目解决什么问题

二维超声只给一个切面，三维结构要靠多角度扫描。扫描一密，数据量、实时处理和交互延迟就会同时成为瓶颈；如果发射/采样再由 PC 触发，毫秒级抖动会变成米级的假距离。

本项目不声称做临床设备，而是回答一个工程问题：**在低成本单阵元探头和中等规模 FPGA 上，能不能把“采集—处理—重建—比对—交互”做成一条能拿证据说话的链路？**

答案是：能，但要分清哪些是实测、哪些是仿真、哪些还没做。本包把这三类分开写。

---

## 2. 三个“能看见”的结果

| 结果 | 数字 | 证据 |
|---|---|---|
| 板上出结果，不再上传原始波形 | 每帧 5 B，回读 2.48–2.80 ms，相对 ILA 477–555 ms 提升 **171–202×** | `data/real/dsp_hw_compare.json` |
| PL 自主触发，PS 连续读不丢帧 | **90.84–91.05 fps**，30 s `missed=0` | `data/real/_m2b_ps_rate.log` |
| 真实三维侧壁 | 三层 **72 格/71 有效，144 顶点/192 面**；六层 **141/131，288/480** | `data/real/_m2b_3layer_signed.json`、`_m2b_6layer.json` |
| 姿态跟手 | **716.6 Hz** 采样，页面 20 Hz，手转模型同步 | `data/real/f1_pose_samples.txt` |
| 数字体模 + 异常检测 | 四件 4096 点，MAE **0.189 mm**；8 个凸起 **8/8、0 误报** | `data/reference/bench/`、`data/reference/anomaly/` |

> 真实四件全高度扫描、真实凸起检出的完整流程见演示视频；本文的量化表仍以已留证据的三层/六层与数字体模为主，绝对尺寸未标定。详见 §7。

---

## 3. 5 分钟跑起来（不需要板子）

```powershell
cd <package>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING='utf-8'

# 四件数字体模：应输出 MAE 0.189–0.190 mm
python src\host\bench\run_bench.py

# 异常检测：应输出 8/8、0 误报
python src\host\anomaly\run_anomaly.py

# 报告插图（需要中文字体）
python report\assets\make_figures.py
```

有 Vivado 2025.1 的话，再跑三组仿真：

```powershell
pwsh -File sim\run_sim.ps1        # PEAK_WORD=... STROBES=1 WORD_STABLE=1
pwsh -File sim\run_axi_tb.ps1     # TB_PASS / AXI_TB_PASS
pwsh -File sim\run_f1_sim.ps1     # MISMATCHES=0 LATENCY=51 SIM_ALL_PASS
```

本包在 2026-10-27 20:58–20:59 重跑过这三组，日志在 `sim/results/pkg_*.log`。

---

## 4. 目录

```
ultrasound_3d_scanner/
├─ README.md                 # 本文件：简介 + 快速开始 + 目录对照
├─ LICENSE                   # MIT（需替换年份/署名）
├─ requirements.txt          # numpy + matplotlib
├─ src/
│  ├─ rtl/                   # 采集核、峰值/质心 DSP、电机、姿态、AXI、顶层
│  ├─ constraints/           # XDC（含 T10/T11 I2C）
│  ├─ ps/                    # PS 裸机 C、lwIP 页面、构建脚本
│  └─ host/                  # Python 主机：wscan、工具、体模、异常
├─ sim/
│  ├─ tb/                    # 峰值 DSP、AXI 帧/姿态、F1 三组 tb
│  ├─ vectors/               # 真实帧 CSV、样本、姿态向量
│  ├─ results/               # 本次重跑的日志
│  └─ run_*.ps1              # 一键仿真
├─ build/
│  ├─ build_ps_m3_pkg.tcl    # M3 位流（包内相对路径）
│  ├─ build_dsp_pkg.tcl      # DSP 位流
│  ├─ io_pin_diff.tcl        # 引脚门（解析不到就 error）
│  └─ reports/               # 资源/时序/DRC/引脚 + 摘要
├─ board/
│  ├─ bitstream/             # M3 与 DSP 位流 + ltx
│  ├─ xsa/                   # ps_m3.xsa + ps7_init.tcl
│  ├─ firmware/              # 预编译 ELF/BIN
│  ├─ tcl/                   # 加载、扫描、采集、DSP 回读
│  └─ logs/                  # 板上实测日志
├─ data/
│  ├─ real/                  # 真实测量：帧率、模型、重复性、姿态
│  ├─ reference/             # 体模/异常参考结果
│  ├─ demo/                  # 4096 点演示与旧版全流程视频
│  └─ figures/               # 报告/视频可复用图
├─ skill/                    # 9 个技能包 + README
├─ submission/               # 提交暂存：技术文档/图片/关键词
└─ report/
   ├─ 01_design_report.md    # 设计报告（主文档）
   ├─ 02_llm_collaboration.md
   ├─ 03_skill_extraction.md
   ├─ 04_reproduction.md
   ├─ 05_evidence_index.md
   ├─ 06_video_shooting_guide.md
   ├─ 07_submission_checklist.md
   └─ assets/                # 插图与生成脚本
```

**目录对照**：赛题推荐 `src / sim / build / board / data / skill / report`，本包完全采用；`src` 下再分 `rtl / constraints / ps / host`，`data` 下再分 `real / reference / demo / figures`。根目录没有额外中文命名。

---

## 5. 系统在做什么

```
1 MHz 发射（8 周期）
  → 目标反射 → 接收探头 → AD8331 → 双路 10 bit ADC（5 MSPS）
  → 两路相减（11 bit diff）
  → PL：DC 阻断 → 1 MHz I/Q → 10 点滑动和 → |I|+|Q| → 窗内峰值/质心
  → 40 bit 峰值字 / 56 bit 质心字
  → AXI 176 bit 帧记录（SEQ/ACK/CDC）
  → PS：8192 帧环形缓冲 → C 算法 → /state JSON → 网页
  → PC：标定 → 质量门 → (z, az, r) 点云 → 剖面 → 旋转体网格 → 残差聚类
```

FPGA 负责“确定性”和“吞吐”，PS 负责“搬运/协议/网页”，PC 负责“离线优化/可视化”。姿态（MPU6050）只进显示，不进测量，保证参考件与待测件的可比性。

详细的原理、接口、寄存器、优化对比见 [`report/01_design_report.md`](report/01_design_report.md)。

---

## 6. 证据等级

本包所有结论分四级，报告和技能包里逐条标注：

| 等级 | 含义 | 例子 |
|---|---|---|
| `real` | 在本项目硬件上跑出来，有日志/JSON | 90.9 fps、2.6 ms 回读、三层模型 |
| `RTL-sim` | xsim 与参考模型逐位比对 | `0x8005A30849 == ref` |
| `synthetic` | 数字体模/合成波形 | MAE 0.189 mm、8/8 异常 |
| `static` | 综合/实现/引脚/资源/代码常量 | 6,921 LUT、WNS 1.399 ns |

逐条映射见 [`report/05_evidence_index.md`](report/05_evidence_index.md)。**不要把 `synthetic` 写成“实测”。**

---

## 7. 已知限制（如实写）

- 真实四件（圆柱/两种锥台/台阶轴）的**完整扫描流程见演示视频**；本文的量化模型以圆柱三层/六层为主。
- **真实凸起检出的量化结果见演示视频**；8/8 是数字体模，不能替代真实声学。旧 10 µs 窗对 10 mm 凸起无签名，窗和阈值要按实测重定。
- **绝对尺寸未标定**；半径锚定名义 Ø28，只能比较差异。
- 随包 M3 位流是 20:14 重建版（6,921 LUT，WNS 1.399）；**716.6 Hz 是在 18:51 同源构建上测的**，20:14 版未复测。
- 环形缓冲 8192 帧，按层扩容前大约支持 8 层。
- 不是临床设备，仅水槽/仿体原理验证。

这些限制不是“扣分项”，而是“下一版的工作清单”。把它们写清楚，比把仿真写成实测更可信。

---

## 8. 文档入口

| 想了解 | 看 |
|---|---|
| 设计报告（背景、原理、接口、优化、验证） | [`report/01_design_report.md`](report/01_design_report.md) |
| 设计报告 PDF / DOCX | [`report/export/design_report.pdf`](report/export/design_report.pdf)、[`report/export/design_report.docx`](report/export/design_report.docx) |
| 技术文档（按官方模板，**最终版**） | [`report/export/technical_document.pdf`](report/export/technical_document.pdf)、[`report/export/technical_document.docx`](report/export/technical_document.docx) |
| 拍视频前的完整讲解（从实物到指标 + Q&A） | [`report/09_project_walkthrough.md`](report/09_project_walkthrough.md) |
| 大模型协作记录（提示词/回答/纠错/工作流） | [`report/02_llm_collaboration.md`](report/02_llm_collaboration.md) |
| 技能包怎么提炼、怎么验证、边界 | [`report/03_skill_extraction.md`](report/03_skill_extraction.md) |
| 从零复现（纯软件/仿真/上板） | [`report/04_reproduction.md`](report/04_reproduction.md) |
| 每个数字对应哪个文件 | [`report/05_evidence_index.md`](report/05_evidence_index.md) |
| 视频怎么拍（分镜/解说/设备/合规） | [`report/06_video_shooting_guide.md`](report/06_video_shooting_guide.md) |
| 提交前 32 项检查 | [`report/07_submission_checklist.md`](report/07_submission_checklist.md) |
| 提交暂存（PDF/图片/关键词） | [`submission/README.md`](submission/README.md) |
| 9 个可复用技能 | [`skill/README.md`](skill/README.md) |
| 构建/资源/哈希 | [`build/reports/resource_summary.md`](build/reports/resource_summary.md) |

---

## 9. 工具与许可

- Vivado / Vitis 2025.1（本项目验证版本）；
- Python 3.12+（numpy、matplotlib）；
- Node.js（仅页面离线冒烟，可选）；
- 许可证：MIT，见 [`LICENSE`](LICENSE)（版权人已填 `2026 linzhiye`）。
- 第三方工具/文档不打包，仅在报告中引用（UG901/UG904/UG1399/UG949、Vitis Libraries、PYNQ）。

---

## 10. 当前状态

- 代码、仿真、构建报告、上板证据、技能包、设计报告、技术文档：**已完成本地整理**；
- **全部代码（提交包）**：`..\upload\ultrasound_3d_scanner\`（推荐结构，未压缩；验收后整目录压 RAR）；
- GitHub：**已上传**，<https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner>（私有；检查完在 Settings → Danger Zone 转 Public，再把链接填进提交页）；
- 演示视频：5 个旧版演示已传到 Release `v1.0-assets`；提交页要求的 ≤3 分钟版**尚未拍摄**（旧版 3 分 50 秒只能作素材）；
- 提交页还需要：RAR 代码包（≤200 MB）、承诺书 PDF、全貌图 1 张、开发板照片 ≤4 张、三个关键词（见 §0）；
- 提交截止：2026-11-04 18:00（以官网为准）。

> 如果只读一个文件，读 `report/01_design_report.md`；如果只跑一个命令，跑 `python src\host\bench\run_bench.py`。
