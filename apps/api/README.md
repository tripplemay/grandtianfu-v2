# api

v2 API 编排层。API 只负责编排模型版本、任务和权限，不在路由函数中实现几何、渲染或 prompt 规则。

预期边界：

- model revisions
- ingest jobs
- layout proposals and approvals
- render jobs and immutable artifacts
- AI enhancement jobs

