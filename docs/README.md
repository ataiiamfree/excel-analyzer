# ChatExcel Docs

当前文件夹是 ChatExcel 的架构与实施文档。以这两个文件为准：

- `Design.md`：当前架构设计，描述个人/内网单用户 robust 版本的目标架构。
- `Implementation-Plan.md`：按阶段落地的实施计划和验收点。

`ChatExcel技术方案讨论记录.md` 是历史方案讨论归档，用来保留从 ReAct 转向 Code-First / Adaptive Plan-Execute 的推理过程，不作为当前实现的唯一依据。

## 当前配置口径

- 默认 LLM provider：DeepSeek API
- 默认 base URL：`https://api.deepseek.com`
- 默认 model：`deepseek-v4-pro`
- API key：只通过 `DEEPSEEK_API_KEY` 环境变量注入，禁止写进文档、代码、prompt 日志或任务产物。

## 当前架构口径

- 不做企业级鉴权、多租户、审计、分布式队列。
- 保留 raw workbook，不原地改上传文件。
- 通过 `WorkbookIngestor` 识别 workbook/sheet/table 结构。
- 通过 `ExcelPreprocessor` 输出 normalized tables。
- 通过 `TaskContext + Artifact Manifest` 管理步骤间信息。
- 通过 `ResultChecker` 校验“代码跑通但结果不对”的风险。
