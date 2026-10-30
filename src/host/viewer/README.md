# 姿态网页：MPU6050 驱动三维模型

纯 WebGL1 + Python 标准库，不依赖 CDN / npm。默认回放 `sim/vectors/demo_pose.csv`；
没有姿态文件时，服务器会合成一段平滑运动（页面角标显示“服务器演示”），所以**不上板也能看**。

## 1. 跑起来

```powershell
# 在包根目录
python src\host\viewer\server.py --port 8780
# 打开 http://127.0.0.1:8780/
```

回放一段自造姿态（不需要板子）：

```powershell
python src\host\viewer\make_demo_pose.py --out data\demo\demo_pose.csv --seconds 60
python src\host\viewer\server.py --port 8780 --pose data\demo\demo_pose.csv
```

接到 FPGA 之后，把 `--pose` 指向 Tcl 正在写的 `pose.csv` 即可，页面不用改。

## 2. 页面能做什么

- 左栏：ROLL / PITCH / YAW 实时数值、数据源、样本年龄、FPS、模型来源与点数/面数；
- 右栏：可旋转的三维模型（拖拽旋转视角、滚轮缩放、双击复位），带地面网格与 XYZ 轴；
- **归零（Z）**：把当前姿态记为单位阵，之后只显示相对转动；
- **复位视角（R）**、**线框（W）**、**暂停（Space）**；
- 模型下拉框：四个演示模型，来自 `data/demo/models/<shape>.ply`；
- 页面角标会写“演示模型”，不冒充实测。

## 3. 数据契约

`pose.csv`，一行一个样本，表头可省（省掉时按位置解析）：

```text
tick_ms,roll,pitch,yaw,seq,valid
1793020146693,0.00,15.15,0.00,0,1
```

- `tick_ms`：50 MHz 时间戳折算成毫秒（epoch 或任意单调基准都行）；
- `roll/pitch/yaw`：度，右手系，Y-X-Z 顺序（与 three.js `Euler('YXZ')` 一致）；
- `seq`：样本序号，用来看丢样；
- `valid`：0/1。

服务器只读最后一行，所以 Tcl 侧可以一直 append，不需要轮询整文件。

## 4. HTTP 接口

| 路径 | 返回 |
|---|---|
| `/` | 页面 |
| `/api/models` | 可用模型列表 |
| `/api/model?name=cylinder` | `{positions, normals, indices, counts, provenance, limits, radius}` |
| `/api/pose` | `{mode, roll, pitch, yaw, seq, valid, age_ms, source}` |
| `/api/health` | 自检 |

坐标转换在服务器里做：扫描系 `(x, y, z_up)` → 显示系 `(x, z_up, -y)`，并按包围盒中心/最大边归一化到约 2 个单位。

## 5. 已做的验证

```powershell
node src\host\viewer\tests\test_math3d.js     # PASS 21 checks
node src\host\viewer\tests\test_dom.js        # PASS 6 checks
python src\host\viewer\tests\test_server.py   # PASS 35 checks
```

- 四元数：单位元、Y/X/Z 单轴 90° 方向、YXZ 组合、slerp 端点/中点、归零管线；
- 矩阵：列正交、行列式 +1、与四元数旋转一致、lookAt、透视近远平面；
- DOM 契约：`app.js` 里用到的每个 `$("id")` 都必须在 `index.html` 里存在；
- PLY：四个演示模型的顶点/索引数量、索引范围、法线单位化、居中、半径；
- 姿态 CSV：缺文件→演示、带表头、无表头、最后一行生效。

## 6. 与 F1 硬件的接法

```text
MPU6050 ──I2C──> PL(i2c_master + pose_fusion) ──VIO 128 bit──> Tcl 读回
                                                              │
                                                     append pose.csv
                                                              │
                                             server.py /api/pose
                                                              │
                                                     WebGL 模型旋转
```

Tcl 侧每 20–50 ms 读一次探针、解码 roll/pitch/yaw/tick/seq、追加一行；VIO 单次回读约 2.5 ms，
页面 20 Hz 显示足够。**不要**把它写成“1 kHz 到网页”。

## 7. 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 静态页 + PLY 解析 + 姿态读取，只读、无缓存落盘 |
| `index.html` / `app.js` / `math3d.js` | 页面、交互、数学 |
| `make_demo_pose.py` | 生成回放 CSV |
| `tests/test_math3d.js` | 数学单元测试（Node） |
| `tests/test_dom.js` | DOM 契约测试（Node） |
| `tests/test_server.py` | 模型/姿态单元测试（Python） |

## 8. 边界

- 演示模式是**合成运动**，不是实测；页面角标已注明；
- 模型全部是 `synthetic` 演示模型，实测模型不在本代码包内；
- 当前没有“姿态回写 FPGA”或“扫描点姿态快照”，属于下一步 RTL；
- 页面不做数据判定，只做姿态驱动显示。
