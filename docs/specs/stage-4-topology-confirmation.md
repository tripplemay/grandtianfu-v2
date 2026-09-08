# 阶段 4C3：人工拓扑确认到 CPU 3D

状态：独立复验通过，等待用户确认。4C2 用户已确认。本检查点仍属于阶段 4，不启动家具求解或照片级增强。

## 契约

- 复用 `POST /api/ingests/{id}/confirm`；原始描图不能确认，只有可重放的 `manual_topology` 派生工件可申请解除 `manual_trace_requires_topology_review`。
- 服务端验证父 trace/source/model hash 和拓扑 recipe，重放输出必须等于原始 topology 工件。确认时当前房间、墙、开口及 merge 几何必须与该工件一致；相机设置允许独立保存。
- 房间类型不得为 unknown，开口类型限定 door/window/passage。审核集合须精确覆盖房间、墙、开口及 merge 组；增加 `topology` 和 `coverage` 两项明确人工声明。
- coverage 仅声明所描绘区域完整，不代表整张宣传页或全屋被自动重建；确认记录写明 `scope=traced_regions`。
- 只允许解除上述一个已知 blocker。其他 hard_blockers/blockers、缺失证据、未分类对象、陈旧 revision/hash、父工件篡改都阻断；失败不追加 revision。
- 原始 ingest/source、历史 revision 和置信度不可改写。在服务端生成的 review 中保存 resolved_blocker_codes、拓扑工件 hash、父 hash、当前 draft hash、审阅者、检查项与时间。
- 确认产生新的 confirmed revision；保存后撤销 review 并恢复 draft，不能伪造 review 绕过门禁。经过确认且设置显式相机的 revision 可进入现有 CPU 3D。

## 阶段门

- 合成多房间 trace -> topology -> 全量审核 -> confirmed -> CPU 3D，source/hash 和几何无漂移。
- 反例覆盖没有拓扑、额外 blocker、未分类房间、遗漏 merge 对象、缺失/伪造检查项、修改几何后沿用旧证据、父工件篡改和并发 CAS。
- 桌面及 390px 浏览器完成确认流程，未确认不渲染、确认后允许渲染，生成图非空；人工 scope 清晰。
- 独立 evaluator 用 fresh context 运行验收并原样落盘；完成后等待用户确认。
