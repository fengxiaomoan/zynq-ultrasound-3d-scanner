# -*- coding: utf-8 -*-
"""Generate the figures used by the design report.

Run from the package root:
    python report/assets/make_figures.py
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "report", "assets")

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150

INK = "#1f2937"
MUTED = "#6b7280"
BLUE = "#2f5d8a"
LBLUE = "#dbe8f3"
GREEN = "#3f7d5a"
LGREEN = "#dcecdf"
ORANGE = "#b5651d"
LORANGE = "#f6e3cf"
RED = "#a33a3a"
GREY = "#f3f4f6"


def box(ax, x, y, w, h, text, fc=LBLUE, ec=BLUE, size=10, bold=False, lw=1.2, radius=0.08):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={radius}",
                       linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size,
            color=INK, fontweight="bold" if bold else "normal", zorder=3, linespacing=1.45)
    return p


def arrow(ax, x1, y1, x2, y2, text="", color=BLUE, style="-|>", ls="-", size=8.5, rad=0.0):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=13,
                        linewidth=1.4, color=color, linestyle=ls, zorder=1,
                        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.16, text, ha="center", va="bottom",
                fontsize=size, color=color, zorder=4,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))


def fig_architecture():
    fig, ax = plt.subplots(figsize=(15.2, 9.4))
    ax.set_xlim(0, 16); ax.set_ylim(0, 10.2); ax.axis("off")

    ax.text(8, 10.0, "超声三维扫描与形态异常检测系统 · 总体架构", ha="center", fontsize=17, fontweight="bold", color=INK)
    ax.text(8, 9.58, "PL 负责确定性采集与定点 DSP；PS 负责帧搬运、网页与轻量算法；PC 负责离线重建与异常比对",
            ha="center", fontsize=10.5, color=MUTED)

    # acoustic front end (left column)
    box(ax, 0.25, 7.05, 3.35, 1.35, "水槽 / 目标\n圆柱 · 圆锥 · 台阶轴\n（1 MHz 水浸）", fc="#eef6f1", ec=GREEN, size=10)
    box(ax, 0.25, 5.0, 1.55, 1.2, "发射换能器\n1 MHz · 8 周期", fc=LORANGE, ec=ORANGE, size=8.6)
    box(ax, 1.9, 5.0, 1.7, 1.2, "接收换能器\n一发一收 · V 形", fc=LORANGE, ec=ORANGE, size=8.6)
    box(ax, 0.25, 1.75, 3.35, 1.0, "AD8331 可变增益\n+ 双路 10 bit ADC\n5 MSPS", fc="#fdf1e7", ec=ORANGE, size=9.3)
    box(ax, 0.25, 0.35, 3.35, 0.75, "TC4420 驱动（接发射换能器）", fc="#fdf1e7", ec=ORANGE, size=9.2)

    # PL
    box(ax, 4.35, 0.2, 4.55, 8.7, "", fc="#f7faff", ec=BLUE, lw=1.8)
    ax.text(6.62, 8.48, "FPGA PL · XC7Z020CLG400-2 @ 50 MHz", ha="center", fontsize=11.5, fontweight="bold", color=BLUE)
    box(ax, 4.62, 7.15, 4.0, 1.0, "采集核 ultrasound_test_core\n8192 拍/帧 · 5 MSPS · OTR/丢帧", size=9)
    box(ax, 4.62, 5.8, 1.88, 1.0, "峰值 DSP\nI/Q → 包络 → 峰值", size=8.8, fc=LGREEN, ec=GREEN)
    box(ax, 6.74, 5.8, 1.88, 1.0, "质心 DSP\n窗内加权质心", size=8.8, fc=LGREEN, ec=GREEN)
    box(ax, 4.62, 4.45, 4.0, 1.0, "双轴步进电机控制\n细分 / 斜坡 / 看门狗", size=9)
    box(ax, 4.62, 3.1, 4.0, 1.0, "位姿锁存\ncapture_start 沿锁存两轴步数", size=9)
    box(ax, 4.62, 1.75, 1.88, 1.0, "姿态融合 F1\nI2C + CORDIC", size=8.8, fc=LGREEN, ec=GREEN)
    box(ax, 6.74, 1.75, 1.88, 1.0, "AXI 寄存器\n176 bit 帧记录", size=8.8, fc=LGREEN, ec=GREEN)
    box(ax, 4.62, 0.55, 4.0, 0.8, "ILA / VIO 调试通道（原始波形与探针）", size=9, fc=GREY, ec=MUTED)

    # PS
    box(ax, 9.35, 0.2, 3.35, 8.7, "", fc="#fbf8f2", ec=ORANGE, lw=1.8)
    ax.text(11.02, 8.48, "PS · ARM Cortex-A9", ha="center", fontsize=11.5, fontweight="bold", color=ORANGE)
    box(ax, 9.6, 7.1, 2.85, 1.05, "帧读取 + ACK\nSEQ 双读防撕裂", size=9)
    box(ax, 9.6, 5.6, 2.85, 1.1, "8192 帧环形缓冲\n≈ 90 s @ 90 fps", size=9)
    box(ax, 9.6, 4.05, 2.85, 1.15, "C 算法\n半径 / 分层 / 残差", size=9, fc=LGREEN, ec=GREEN)
    box(ax, 9.6, 2.5, 2.85, 1.15, "lwIP HTTP\n/state · /api/pose", size=9)
    box(ax, 9.6, 0.95, 2.85, 1.1, "静态页面\nCanvas 三维视图", size=9, fc=GREY, ec=MUTED)

    # PC
    box(ax, 13.15, 0.2, 2.55, 8.7, "", fc="#f7f7fb", ec="#5b5b7a", lw=1.8)
    ax.text(14.42, 8.48, "PC / 浏览器", ha="center", fontsize=11.5, fontweight="bold", color="#4b4b6b")
    box(ax, 13.38, 7.0, 2.1, 1.1, "离线重建\nprofile / mesh", size=9)
    box(ax, 13.38, 5.5, 2.1, 1.1, "异常比对\n残差 + 聚类", size=9, fc=LGREEN, ec=GREEN)
    box(ax, 13.38, 4.0, 2.1, 1.1, "标定 / 质量门\n扫描计划", size=9)
    box(ax, 13.38, 2.5, 2.1, 1.1, "Vivado Tcl\n电机 + 采集编排", size=9, fc=GREY, ec=MUTED)
    box(ax, 13.38, 1.0, 2.1, 1.1, "证据与报告\nmanifest / hash", size=9, fc=GREY, ec=MUTED)

    # sensor input above PL
    box(ax, 4.62, 8.85, 4.0, 0.55, "MPU6050（I2C 400 kHz）→ 姿态融合", fc="#eaf2ee", ec=GREEN, size=9)
    arrow(ax, 7.6, 8.85, 7.6, 8.62, "", color=GREEN, size=8)

    # acoustic / electrical arrows
    arrow(ax, 1.02, 6.2, 1.02, 7.05, "发射", color=ORANGE, size=8)
    arrow(ax, 2.75, 7.05, 2.75, 6.2, "反射", color=GREEN, size=8)
    arrow(ax, 2.75, 5.0, 2.75, 2.75, "回波", color=GREEN, size=8)
    arrow(ax, 3.62, 2.25, 4.55, 2.25, "差分 11 bit", color=ORANGE)
    arrow(ax, 3.62, 0.72, 4.55, 0.72, "tx_burst", color=BLUE)

    # PL-PS: one bidirectional AXI link in the gap
    arrow(ax, 9.12, 1.3, 9.12, 8.2, "", color=BLUE, style="<|-|>")
    ax.text(9.02, 4.75, "AXI4-Lite：帧记录 / 控制 / ACK", rotation=90, ha="center", va="center",
            fontsize=8.5, color=BLUE, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.95))

    # PS-PC
    arrow(ax, 12.72, 3.05, 13.3, 3.05, "以太网")
    arrow(ax, 13.3, 1.55, 12.72, 1.55, "HTTP", color=ORANGE)

    ax.text(8, 0.02, "注：彩色箭头表示数据流向；ILA 与 VIO 是调试通道，不参与正式闭环。",
            ha="center", fontsize=8.5, color=MUTED)
    fig.savefig(os.path.join(OUT, "fig_system_architecture.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_timing():
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14.5, 7.2), gridspec_kw={"height_ratios": [2.1, 1]})

    # panel 1: one frame
    ax1.set_xlim(0, 170); ax1.set_ylim(0, 4.2); ax1.axis("off")
    ax1.text(0, 3.95, "(a) 一帧内部时序：50 MHz 时钟，8192 拍 = 163.84 µs，5 MSPS 下 819 个采样点",
             fontsize=12.5, fontweight="bold", color=INK)

    ax1.add_patch(Rectangle((0, 2.75), 163.84, 0.38, fc=LBLUE, ec=BLUE, lw=1))
    ax1.text(81.9, 2.94, "frame_active：8192 个 50 MHz 时钟", ha="center", va="center", fontsize=10, color=BLUE)
    ax1.add_patch(Rectangle((0, 2.75), 8, 0.38, fc=ORANGE, ec=ORANGE, alpha=0.45))
    ax1.text(4, 3.32, "TX 8 个 1 MHz 周期 = 8 µs", ha="left", fontsize=9.5, color=ORANGE)

    ax1.plot([0, 163.84], [2.1, 2.1], color=MUTED, lw=1.2)
    for t in range(0, 164, 20):
        ax1.plot([t, t], [2.02, 2.18], color=MUTED, lw=1)
        ax1.text(t, 1.86, f"{t}", ha="center", fontsize=8.5, color=MUTED)
    ax1.text(168, 1.86, "µs", fontsize=8.5, color=MUTED)

    # sample ticks
    for t in np.arange(0, 163.84, 5):
        ax1.plot([t, t], [2.55, 2.72], color=BLUE, lw=0.6, alpha=0.55)
    ax1.text(0, 2.24, "ADC 采样：每 10 拍一个点（0.2 µs）", fontsize=9, color=BLUE)

    ax1.add_patch(Rectangle((56, 1.15), 51.8, 0.5, fc=LGREEN, ec=GREEN, lw=1.2))
    ax1.text(81.9, 1.4, "峰值搜索窗：样本 280–539 = 56.0–107.8 µs", ha="center", va="center", fontsize=10, color=GREEN)
    ax1.annotate("", xy=(56, 0.92), xytext=(107.8, 0.92), arrowprops=dict(arrowstyle="<->", color=GREEN, lw=1.2))
    ax1.text(81.9, 0.62, "窗内取 |I|+|Q| 最大值 → 40 bit 锁存（idx × 0.2 µs = 到达时间）",
             ha="center", fontsize=9.5, color=INK)

    ax1.text(0, 0.12, "确定性：TX 起点到首样本由计数器决定，抖动 20 ns；主机触发方案为 1–10 ms 量级。",
             fontsize=9, color=MUTED)

    # panel 2: frame period
    ax2.set_xlim(0, 12); ax2.set_ylim(0, 2.4); ax2.axis("off")
    ax2.text(0, 2.2, "(b) 帧周期：11 ms 配置 → 实测 90.84–91.05 fps；TX 占空比约 0.07%",
             fontsize=12.5, fontweight="bold", color=INK)
    ax2.add_patch(Rectangle((0.2, 0.75), 10.8, 0.62, fc=GREY, ec=MUTED, lw=1))
    ax2.add_patch(Rectangle((0.2, 0.75), 0.16, 0.62, fc=ORANGE, ec=ORANGE))
    ax2.add_patch(Rectangle((0.2, 0.75), 0.42, 0.62, fc=BLUE, ec=BLUE, alpha=0.55))
    ax2.annotate("TX 8 µs + 采集 164 µs", xy=(0.42, 1.37), xytext=(1.7, 1.55),
                 arrowprops=dict(arrowstyle="->", color=BLUE, lw=1), fontsize=9, color=BLUE)
    ax2.text(5.5, 1.06, "帧间隔（空闲 / 电机移动 / 主机处理）", ha="center", va="center", fontsize=9.5, color=MUTED)
    ax2.annotate("", xy=(0.2, 0.55), xytext=(11.0, 0.55), arrowprops=dict(arrowstyle="<->", color=INK, lw=1))
    ax2.text(5.6, 0.27, "11 ms（可配置，硬件下限 10 ms 锁定）", ha="center", fontsize=9.5, color=INK)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_frame_timing.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_optimization():
    fig, axes = plt.subplots(1, 3, figsize=(15.2, 4.6))
    panels = [
        ("单帧回读耗时（ms，对数轴）", ["ILA 上传", "DSP + VIO"], [501, 2.6], ["501", "2.6"], "×193"),
        ("单帧数据量（Byte，对数轴）", ["ILA CSV", "40 bit 字"], [342172, 5], ["342,172", "5"], "×68,434"),
        ("连续帧率（fps）", ["主机逐帧触发", "PL 自主触发"], [2.0, 90.9], ["≈2", "90.9"], "×45"),
    ]
    for ax, (title, labels, vals, texts, gain) in zip(axes, panels):
        y = np.arange(len(vals))[::-1]
        colors = [MUTED, BLUE]
        ax.barh(y, vals, color=colors, height=0.52)
        ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=10)
        ax.set_title(title, fontsize=11.5, color=INK, pad=10)
        if "对数" in title:
            ax.set_xscale("log")
            ax.set_xlim(1, max(vals) * 8)
        else:
            ax.set_xlim(0, max(vals) * 1.35)
        for yi, v, t in zip(y, vals, texts):
            ax.text(v * 1.12 if "对数" in title else v + max(vals) * 0.02, yi, t,
                    va="center", fontsize=10.5, color=INK, fontweight="bold")
        ax.text(0.96, 0.90, gain, transform=ax.transAxes, ha="right", fontsize=15,
                color=GREEN, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=GREEN, lw=0.8, alpha=0.9))
        ax.grid(axis="x", alpha=0.25, linestyle="--")
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    fig.suptitle("把“上传原始波形”换成“板上出结果”后的三项变化（均为同板实测）", fontsize=13.5, y=1.02, color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_optimization.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_resources():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 4.4))
    metrics1 = ["LUT", "FF"]
    m2 = [4788, 7011]
    m3 = [6921, 8214]
    x = np.arange(len(metrics1)); w = 0.34
    ax1.bar(x - w / 2, m2, w, label="M2b（采集 + DSP + PS 通路）", color=MUTED)
    ax1.bar(x + w / 2, m3, w, label="M3（+ 姿态融合）", color=BLUE)
    for i, (a, b) in enumerate(zip(m2, m3)):
        ax1.text(i - w / 2, a + 120, f"{a}", ha="center", fontsize=9)
        ax1.text(i + w / 2, b + 120, f"{b}", ha="center", fontsize=9)
    ax1.set_xticks(x); ax1.set_xticklabels(metrics1)
    ax1.set_title("逻辑资源（Slice）", fontsize=11.5)
    ax1.legend(fontsize=8.5, frameon=False, loc="upper left")
    ax1.set_ylim(0, 9500)
    ax1.grid(axis="y", alpha=0.25, linestyle="--"); ax1.set_axisbelow(True)

    metrics2 = ["BRAM Tile", "DSP48"]
    m2b = [12.5, 14]
    m3b = [12.5, 18]
    x2 = np.arange(len(metrics2))
    ax2.bar(x2 - w / 2, m2b, w, color=MUTED)
    ax2.bar(x2 + w / 2, m3b, w, color=BLUE)
    for i, (a, b) in enumerate(zip(m2b, m3b)):
        ax2.text(i - w / 2, a + 0.35, f"{a:g}", ha="center", fontsize=9)
        ax2.text(i + w / 2, b + 0.35, f"{b}", ha="center", fontsize=9)
    ax2.set_xticks(x2); ax2.set_xticklabels(metrics2)
    ax2.set_title("存储与乘法资源", fontsize=11.5)
    ax2.set_ylim(0, 22)
    ax2.grid(axis="y", alpha=0.25, linestyle="--"); ax2.set_axisbelow(True)

    for ax in (ax1, ax2):
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("全设计资源：M3 相对 M2b 增加 LUT +2133 / FF +1203 / BRAM +0 / DSP +4", fontsize=12.5, y=1.02, color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_resources.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _draw_mesh(ax, d, title):
    st = d["runs"]["std"]
    verts = np.array(st["mesh"]["vertices"], dtype=float)
    faces = np.array(st["mesh"]["faces"], dtype=int)
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    polys = verts[faces]
    z = verts[:, 2]
    norm = plt.Normalize(z.min(), z.max())
    cmap = plt.get_cmap("viridis")
    pc = Poly3DCollection(polys, facecolors=cmap(norm(z[faces].mean(axis=1))),
                          edgecolors=(0, 0, 0, 0.12), linewidths=0.15, alpha=0.96)
    ax.add_collection3d(pc)
    ax.set_xlim(55, 95); ax.set_ylim(80, 120); ax.set_zlim(-9, 3)
    ax.set_box_aspect((40, 40, 12))
    ax.view_init(elev=18, azim=-62)
    ax.set_xlabel("x / mm", fontsize=8); ax.set_ylabel("y / mm", fontsize=8); ax.set_zlabel("z / mm", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=11, pad=2)
    ax.xaxis.pane.set_alpha(0.08); ax.yaxis.pane.set_alpha(0.08); ax.zaxis.pane.set_alpha(0.08)


def fig_real_model():
    p3 = os.path.join(ROOT, "data", "real", "_m2b_3layer_signed.json")
    p6 = os.path.join(ROOT, "data", "real", "_m2b_6layer.json")
    d3 = json.load(open(p3, encoding="utf-8"))
    d6 = json.load(open(p6, encoding="utf-8"))
    fig = plt.figure(figsize=(12.4, 5.2))
    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    _draw_mesh(ax1, d3, "实测三层模型（z = −2/0/+2 mm）\n72 格 · 71 有效 · 144 顶点 / 192 三角面")
    _draw_mesh(ax2, d6, "实测六层模型（z = −8…+2 mm）\n141 格 · 131 有效 · 288 顶点 / 480 三角面")
    fig.suptitle("板上真实扫描得到的三维侧壁（半径约 14.0 mm，开放网格，未封端盖）", fontsize=12.5, y=0.99, color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_real_model.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig_architecture()
    fig_timing()
    fig_optimization()
    fig_resources()
    fig_real_model()
    print("FIGURES_OK", OUT)
