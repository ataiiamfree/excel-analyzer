# CLAUDE.md - Excel 智能分析 Agent 项目规则

## Git 提交规范
- 每次有改动后都需要 Git 提交
- 提交信息使用中文，简明扼要

## 文档同步规范
- 代码改动必须同步更新 `docs/` 下对应文档
- 新增模块在 `docs/Design.md` 中补充设计说明
- 文档与代码不一致视为未完成的改动

## 代码规范
- Python 3.10+，使用 type hints
- 异步函数用 `async/await`
- 数据类用 `@dataclass` 或 `pydantic.BaseModel`
- LLM 调用必须经过 `app/llm/client.py` 统一入口
- API key 等敏感信息只通过环境变量注入，不能写进代码或文档

## 架构约束
- LLM 每次调用独立，不累积上下文
- 数据在沙箱中流转，LLM 只看摘要
- 原始文件不可变，所有产物写入 normalized/ 或 output/
- 步骤间通过 TaskContext + Artifact Manifest 传递信息

## 测试
- 测试放在 `tests/` 目录
- 用 `pytest` 运行：`make test`
