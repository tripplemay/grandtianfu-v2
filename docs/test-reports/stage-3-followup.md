# 阶段 3 复核整改记录

独立复核初版发现的三个 P1 已在 `06b85ca` 后修复并回归验证：

- API cache hit 现在逐项校验 manifest 中四类 artifact 的存在性和 SHA-256；篡改 `color.png` 会触发重渲染。新增 API 回归测试覆盖该路径。
- 投影将 `50°` 按冻结契约解释为垂直 FOV，并由画布宽高推导水平 FOV。
- 家具 `asset_ref.kind` 非 `parametric` 时硬失败，不再静默按尺寸生成盒体；新增渲染器测试覆盖。

整改后验证：`uv run pytest -q` 为 72 passed；`uv run ruff check apps/api apps/api/tests packages/scene3d packages/scene3d/tests` 通过；前端 Vitest 17 passed，TypeScript/Vite build 通过。独立复核原报告保留作为问题发现记录，阶段门等待用户确认。
