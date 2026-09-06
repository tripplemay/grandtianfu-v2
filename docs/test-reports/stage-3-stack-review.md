# 阶段 3 栈与风险独立评估

日期：2026-09-06  
范围：`packages/scene3d/README.md`、`SpatialModel v2` 规格、阶段路线与当前 `spatial_core` 实现。当前 `scene3d` 仍是占位包；本报告不修改产品代码、不启动生产服务。

## 结论

建议先做一个**窄范围、纯 CPU、软件光栅化 spike**：只支持 `orthogonal_v1` 的墙/地/顶、开口、参数化家具和一个显式 perspective camera，使用固定三角形/深度排序、无纹理和无随机采样，输出 color、depth、normal、uint32 instance mask 与 manifest。实现可用 NumPy 做数组和 z-buffer、Pillow 做最终 RGBA 编码；若需要减少依赖，可将图像编码单独替换为标准库/固定二进制格式。

这条路线最容易先证明阶段门要求的“2D -> 3D -> 相机投影无漂移”和逐像素确定性。它不是长期通用渲染器：真实网格、纹理、复杂材质、抗锯齿和照片级效果应留给后续渲染服务。

## 渲染器选型

| 方案 | 适合点 | 主要风险 | 阶段 3 结论 |
| --- | --- | --- | --- |
| NumPy/Pillow 窄范围软件光栅器 | 依赖小，CPU 可控，z-buffer/depth/normal/mask 可完全定义，像素输出容易做到字节级稳定 | 需要自行实现三角形光栅化、裁剪、透视插值和几何构建；不能冒充完整 DCC | **推荐作为 spike** |
| Blender headless CPU | 几何、相机、材质、深度/法线/对象 ID 能力成熟 | 二进制体积和启动时间大；版本、色彩管理、线程、平台构建及渲染设置会影响像素；worker 隔离和资产导入复杂 | 不作为首个闭环；若采用，必须单独 ADR、固定容器 digest 和输出回归基线 |
| `trimesh` + `pyrender`/OpenGL | 可复用 mesh 数据结构和相机数学 | 依赖 EGL/GLX/Mesa 等系统栈，所谓 headless 仍可能走软件 GPU；驱动和平台差异会破坏确定性 | 不作为首个 CI 基线 |
| VTK/Open3D/其他通用 3D 框架 | 功能丰富 | 体积、原生依赖、渲染后端和输出格式控制面大，超出本阶段垂直切片 | 暂不选 |

无论选型，renderer 不应嵌入 FastAPI 进程；README 已正确要求独立 render worker/service。worker 的 Python、NumPy/Pillow（或 Blender/Mesa）版本必须锁定，必要时固定单线程环境变量，且将 renderer 版本写入 manifest。

## 必须先冻结的输入边界

1. 只允许 `status=confirmed` 或 `locked` 的 revision 进入精确渲染；`draft` 应明确拒绝并返回可分类错误。
2. 每次任务提交 `model_id`、`revision`、canonical model hash，以及一个明确的 camera ID/hash；当前模型允许 `cameras=[]`，因此“未指定 camera”不能静默选默认值。
3. 当前模型代码使用家具字段 `id`，规格文字使用 `instance_id`。在 mask/manifest 前必须统一命名或定义不可变映射，否则无法满足“同一 instance ID 可回溯”。
4. `asset_ref` 只有 kind/ref，没有资产解析器、资产 hash 或离线资源包契约。worker 不能联网或静默生成替代几何；缺失/不匹配资产应硬失败，并在 manifest/错误中记录 ref 与 hash。
5. 相机验证需补充：图像宽高上限、有限的 near/far、position 不得等于 look_at、up 向量非零且不与视线共线、视场角/投影参数范围。当前全局 JSON 上限是 `1e9`，不能直接作为图像分配上限，否则单个输入可触发 OOM。
6. 阶段 0/验收文档把门洞、通道净空列为硬失败，但当前 `spatial_core` 只做房间内家具边界和家具间碰撞。3D worker 必须调用更强的 preflight validator，或明确阶段 3 暂不接收此类模型；不能仅渲染后标 warning。

## 输出契约建议

### Color

- 固定宽高、RGBA、sRGB 转换和背景颜色；禁用平台相关色彩管理。
- 首个 spike 禁止随机采样和非确定性抗锯齿。若使用 supersampling，固定样本位置、顺序和 downsample 算法。
- 输出写入临时目录，所有通道成功且 hash 完成后再原子发布，避免留下可被当成成功结果的半成品。

### Depth

- 定义为相机坐标系中的正向距离（或明确 z-buffer 逆变换），单位必须固定为 mm 或 m，不能让消费者猜测。
- 推荐 float32 无损数组格式，另存 `valid/background` 语义；背景使用固定 `+inf` 或明确 far sentinel，并在 manifest 写明。
- 固定 pixel-center、near/far、深度比较和同深度 tie-break 规则。物体排序不能依赖 Python dict/集合遍历顺序。

### Normal

- 明确输出在 world、camera 还是 view space；推荐 camera-space unit normal，背景为 `[0,0,0]` 且由 valid mask 区分。
- 保存 float32 或无损编码，避免 8-bit 映射导致几何验收无法复核。
- 法线必须由面朝向和相机可见性规则决定；共享墙/开口边界的法线和背面剔除策略要固定。

### Instance mask

- 使用 uint32 label，`0` 固定为背景；不要使用依赖调色板的 RGB 颜色作为身份。
- label 分配按稳定 ID 的排序规则生成，并在 manifest 保存 `label -> object_type/object_id`。至少覆盖每个家具实例；墙、地、顶和开口是否入 mask 也要冻结。
- 遮挡时采用与 color/depth 同一 z-buffer 和 tie-break，避免 mask 与 color 的可见物体不一致。
- 验收用渲染 mask 与独立期望投影做 IoU，阈值按规格不低于 `0.95`；同时检查每个输入家具 ID 恰好有可回溯 label，缺失或意外合并为硬失败。

### Manifest

manifest 至少应包含：`model_id`、`model_revision`、`model_hash`、camera ID/hash 和规范化参数、renderer name/version、代码/容器版本、资产 ref/hash、输出尺寸/格式/坐标系、near/far、background/AA 设置、每个实例的 mask label、各 artifact hash、任务状态和错误码。时间戳可作为观测元数据，但不能进入决定性 artifact hash。

## 坐标与投影验收

建立不依赖图像观感的 golden fixture：已确认阶段 2 模型中的墙、共享 merge 边界、开口和至少两种家具旋转。对每个墙角、房间角、家具 footprint 角和开口端点，计算同一 mm 世界点经过 renderer view/projection/viewport 的像素坐标；重复渲染的投影误差目标不超过 `0.5px`，序列化/反序列化坐标误差为 `0mm`。

必须固定并测试：X 向东、Y 向南、Z 向上；家具 x/y 是旋转后 footprint 最小坐标、90 度交换 width/depth；墙厚围绕中心线分配；像素中心和 y 轴方向；透视相机矩阵；单位转换。禁止把 SVG/2D AABB 的显示结果直接当作 3D 真值。

## 确定性测试矩阵

- 同一进程连续运行两次：color/depth/normal/mask 字节 hash 全相同。
- 新进程运行两次：结果和 manifest hash 全相同。
- 重新加载同一 JSON（包括 key 顺序不同但 canonical hash 相同的等价 JSON）：结果相同。
- 固定 CPU worker 镜像在 CI 与本地重复运行；记录 Python、依赖、CPU 线程数和 renderer 版本。
- 改动一个坐标/尺寸/相机参数：至少对应 artifact hash 改变，且只影响预期投影/遮挡区域。
- 并发 N 个 worker：每任务隔离临时目录和输出，不能互相覆盖；达到像素/三角形/资产/内存/超时上限时返回明确失败，不产生成功 manifest。

## 资源、性能和失败风险

- 先做资源预算：最大像素数、对象/三角形数、资产字节数、深度/normal/mask 数组峰值内存。宽高不能只受 `1e9` JSON 边界保护。
- 测试冷启动、warm worker、单任务 P50/P95、并发吞吐、RSS 峰值和超时；阶段 0 的“CPU worker P95/内存预算”仍需 spike 后用实测数值冻结 ADR，当前没有可宣称的预算。
- Pillow/NumPy 的版本升级、BLAS/OpenMP 多线程、浮点 FMA/编译器差异、PNG 压缩实现和 Blender 色彩管理都是 determinism 风险，应锁版本并把输出格式参数纳入 manifest。
- 任何几何/资产/相机/编码失败都必须以结构化错误结束；不允许用默认相机、默认材质、空 mask 或“最佳近似”冒充成功。

## 阶段 3 阶段门前的最小交付清单

1. 一份选型 ADR：renderer、Python/原生依赖、容器或锁文件、CPU 线程策略和预算。
2. 一个单房间 `orthogonal_v1` golden fixture，包含墙/地/顶、开口、旋转家具、相机和稳定资产映射。
3. 可独立运行的 worker contract（输入 revision/hash，输出 atomic artifacts + manifest，结构化失败）。
4. color/depth/normal/uint32 mask 的格式与坐标系文档，以及 label 映射规则。
5. 2D->3D->camera 投影误差、重复运行 hash、mask IoU、越界/缺资产/坏 camera/超预算负例测试。
6. CPU P95、RSS、并发和超时实测记录；未达到预算或出现非确定性时，按路线停止进入 AI/照片增强阶段。

## 风险结论

当前没有可验收的 `scene3d` 实现，因此不能把阶段 3 标记为通过，也不能在没有上述输入/输出契约时接入 AI。优先完成窄范围 CPU 软件光栅器和 golden/确定性测试，再以实测结果决定是否引入 Blender 或其他通用后端。
