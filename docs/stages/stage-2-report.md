# 阶段 2：2D 编辑闭环

状态：本地实现、自动测试与独立复验通过，等待用户确认。未进入阶段 3。

## 交付

- React/TypeScript/SVG 工作台：从同一 SpatialModel 展示房间、merge 分组、墙厚、开口与参数家具。
- 家具毫米数值编辑、90 度朝向、拖动、添加/删除；撤销、重做和取消输入。
- 墙厚/墙顶标高、开口宿主/偏移/宽高；矩形房间名称及安全宽高编辑，同步边界墙但不移动家具。
- 后端几何校验、普通保存形成 draft、显式人工确认形成 confirmed。
- SQLite 不可变 revision、事务 CAS、读取 hash 复验；历史只读，恢复追加新版本。
- 未保存离开确认、数值错误状态、并发保存冲突保留本地编辑；JSON 导出只导出已保存版本。
- 版本锁定、Python/前端依赖锁文件、本地运行文档和不含部署的 GitHub Actions CI。

## 验证

本地环境：Python 3.12.13、Node 25.7.0、Chromium 151。CI 使用 Python 3.12 / Node 22。

| 验证 | 结果 |
| --- | --- |
| `uv run pytest -q` | 54 passed；2 条上游 TestClient/AnyIO 弃用警告 |
| `npm --prefix apps/web test` | 17 passed |
| `npm --prefix apps/web run build` | TypeScript 与 Vite 构建通过 |
| `uv run pytest tests/e2e -q` | 8 passed |
| `uv run ruff check apps/api tests/e2e` | 通过 |
| `npm --prefix apps/web ci` | 通过；审计未报告依赖漏洞 |
| `git diff --check` | 通过 |

浏览器覆盖：小数坐标与尺寸保存/刷新、历史恢复不覆盖、缩放后拖动、连续平移、撤销/重做、无效输入拒绝、未保存导航取消、并发冲突、共享墙锁定、房间宽度/开口编辑与确认、家具添加/删除、数值 Escape 取消，以及 1440x960 / 390x844 / 360x640 布局。

每个浏览器用例使用独立临时 SQLite 与 loopback 端口，不修改工作台数据库。截图位于忽略目录 `artifacts/e2e/stage-2-*.png`。内嵌浏览器运行时未提供可用实例，本次使用独立 Playwright Chromium 完成验收。

独立复核过程及结论见 `docs/test-reports/stage-2-independent-review.md`，保留首轮发现与复验轨迹。

## 几何契约

- 数值输入不从像素反算；拖动使用 SVG CTM 逆变换并显式量化至 0.01 mm。
- 平移使用手势起点的固定 CTM，缩放/适配只改变 viewBox，不写入模型。
- 家具 x/y 仍是旋转后 footprint 的最小角，90/270 度交换宽深；本阶段未偷偷改为中心点坐标。
- 不做坐标自动纠正。越界/碰撞在编辑状态显示错误，禁止保存与确认。
- 服务拒绝空 rooms/walls、非有限数和绝对值超过 1e9 的数字。
- 墙段要求覆盖房间各侧，允许共享墙超出某个成员房间的边界。

## 限制

- 仅 loopback 本地开发验收，无认证、权限、生产发布或旧资产迁移。
- 房间原点及涉及共享墙的尺寸只读；不支持拆墙、自由绘墙或创建 merge 分组。
- merge 连通性、房间重叠、家具与墙厚碰撞、三维净空、贴墙和门洞通行仍需后续工程规则，当前校验通过不等于完整工程验收。
- 位图/PDF 识别、CAD 导出、3D、CPU worker、布局求解与 AI 均未实现。
- 阶段 3 开始前须明确平面 Y 方向与右手 3D 坐标映射；本次只证明 2D 往返，不宣称 3D 投影一致。

## 下一阶段

收到用户确认后才开始阶段 3：手工确认模型到 CPU 3D 垂直切片，验证墙/地/顶/开口、参数家具、相机及 color/depth/normal/instance mask，不先接入 AI 或识别。
