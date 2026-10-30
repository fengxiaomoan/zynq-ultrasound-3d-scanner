# 技能包总览

本目录是可复用的技能包：把项目中实际遇到的判断、失败与回归，整理成换一个题目、换一块板卡也能使用的做法，而不是按模块拆分项目文档。

---

## 1. 先说结论：从 9 个“专用小块”合并成 9 个“可复用技能”

最初版本按模块拆得很细：采集、DSP、帧握手、姿态、建模、异常、构建、证据、PYNQ，共 9 个。这种拆法有两个问题：过于专用，换一个题目难以复用；工作区中已有的通用技能没有纳入。

这一版做了三件事：

1. **合并**：把“采集 + 构建”“DSP + 帧握手”“建模 + 异常”分别合并，减少“一个技能只讲一个模块”的碎片感；
2. **通用化**：每个技能增加“可替换点”，写清换板卡/换传感器/换题目时改哪里；
3. **补通用技能**：把工作区里已有的 `fpga-contest-helper`、`china-shopping-search` 收进来，并新增 `mechanical_design_to_print`，覆盖“机械/打印”这条通用交付链。

合并后的 9 个技能：

| # | 技能 | 适用任务 | 类型 | 验证等级 |
|---|---|---|---|---|
| 01 | [`fpga_capture_bringup`](01_fpga_capture_bringup/SKILL.md) | 新板 ADC/高速采集 bring-up + 可复现构建门禁 | 通用 | 板上实测 |
| 02 | [`rtl_dsp_pipeline`](02_rtl_dsp_pipeline/SKILL.md) | 定点 DSP 搬进 RTL + AXI 帧记录/PS 读取 | 通用 | 板上实测 |
| 03 | [`sensor_fusion_ui`](03_sensor_fusion_ui/SKILL.md) | IMU/传感器 → FPGA 定点融合 → 网页 3D | 通用 | 板上实测 |
| 04 | [`scanning_3d_reconstruction`](04_scanning_3d_reconstruction/SKILL.md) | 扫描式三维重建 + 标准件/待测件残差比对 | 领域方法 | 板上实测 + 仿真 |
| 05 | [`evidence_review`](05_evidence_review/SKILL.md) | 报告/视频/提交前的证据分级与红队 | 通用（元技能） | 全项目使用 |
| 06 | [`fpga_contest_helper`](06_fpga_contest_helper/SKILL.md) | FPGA 竞赛：拆题、认板、RTL/CDC、时序、交付 | 通用 | 工作区既有技能 |
| 07 | [`pynq_overlay_io`](07_pynq_overlay_io/SKILL.md) | PYNQ overlay：AXI-Lite + DMA 通用 bring-up | 通用（PYNQ 加分项） | 部分验证，文内标注 |
| 08 | [`mechanical_design_to_print`](08_mechanical_design_to_print/SKILL.md) | CAD → STL/3MF → 打印清单/装配 | 通用 | CAD 验证 + 实物装配 |
| 09 | [`procurement_search`](09_procurement_search/SKILL.md) | BOM/器件/模块的国内采购与比价 | 通用 | 工作区既有技能 |

---

## 2. 全目录扫描结果：还找到了什么

对工作区做过一次 `SKILL.md` 全目录扫描，结果如下：

| 位置 | 技能 | 处理 |
|---|---|---|
| `FPGA_Contest_Starter_v1.0.0/.agents/skills/fpga-contest-helper` | `fpga-contest-helper` | **收入**为 06，保留 5 个 references |
| `china-shopping-search` | `china-shopping-search` | **收入**为 09（采购/比价） |
| `team-handoff` | `team-handoff` | **不收入**：依赖 SCAN 团队网页和成员绑定，换队伍不可用 |
| `full_scan_workflow/skills/ultrasonic-cylinder-modeling` | `ultrasonic-cylinder-modeling` | 内容已合并进 04，原文件不重复收 |
| `3Dprinter/design_output` | 不是 skill，是 3D 打印**输出包** | 转成 08 的验证材料，放在 `data/mechanical/` |

工作区中的 “output skill” 实际对应的是 `3Dprinter/design_output/`（打印清单、STL/STEP、装配说明、验证 JSON），它本身不是 `SKILL.md`。这一版把它提炼成 `08_mechanical_design_to_print`，使“机械设计 → 打印 → 装配”这条链路也可以复用。

---

## 3. 每个技能怎么写

统一模板：

- **适用范围**：什么任务、什么硬件/工具条件下可用；
- **输入**：需要先准备什么；
- **使用方法**：编号步骤 + 可复制命令 + 判据；
- **已验证效果**：本项目实际跑出的数字/结论；
- **失效条件**：什么时候不能用，或者会得出错误结论；
- **来源**：从哪次失败/观察中总结；
- **边界**：不承诺什么。

技能不是“操作手册的复制”。它记录的是**判断**：先看什么、什么现象说明什么、什么时候必须停下来。

---

## 4. 这些技能是怎么提炼出来的

不是先写模板再填内容，而是反过来：

1. **先有失败**：每个技能至少对应一次“现象无法用现有文档解释”的事件；
2. **再做定位**：把现象拆成可区分假设，设计最小实验，留下日志；
3. **再写判据**：把“怎么算修好”写成一条可执行的检查（逐位、`missed=0`、`FRAME_STEP=1` 等）；
4. **再划边界**：写清“这个结论只在哪块板、哪个窗口、哪种目标上成立”；
5. **最后才抽象**：去掉本队专有的型号/引脚，留下可迁移的步骤和陷阱。

三个例子：

- `02_rtl_dsp_pipeline` 来自峰值 DSP 的 40 位字在板上对不上。根因不是算术，而是 `active` 从不清零，`sid` 回绕后每 13.1 ms 重新锁存。技能里因此有一条硬性回归：**tb 必须喂超过 65,536 个样本**。
- `04_scanning_3d_reconstruction` 来自 24 方位环每次少 14.34°（23×171=3933，不是 4096），以及 10 µs 固定窗对 3–12 mm 凸起“看不见”。技能里因此要求：**环必须闭合**、**缺陷搜索把窗放宽到 66–84 µs**、**连续性滤波在找缺陷时必须关掉**。
- `01_fpga_capture_bringup` 来自 `-nolog` 把 `-log` 压掉、引脚 diff 正则解析不到却“静默通过”。技能里因此要求：**解析不到就 error**，不能把空表当通过。

---

## 5. 怎么用这些技能

### 5.1 换题目复用

- `01`/`02`：任何“ADC/传感器 → FPGA → PS”的采集与结果回读；
- `03`：任何“IMU/传感器 → FPGA → 上位机 3D/仪表”的交互；
- `04`：任何“旋转/平移扫描 + 标准件 vs 待测件”的形态检测；
- `05`：任何提交材料的证据审查；
- `08`：任何 3D 打印结构件；
- `09`：任何 BOM 采购。

### 5.2 换板卡复用

技能里把“板卡相关”的部分单独列出：

- 时钟/复位/引脚：换成新板的约束与 IO 标准；
- ADC 位宽/采样率：改 `FRAME_CYCLES`、分频、窗口样本号；
- I2C 引脚/上拉：改 `scl/sda` 约束与电平；
- 电机：换驱动器时保留“斜坡/看门狗/限位”的接口语义；
- PYNQ：换 overlay 名/IP 名，不改验收顺序。

### 5.3 作为智能体的系统提示

可以把某个 `SKILL.md` 直接作为 agent 的任务说明（YAML front matter 里有 `name`/`description`）。建议搭配 `05_evidence_review` 一起用，防止 agent 把“仿真通过”写成“实测通过”。

---

## 6. 评价标准（自检）

按赛题“可复用性”要求，每个技能逐项自检：

| 项 | 要求 | 本仓库做法 |
|---|---|---|
| 适用范围 | 什么任务/硬件/输入 | 每个技能开头一段 |
| 使用方法 | 步骤、命令、判据 | 编号步骤 + 可复制命令 |
| 失效条件 | 什么时候不成立 | 单独一节，写“会错在哪” |
| 已验证效果 | 数字/结论 + 证据 | 数字 + 文件相对路径 |
| 来源 | 从哪些失败总结 | 单独一节，写现象与根因 |
| 边界 | 不承诺什么 | 单独一节 |
| 可迁移 | 换题/换板是否可用 | 每个技能的“替换点” + 第 5 节 |

---

## 7. 技能与评分项的对应

| 评分项 | 技能包的支撑 |
|---|---|
| 创新性与应用价值 | 03 把“手背姿态 + 实时建模”的交互固化；04 把“扫描 + 异常”的方法固化 |
| 性能与资源优化 | 01/02 的构建门、回读加速、数据压缩 |
| 功能正确性与完整性 | 01/02/03 的三级验证链；04 的真实/仿真分层 |
| 大模型协作与技能包 | 本目录 + `report/02_llm_collaboration.md` + `report/03_skill_extraction.md` |
| 文档质量与可复现性 | 05 + `report/04_reproduction.md` + `report/05_evidence_index.md` |

---

## 8. 通用 PYNQ 加分项

赛题对“面向 PYNQ 框架、且不与本队题目绑定”的通用 Skill 单独加分。`07_pynq_overlay_io` 只依赖 PYNQ 的 `Overlay`/`MMIO`/`DMA` 接口，不绑定超声、不绑定本队引脚。

**验证边界**：本队实际使用裸机 PS + AXI-Lite，PYNQ 镜像上的 Python API 没有在本队硬件上执行。技能里把“已验证”的部分（AXI 寄存器语义、帧记录、CDC、DMA 方向）与“未执行”的部分（`pynq.Overlay` 的具体调用、`allocate` 的缓存属性）分开写，并给出上板验收脚本。这样不冒充实测，也能让下一个队伍直接照着跑。
