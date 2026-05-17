# Excel 智能分析 Agent

上传 Excel 文件，用自然语言提出分析需求，自动生成 Python 代码执行分析并输出报告。

## 架构

采用 **Adaptive Plan-Execute** 编排：先粗略规划全局，每步执行后根据实际结果动态细化下一步。每次 LLM 调用独立，不累积上下文。

详见 [Design.md](docs/Design.md) 和 [Implementation-Plan.md](docs/Implementation-Plan.md)。

## 当前实现状态

当前代码处在核心模块落地阶段，已开始实现：

- DeepSeek 配置入口
- Workspace / state / artifact manifest
- ExecutionPlan 调度状态机
- TaskContext 与 PromptAssembler
- WorkbookIngestor / ExcelPreprocessor / Profiler
- PythonSandbox / ResultChecker

`app/main.py` 和交互式前端属于 Phase 8，尚未实现。因此现在先以模块测试和 smoke test 为主，暂时不要用 `make run` 作为验收标准。

## 快速开始（开发）

### 1. 环境准备

```bash
# Python 3.10+
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

### 3. 验证

```bash
make test
```

当前本机需要先安装 requirements，尤其是 `pytest`、`httpx`、`pyarrow`，才能跑完整测试。

Phase 8 完成后再启用 Web/Chainlit 入口。

## 项目结构

```
app/
├── main.py         # Chainlit 入口
├── session.py      # 会话管理（追问复用、对话摘要）
├── agent/          # 编排器、规划器、报告生成
├── context/        # TaskContext、PromptAssembler、摘要提取
├── tools/          # WorkbookIngestor、ExcelPreprocessor、Profiler、沙箱、ResultChecker
├── llm/            # LLM 客户端
└── prompts/        # 系统提示词模板
memory/             # 跨会话记忆（用户偏好、已知 schema）
tests/              # 测试
workspace/          # 运行时任务目录（不进 git）
docs/               # 设计文档
```

## 技术栈

- **LLM**: DeepSeek V4 Pro（128K+ 上下文）
- **后端**: FastAPI + Python 3.10+
- **数据处理**: pandas + openpyxl + pyarrow
- **图表**: matplotlib
