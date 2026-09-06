# ADR 0003：阶段 3 坐标与 CPU 渲染契约

## 状态

Accepted，2026-09-06。具体 renderer 选型仍需通过阶段 3 spike 单独决策。

## 背景

阶段 2 已证明 2D 编辑器使用毫米坐标、SVG Y 向下和家具旋转后最小角约定可以保存与重载。阶段 3 必须把这套平面事实展开到 3D 和像素通道，避免 renderer 采用另一套轴向后产生家具镜像、上下颠倒或相机漂移。

## 决策

1. Canonical 世界坐标固定为右手系 `X east / Y south / Z up`，原点和单位不变。
2. 2D 平面直接使用 `(x,y)`，SVG 向下的 Y 与世界向南的 Y 同号；不会在 2D→3D 中对 Y 取负。
3. 相机在同一世界坐标系表达，使用显式 perspective 投影和固定 render profile；不得自动居中、改 FOV 或猜测内参。
4. 墙、地、顶、开口和家具全部由 `SpatialModel` 确定性派生；家具 `x/y` 仍表示旋转后 footprint 最小角。
5. 输出原始通道为 RGBA color、float32 depth、float32 world normal、uint32 instance mask，所有产物通过 model/camera/asset/profile hash 回溯。
6. 渲染在独立 CPU worker 执行，默认单任务单进程；AI、位图、布局求解不属于阶段 3。

## 像素坐标说明

世界点先投影到相机右/上/前基底，再使用 `u=cx+fx*x/z`、`v=cy-fy*y/z` 输出左上角原点的像素坐标。`v` 的负号只负责把“相机向上为正”转换为“图像向下为正”，不能被误解为平面 Y 轴反向。

## 后果

- renderer adapter 必须显式声明内部轴向、手性和单位；
- 任何轴变换都要有 round-trip 测试和 manifest 记录；
- 后续 AI 的 depth/normal/mask 必须遵循本 ADR 的通道语义；
- 若候选 renderer 不能保持确定性或 CPU 预算，必须重新提交 ADR，不得在实现中放宽阶段门。

## 不在本 ADR 内

- Blender、Three.js、Unreal、Cycles、Eevee 或其他具体 renderer 的最终选择；
- 真实家具模型和纹理供应链；
- 位图识别、照片相机估计和 AI 增强策略。
