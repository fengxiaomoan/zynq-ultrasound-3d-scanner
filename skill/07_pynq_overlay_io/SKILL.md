---
name: pynq_overlay_io
description: 'Use on any PYNQ-Z1/Z2/RFSoC/KV260 board to bring up a custom overlay: load the .bit/.hwh pair, inspect ip_dict, map AXI-Lite registers, allocate contiguous buffers, run an AXI DMA transfer, measure latency and diagnose the usual failures (overlay name mismatch, missing IP, cache coherency, TLAST, simple-mode size). This skill is deliberately not tied to ultrasound or to this team''s pins.'
---

# PYNQ overlay 通用 bring-up（AXI-Lite + DMA）

## 适用范围

- 手上有 Vivado 导出的 `.bit` + `.hwh`，要在 PYNQ 上加载；
- 需要从 Python 读写自定义 AXI-Lite 寄存器；
- 需要用 AXI DMA / Stream 搬一块连续数据；
- 换题目、换 PYNQ 板仍可用：只依赖 PYNQ 的 `Overlay`、`MMIO`、`allocate`、DMA 接口。

## 输入

- `.bit` 与同名 `.hwh`（必须成对，且与 bit 同一次构建）；
- 目标 PYNQ 镜像版本（2.7 / 3.x）；
- 寄存器映射（偏移、位宽、读写属性）；
- DMA 方向、位宽、最大传输长度。

## 使用方法

### 1. 加载 overlay，先看 `ip_dict`

```python
from pynq import Overlay, allocate
import numpy as np

ol = Overlay("/home/xilinx/design_1.bit")   # .hwh 必须同名同目录
print(ol.ip_dict.keys())
```

**判据**：能在 `ip_dict` 里看到自定义 IP 名；看不到，先查 `.hwh` 是否是这次构建的，不要改代码猜。

### 2. 读一个“身份寄存器”

在 RTL 里放一个只读 `ID = 0x5A5A_xxxx` 寄存器。Python 先读它：

```python
ip = ol.<your_ip_name>
print(hex(ip.read(0x00)))
```

**判据**：读回固定 ID。读不到或读回 0xFFFFFFFF，说明地址映射/总线/时钟有问题，先停。

### 3. 写/读 scratch 寄存器

```python
ip.write(0x04, 0x12345678)
assert ip.read(0x04) == 0x12345678
```

**判据**：写入回读一致；不一致查 `awvalid/awready`、时钟、复位、地址位宽。

### 4. 连续缓冲区

```python
buf = allocate(shape=(N,), dtype=np.uint32)
buf[:] = data
buf.sync_to_device()          # 若使用可缓存缓冲区
```

- 缓冲区必须物理连续；`allocate` 会处理；
- 大块数据用 `np.zeros`/`np.empty` 后 `sync_to_device`；
- 传输后 `buf.invalidate()` 再读，避免 cache 旧值。

**判据**：`buf.physical_address` 非空；传输前后数据一致。

### 5. DMA 传输

```python
dma = ol.axi_dma_0
dma.recvchannel.transfer(buf)
dma.recvchannel.wait()
```

- 确认 DMA 是 simple mode 还是 SG mode；
- simple mode 单次长度受 `BTT` 位宽限制；
- 发送端必须产生 `TLAST`，否则 DMA 不结束；
- 先做“已知 pattern 回环”，再做真实数据。

**判据**：`wait()` 返回、`buf` 内容与预期一致；连续 100 次无 timeout。

### 6. 延迟与吞吐

```python
import time
t0 = time.perf_counter()
for _ in range(100):
    dma.recvchannel.transfer(buf)
    dma.recvchannel.wait()
t1 = time.perf_counter()
print("per transfer ms", (t1-t0)*10)
```

**判据**：记录 P50/P95，不要只报最好一次；Python 轮询开销要计入。

### 7. 常见故障顺序

1. overlay 名/路径错 → `ip_dict` 为空；
2. `.hwh` 与 `.bit` 不同次构建 → IP 地址错；
3. PL 时钟没起来 → 读全 F；
4. 复位没释放 → 写不进去；
5. DMA `TLAST` 缺失 → `wait()` 卡死；
6. 缓冲区不连续/cache 未同步 → 数据错位；
7. 中断没接 → 用轮询 `wait()` 先跑通，再接中断。

## 已验证效果与验证边界

**已验证（本队等价路径）**：

- 在本队 Zynq-7020 裸机上验证了 AXI-Lite 寄存器读写、176 bit 帧记录的 SEQ/ACK、toggle CDC、环形缓冲；
- 验证了“读 ID → 写 scratch → 读回 → 连续帧”的同一套验收顺序；
- 验证了 cache 不一致会导致 JTAG 读到旧计数器，必须把调试计数写到 AXI GPIO。

**未执行（明确标注）**：

- 本队硬件不是 PYNQ 镜像，`pynq.Overlay`、`allocate`、`axi_dma` 的具体 Python 调用**没有在本队板上执行**；
- 因此本技能不附带“实测吞吐/延迟”数字，只给验收脚本与判据；
- 换到 PYNQ 板时，请先跑第 2–3 步，再跑 DMA；不要把本队的裸机数字当成 PYNQ 数字。

## 失效条件

- **`.bit` 与 `.hwh` 不成对**：overlay 能加载，但 IP 地址/名字错，读写全 F。
- **用 `allocate` 之外的方式分配**：普通 `numpy` 数组不保证物理连续，DMA 会错。
- **忽略 cache**：`sync_to_device`/`invalidate` 漏一步，数据看起来“随机错”。
- **DMA 没有 TLAST**：`wait()` 永久阻塞；先查 stream 源。
- **simple mode 超长**：超过 `BTT` 位宽会截断；分块传。
- **把 Python 轮询当硬实时**：Linux 调度会带来 ms 级抖动；硬实时要在 PL 里做。

## 来源

- 本项目 AXI-Lite 帧记录、CDC、cache 一致性、DMA 方向的设计经验；
- 裸机路径上“读 ID → scratch → 连续帧”的验收顺序；
- 多次“地址错/时钟没起来/读全 F”的排查。

## 边界

本技能不覆盖 PYNQ 镜像制作、设备树、DMA 驱动内核模块和中断注册；它只保证“overlay 能加载、寄存器能读写、DMA 能搬一块已知数据”。换板/换镜像时，先确认 PYNQ 版本与 `.hwh` 兼容。
