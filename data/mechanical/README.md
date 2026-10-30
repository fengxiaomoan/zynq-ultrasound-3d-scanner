# 机械设计输出

本目录是 3D 打印支架/滑台/探头夹具的**设计输出与验证记录**，用于技术文档的“机械设计”一节和 `skill/08_mechanical_design_to_print`。

| 文件 | 内容 |
|---|---|
| `assembly.png` | 装配预览 |
| `lift_parts.png` | 升降模块零件预览 |
| `probe_parts.png` | 探头夹具零件预览 |
| `print_list.csv` | 打印清单（件号、名称、数量、尺寸、体积、是否必打） |
| `parts_manifest.json` | 逐件元数据（模块、备注、尺寸、水密） |
| `verification.json` | CAD 验证：23 实体、22 种打印件、26 件、6 个 plate、全部 STL 水密、无碰撞 |
| `assembly_notes.md` | 打印与装配说明（原 `先读我_打印与装配说明.md`） |

## 验证边界

- `verification.json` 只证明 **CAD 拓扑/名义中性位间隙**；
- 没有在包内重新做切片、打印、负载、声学、全行程、漏水/防水验证；
- 电机轴偏移/扁位、水箱壁厚、运动假设仍需按实物复核；
- 实物装配照片见 `report/assets/photo_rig_front.jpg`、`photo_rig_top.jpg`。

## 原始工程

完整 STEP/STL/3MF 约 10 MB，未纳入仓库。本目录保留预览、清单、装配说明和验证 JSON；重新切片时以原始设计文件的 STEP/STL 为准。
