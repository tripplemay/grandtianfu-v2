# 2D 工作台

React + TypeScript + Vite，SVG 完全由 SpatialModel 派生，不把像素坐标保存回事实源。

```bash
npm ci
npm run dev
npm test
npm run build
```

开发模式使用 `http://127.0.0.1:5176`，`/api` 代理到本地 `8026`；API 启动命令见仓库 README。构建结果由 API 同源服务，不需要开发服务器。

家具 x/y 沿用阶段 1 旋转后 footprint 最小角约定。数值输入不舍入；鼠标/触摸拖动显式量化至 0.01 mm。视口平移、缩放与适配不进入撤销历史，不修改模型。房间尺寸变化仅支持不涉及共享墙的矩形边界事务，不移动家具或重排门窗。

历史版本只读。恢复历史追加 draft，人工确认追加 confirmed；任何保存均携带最新 revision/hash，冲突时保留本地编辑。页面不在 localStorage 保存另一个事实源。

画布支持拖动和平移，属性数值及图层操作可用键盘完成。移动端用图层/平面/属性三个工作区域切换。
