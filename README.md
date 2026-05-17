# Excel 智能分析 Agent

上传 Excel 文件，用自然语言提出分析需求，自动生成 Python 代码执行分析并输出报告。

## 架构

采用 **Adaptive Plan-Execute** 编排：先粗略规划全局，每步执行后根据实际结果动态细化下一步。每次 LLM 调用独立，不累积上下文。

详见 [Design.md](docs/Design.md) 和 [Implementation-Plan.md](docs/Implementation-Plan.md)。

## 当前实现状态

Phase 1–8 已完成，核心功能可用：

- **数据预处理**: WorkbookIngestor → ExcelPreprocessor → Profiler
- **执行引擎**: PythonSandbox + ResultChecker + Adaptive Plan-Execute
- **报告生成**: Reporter 分章节 LLM 调用，自动注册产物
- **交互层**: Chainlit Web 界面，支持文件上传、分析、追问
- **会话管理**: Session 追问复用、Memory 跨会话 schema 匹配

## 快速开始

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

### 3. 运行

```bash
make run
# 浏览器打开 http://localhost:8000
# 上传 Excel → 输入分析需求 → 查看分步进度 → 查看报告和图表
# 追问 "再按部门细分" → 不重新上传，直接出新结果
```

### 4. 测试

```bash
make test
```

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
- **交互层**: Chainlit
- **后端**: Python 3.10+
- **数据处理**: pandas + openpyxl + pyarrow
- **图表**: matplotlib
