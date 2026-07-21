# Backlog after v0.9.2 MVP

## v0.10 分析语义

- SheetBench 104：英文月份、年份与季度复合增长率。
- SheetBench 101：相同序号跨父级分组的完整作用域。
- SheetBench 126：重复 `Direct Cost` 列族的口径消歧。
- SheetBench 2292：明细与 `of which` 非加总关系。
- SheetBench 1135：重复指标列、明细/Total 行角色和候选证据排序。
- SheetBench 515：section 上下文与精确汇总行匹配。
- 结果表数值格式：浮点尾差、单位与小数位统一。
- 生成 CSV 的原始数值格式：部分派生差值会保留 Python 浮点精度尾差；当前 UI 预览已格式化，后续在通用导出层增加列级格式策略。

## Robustness

- WebSocket 延长自动重连窗口，或在服务恢复后持续低频重试。
- 为 Pi sidecar 增加操作系统级 workspace 写入隔离；当前 v0.9 已隔离 context、限制工具并阻断 Git。
- 为 typed tool service 提供原生 Pi custom tool，替换通用 bash bridge。
- workspace TTL/GC、磁盘空间预警、跨进程任务恢复。
- follow-up 运行会对同路径产物重复登记 SQLite artifact 记录；UI 已按路径去重，后续在持久化层改为幂等登记。

## 生产化

- 鉴权、多租户、数据留存和审计。
- Docker/Kubernetes、监控告警和结构化日志（CI 已落地：GitHub Actions 跑 pytest / 前端构建 / 泄漏检查；CD 仍在此列）。
- 安全审计、prompt injection 测试、沙箱逃逸测试。
- 性能/负载测试、配额与计费。
