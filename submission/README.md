# 提交材料

本目录存放提交页需要的成品文件，源码、仿真、证据与报告在主仓库对应目录。

| 材料 | 文件 | 说明 |
|---|---|---|
| 技术文档 | `technical_document.pdf` | 16 页，2.1 MB，按官方模板；与 [`report/export/technical_document.pdf`](../report/export/technical_document.pdf) 同一份 |
| 设计报告（可选） | `design_report_optional.pdf` | 22 页，1.7 MB；非提交页必填项 |
| 作品全貌图 | `board_full_view.jpg` | 装置正面全貌 |
| 开发板照片 | `board_photos/` | 正面、俯视、电路、接线共 4 张 |
| 三个关键词 | `keywords.txt` | 超声三维重建 / FPGA 板上 DSP / 手背姿态交互 |
| GitHub 链接 | <https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner> | 源码、仿真、构建报告、证据与文档 |

## 全部代码压缩包

提交页的“全部代码”为 RAR（≤200 MB），归档根目录是 `ultrasound_3d_scanner/`，解压后直接看到：

```
README.md  src/  sim/  build/  board/  data/  skill/  report/
```

压缩包包含代码、脚本、测试数据、构建报告、位流、XSA、ELF、技能包与报告；不包含 `data/demo/*.mp4`（约 58 MB，见 [Release `v1.0-assets`](https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner/releases/tag/v1.0-assets)）与 `report/export/*.docx`（可由 Markdown 重新生成）。

## 三个关键词

```
超声三维重建
FPGA 板上 DSP
手背姿态交互
```

## 其他提交项

演示视频（MP4/H.264，≤3 分钟）与签字盖章的参赛作品承诺及使用授权书不在本仓库，按提交页要求单独上传。技术文档、视频与图片中不含学校、指导教师与姓名信息。
