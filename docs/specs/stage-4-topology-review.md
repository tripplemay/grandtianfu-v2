# 阶段 4C2：门窗、连通性与 merge 拓扑校核

状态：building。4C1 已独立验收通过；本阶段完成后再次暂停，不能直接进入阶段 5。

## 目标

把人工矩形描图草稿从“只有房间/墙体”推进到可审核的拓扑草稿。所有拓扑仍由用户
明确选择，不从墙体相邻关系或图片纹理猜测。

## 输入与输出

- 输入为 `manual_trace_requires_topology_review` 的 ingest draft；父 ingest 和 trace 参数不可变。
- 输出为新的 revision/derived draft，保存完整 SpatialModel、父 revision/hash、操作者动作和算法版本。
- 不修改 source、父模型或历史 revision；重复同一拓扑请求幂等。

## 可审核对象

- 门/窗/通行开口：选择 host wall、offset、width、height、bottom_z、kind。
- 房间 merge：选择至少两个房间组成 merge group；只允许存在共享边界或用户明确声明的通行开口。
- 房间连通性：每个 merge group 的邻接边界必须由实际共享墙解释；opening 只能挂在该共享墙上，且其沿墙跨度必须与两房间的共同边界区间相交。当前模型尚无 `from_room_id/to_room_id`，因此不允许用 opening 凭空连接完全分离的房间；孤立房间必须保持无 group。

## 硬校验

- 开口必须完全落在 host wall 内，尺寸和高度为正，不能互相重叠；窗台高度不能低于 0。
- merge group 至少两个房间，房间只能属于一个 group；组内每对相邻房间必须有共享墙或审核通过的 opening。
- 不允许引用未知 room/wall，不允许布尔/NaN/越界/额外 JSON 字段。
- 拓扑未完成、存在未分类候选或 unresolved blocker 时，确认和 3D 继续阻断。

## 阶段门

- UI 可从人工描图草稿选择墙体、添加/编辑/删除门窗、选择 merge 组并显示邻接解释。
- API 对非法开口、重叠开口、无效 merge、陈旧 hash 和父工件篡改返回结构化错误且不发布半成品。
- 相同输入 hash 稳定、重复提交幂等；source/parent provenance 完整。
- 独立 evaluator 在桌面/移动端、合成相邻/T 形/分离房间及真实宣传页上验收。

## 暂不解除

即使拓扑校核通过，本阶段先保留 `manual_trace_requires_topology_review`，直到 evaluator
确认所有对象均被复核并且与 2D/3D 轮廓一致；本阶段不做家具布局和照片级生成。
