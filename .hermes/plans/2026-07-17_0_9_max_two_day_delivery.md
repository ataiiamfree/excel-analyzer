# v0.9 Max Two-Day Delivery Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在两天内把当前 `main` 收敛成可演示、每条核心流程可跑通、具备基础 robustness 的本地单用户 `v0.9 Max`，不追求企业级生产能力。

**Architecture:** 不新增产品能力、不重构分析引擎；以当前 FastAPI + WebSocket + React + SQLite 实现为 release candidate，只修验收中发现的 P0/P1 阻塞。用自动化回归、真实浏览器走查和故障注入三层证据证明“能跑通且不容易出戏”。

**Tech Stack:** Python 3.10+、FastAPI、WebSocket、SQLite、React 18、TypeScript、Vite、pytest、DeepSeek LLM、openpyxl/pandas。

---

## 0. Review 结论与范围修正

### 当前事实基线（2026-07-17）

- `main` 位于 `13c2d9f`，已合入 v0.9.1 hotfix 与 v0.9.2 conversation lifecycle hardening。
- 当前已有 `v0.9-mvp`、`v0.9.1-mvp` tag；尚无 `v0.9.2-mvp` / `v0.9-max` tag。
- 后端测试清单目前有 291 个 test function；最近状态文档声称 291 passed，但本计划执行时必须在当前环境重新跑，不能只引用旧数字。
- `docs/V0.9-MVP-Release.md` 仍写 `v0.9.0` / 264 passed；`README.md` 和 `pyproject.toml` / `web/package.json` 也仍显示 0.9.0。
- cc 产出的 `docs/Delivery-Plan-MVP.md`、`docs/MVP-Execution-Steps.md`、`docs/execution-status.md` 是 7 月 15 日的四周计划；`docs/status-2026-07-friday.md` 已明确它们作废。
- cc 的旧计划里以下 robustness 已在代码中实现，不应重复开发：上传扩展名/大小/损坏校验、WS 三次指数退避重连、结构化 timeout/rate-limit 错误、取消运行、历史恢复、删除会话 active-run 守卫、run GET/DELETE、并发上限、artifact/workspace containment。
- SheetBench 当前证据是 15/21，且 21/21 能正常收口；1135 与其他 5 个 case 是已知准确性限制。两天内不再追 benchmark 分数，不做 case-specific 修补。
- 工作区有未跟踪的 cc 文档、docx 和生成脚本。它们不得被一股脑加入 release commit；只纳入与本次版本事实和验收直接相关的 Markdown/脚本。

### v0.9 Max 的唯一交付定义

必须同时满足：

1. 当前 `main` 的 Python 全量测试和前端生产构建通过。
2. 三条核心用户旅程在真实浏览器连续走通：首次分析、同会话追问、刷新恢复/产物查看下载。
3. 五条基础错误路径有明确提示且服务不崩：错误格式、损坏文件、空问题、WS 中断恢复、运行中取消。
4. 运行/会话生命周期走通：运行中不可删，取消/完成后可删，刷新后历史仍在。
5. 版本说明、README、已知限制、验收结果与代码事实一致。

### 明确不做

- 鉴权、多租户、Docker/K8s、CI、监控告警、压测、审计、计费、移动端。
- SheetBench 17/21 或 21/21 冲分。
- WebSocket heartbeat、跨进程任务恢复、复杂 workspace GC。
- UI 像素级 polish、架构重构、新 benchmark、新文件格式。

---

## Day 1：冻结基线 + 真实 happy path

### Task 1: 建立干净的 release-candidate 基线

**Objective:** 先证明当前代码是否已经可交付，并隔离 cc 的未跟踪产物，避免误提交。

**Files:**
- Review: `docs/Delivery-Plan-MVP.md`
- Review: `docs/MVP-Execution-Steps.md`
- Review: `docs/execution-status.md`
- Review: `docs/status-2026-07-friday.md`
- Create: `docs/v0.9-max-qa-report.md`

**Steps:**

1. 记录 `git rev-parse HEAD`、`git status --short`、Python/Node/npm 版本到 QA 报告。
2. 对每个未跟踪文件分类为 `release evidence`、`historical/reference`、`unrelated generated artifact`；本任务不删除任何文件。
3. 运行 `python -m pytest tests/ -q`，预期全部通过；失败时在 QA 报告记录 exact test 和 traceback 摘要。
4. 运行 `npm --prefix web run build`，预期 TypeScript 与 Vite 构建通过。
5. 运行 `python scripts/smoke_delete_lifecycle.py`；如果真实 LLM 不可用，明确标为环境阻塞，不用 mock 结果冒充验收。
6. Gate：测试或 build 不通过时，只进入 Task 2 修 release blocker，不开始 UI 美化或能力增强。

### Task 2: 只修自动化基线中的 P0/P1

**Objective:** 恢复绿灯；不借机扩 scope。

**Files:**
- Modify only failing implementation file(s) under `app/`, `web/src/`, or `scripts/`
- Test: matching file under `tests/`

**Steps per failure:**

1. 先写/收窄一个能稳定复现的回归测试。
2. 运行单测确认失败。
3. 做最小修复。
4. 运行目标测试，再跑全量 pytest 或 web build。
5. 在 `docs/v0.9-max-qa-report.md` 记录根因、修复和验证命令。
6. 若单个问题预计超过 2 小时且不阻断三条核心旅程，将其降为已知限制，不继续深挖。

### Task 3: 启动单端口 release-like 版本

**Objective:** 验收用户实际拿到的构建产物，而非只验收两个开发服务器。

**Files:**
- Verify: `Makefile`
- Verify: `app/api/server.py`
- Verify: `web/dist/`

**Steps:**

1. 运行 `make web-build`。
2. 运行 `make run`，访问 `http://127.0.0.1:8000/api/health` 和 `http://127.0.0.1:8000`。
3. 确认 API version、页面静态资源、SPA fallback 都来自同一服务。
4. 截图或记录 health JSON 与首页加载结果到 QA 报告。

### Task 4: 浏览器核心旅程 A — 首次分析

**Objective:** 从空首页到报告和产物完整走通一次。

**Files likely to change only if blocked:**
- `web/src/pages/HomePage.tsx`
- `web/src/pages/ConversationPage.tsx`
- `web/src/chat/Composer.tsx`
- `web/src/api/http.ts`
- `web/src/api/ws.ts`
- `app/api/routers/conversations.py`
- `app/api/server.py`
- `app/api/ws/runner.py`

**Steps:**

1. 使用一张小型、答案可人工核对的真实 `.xlsx`，不要用 SheetBench case。
2. 首页上传文件，确认会话创建、侧栏出现、文件名正确。
3. 提问一个确定性问题，例如“按部门汇总金额并给出总计”。
4. 确认 WS 建连、计划出现、步骤状态按 pending/running/done 更新。
5. 确认最终报告有数值结论，人工与 Excel 原始数据核对。
6. 确认至少一个产物可预览并下载；下载文件可重新打开。
7. 任一步失败，记录复现、控制台错误、后端日志、P0/P1/P2 分类。
8. Gate：A 必须连续通过两次；允许报告措辞不同，不允许数值主结论错误或流程断裂。

### Task 5: 浏览器核心旅程 B/C — 追问与恢复

**Objective:** 证明产品不只会跑第一次。

**Files likely to change only if blocked:**
- `web/src/chat/Thread.tsx`
- `web/src/chat/MessageAssistant.tsx`
- `web/src/artifacts/FileList.tsx`
- `web/src/artifacts/TablePreview.tsx`
- `web/src/layout/Sidebar.tsx`
- `app/api/persistence/store.py`
- `app/session.py`

**Steps:**

1. 在旅程 A 的会话追问“只看金额最高的两个部门，并生成表格”。
2. 确认无需重新上传，回答引用同一工作簿，旧消息和新产物都保留。
3. 刷新页面，确认会话、消息、最终状态、产物列表恢复。
4. 切到其他会话再切回，确认没有串会话或状态错乱。
5. 下载追问生成的产物并人工核对 top 2。
6. Gate：追问和刷新恢复各连续通过一次，无 P0。

---

## Day 2：故障矩阵 + 最小修复 + 版本冻结

### Task 6: 执行五项 robustness 故障矩阵

**Objective:** 证明常见失败不会让用户卡死或让服务崩溃。

**Files likely to change only if blocked:**
- `app/api/uploads.py`
- `app/api/ws_events.py`
- `app/api/ws/manager.py`
- `app/api/ws/runner.py`
- `web/src/api/http.ts`
- `web/src/api/ws.ts`
- `web/src/pages/HomePage.tsx`
- `web/src/pages/ConversationPage.tsx`
- `web/src/chat/Composer.tsx`

**Matrix:**

| 场景 | 操作 | 必须观察到的结果 |
|---|---|---|
| 错误格式 | 上传 `.txt` | 前端明确拒绝；不创建脏会话/目录 |
| 损坏文件 | 把文本改名为 `.xlsx` | 返回可读错误；原会话文件不被替换 |
| 空问题 | 空白输入发送 | 按钮禁用或提示；后端不启动 run |
| WS 中断 | 分析中临时停止/恢复连接 | 显示重连状态；最多 3 次退避；页面不红屏 |
| 取消 | 长分析运行中点击取消 | 步骤与 run 标为 cancelled；连接仍可继续使用 |

**Steps:**

1. 每项保存 UI 现象、HTTP/WS 状态和后端是否仍健康。
2. 测试后再次访问 `/api/health` 并发起一个正常小问题，防止“表面报错、服务已坏”。
3. P0 定义：正常流程断裂、数据串会话、服务 crash、无法恢复、错误答案却标成功。
4. P1 定义：错误提示不清晰、状态持久化错误、需刷新才能恢复。
5. P2 定义：纯视觉/措辞问题；全部进 backlog，不在两天内修。

### Task 7: 会话与运行生命周期验收

**Objective:** 验证 cc 已合入的 P1-5/P1-6 确实在真实 UI/API 下成立。

**Files likely to change only if blocked:**
- `app/api/routers/conversations.py`
- `app/api/routers/runs.py`
- `app/api/deps.py`
- `app/api/ws/manager.py`
- `web/src/layout/Sidebar.tsx`
- `tests/test_api_server.py`
- `tests/test_api_runs.py`
- `tests/test_ws_manager.py`

**Steps:**

1. 空闲且 WS 已连接时删除会话，应成功。
2. 分析运行中删除会话，应返回 409 且 workspace/SQLite 记录仍在。
3. 取消或等待完成后再次删除，应成功并释放 Session cache/workspace。
4. 调用 `/api/runs/{id}` 获取状态；对运行中 run 执行 DELETE，确认取消语义正确。
5. 执行 `python -m pytest tests/test_api_server.py tests/test_api_runs.py tests/test_ws_manager.py -q`。

### Task 8: 修复 Day 1/2 中唯一值得修的 blocker

**Objective:** 把 P0 清零、P1 限定为最多 1–2 个有明确 workaround 的已知限制。

**Rules:**

1. 每个 blocker 必须有稳定复现步骤或自动化测试，不凭感觉改。
2. 优先修状态机、错误边界、数据正确性；不修颜色、间距、动画。
3. 不修改 `app/tools/excel_preprocessor.py`、`app/tools/result_checker.py`、planner/prompt，除非真实业务 happy path 被稳定阻断并有通用根因证据。
4. 每次修复后重新跑对应旅程/故障场景，再跑全量 pytest + web build。
5. 截止 Day 2 下午仍无法低风险修复的项写入 release note，不延期去做生产级方案。

### Task 9: 统一版本与交付文档

**Objective:** 消除“代码是 0.9.2、文档是 0.9.0、旧计划说还未开始”的冲突。

**Files:**
- Modify: `README.md`
- Modify: `docs/V0.9-MVP-Release.md`（或重命名/新建 `docs/V0.9-Max-Release.md`，二选一）
- Modify: `docs/status-2026-07-friday.md`
- Modify: `pyproject.toml`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`（仅由 npm version/build 的一致性变更产生）
- Create/complete: `docs/v0.9-max-qa-report.md`
- Create: `docs/Backlog.md`
- Annotate as historical: `docs/Delivery-Plan-MVP.md`
- Annotate as historical: `docs/MVP-Execution-Steps.md`
- Annotate as historical: `docs/execution-status.md`

**Steps:**

1. 先决定唯一显示名：建议 tag `v0.9.2-mvp`，产品文案可称“v0.9 Max”；不要同时制造两个语义不清的 release tag。
2. 版本号统一到 0.9.2；release note 只写实际跑出的测试数和 QA 结果。
3. 把 15/21 SheetBench、1135/515 等不稳定性、LLM 随机性、本地单用户定位明确写入已知限制。
4. 在三份 cc 旧计划顶部加醒目的“历史计划，已由当前 release plan 替代”，不重写全文。
5. `docs/Backlog.md` 仅保留非阻塞项：生产化、安全深审、监控、部署、heartbeat、GC、benchmark 能力提升、UI P2。
6. 不把业务无关 docx 和生成脚本混入 release commit。

### Task 10: 最终 release gate 与冻结

**Objective:** 只有证据全部成立才发布。

**Verification commands:**

```bash
python -m pytest tests/ -q
npm --prefix web run build
python scripts/smoke_delete_lifecycle.py
git status --short
git diff --check
```

**Manual gate checklist:**

- [ ] 首次分析连续两次通过，主数值人工核对正确。
- [ ] 同会话追问通过。
- [ ] 刷新/切换会话恢复通过。
- [ ] 产物预览、下载、重新打开通过。
- [ ] 五项故障矩阵通过，故障后服务仍健康。
- [ ] 运行中删除 409；取消/完成后可删。
- [ ] P0 = 0。
- [ ] P1 有明确 workaround 且已写 release note。
- [ ] README、版本号、release note、tag 名一致。
- [ ] staged files 不含无关 cc docx/脚本或本地 `.env`、SQLite、runtime log。

**Release action（需用户确认后执行）:**

1. 精确 stage 本计划内变更和验收文档。
2. 创建一个 release-candidate commit；不要 squash 掉 cc 已合入提交的历史。
3. 在 commit 上打 annotated tag `v0.9.2-mvp`。
4. 若需推远端，再 push branch/tag；本计划不默认授权发布远端。

---

## Go / No-Go 标准

**GO:** 全量测试、web build、三条核心旅程、五项故障矩阵全部通过；P0 为 0；已知准确性限制如实披露。

**CONDITIONAL GO:** 仅剩不影响流程的 P1/P2，且有简单 workaround；例如 WS 自动重连失败但“手动重连”稳定有效。

**NO-GO:** 任一核心旅程无法连续完成、报告主数值稳定错误、取消/删除造成数据损坏、刷新后会话丢失、正常错误输入导致服务 crash。

## 时间预算

- Day 1 上午：Task 1–3（2–3h）
- Day 1 下午：Task 4–5（3–4h）
- Day 2 上午：Task 6–7（2–3h）
- Day 2 下午：Task 8–10（3–5h，修复预算最多 3h）

超过预算时的砍项顺序：UI P2 → 文档润色 → P1 非阻塞修复 → 额外 QA 场景。核心三旅程、故障矩阵和 release note 不砍。

---

## Phase 2：视频演示与 PPT 就绪度优化（已执行，PPT 文件待大纲确认）

### 审查结论（2026-07-19）

当前产品的**功能演示就绪度已经合格**：上传、分析、计划/进度、报告、表格/图表产物、下载、追问、刷新恢复和基础故障路径均有真实浏览器证据。但从“录一条可复用的视频、截一组能直接放进 PPT 的画面”来看，只能判定为 **Conditional Ready**，还不建议直接开始正式录制。

主要差距不是分析能力，而是演示表达：

1. 没有固定的演示数据、问题、标准答案、录制脚本和重置流程，实时 LLM 的时延与随机性容易让录制返工。
2. 界面仍暴露 `tokens`、`mixed`、`step`、`artifacts`、脚本路径/stdout 等技术信息；“思考过程”运行时默认展开，不适合业务型 PPT 和公开视频。
3. 侧栏硬编码 `Natalia X.`，品牌又同时出现 Excel Analyzer、ChatExcel、v0.9 Max，录屏与截图口径不统一。
4. 首页只有一句产品说明和 textarea placeholder，缺少“一眼看懂”的价值点、典型场景和可点击示例问题。
5. 报告已经结论优先，但关键数值仍主要依赖 Markdown 正文；表格浮点尾差、英文状态标签会直接降低截图质感。
6. 仓库没有正式截图、视频脚本、PPT 大纲、演示预检清单或网络异常备用方案。

本阶段只做**影响演示理解、录制稳定性和截图质量**的优化，不做营销官网、复杂动画、核心分析引擎重构，也不伪造分析结果。

### 优先级与时间盒

| 优先级 | 范围 | 进入正式录制前是否必须 |
|---|---|---|
| Demo-P0 | 固定演示故事、预检/重置流程、去个人化、隐藏高风险技术细节、真实浏览器彩排 | 必须 |
| Demo-P1 | 首页价值表达、结果视觉层级、数值展示、统一中文标签、截图素材 | 建议全部完成 |
| Demo-P2 | 动画、营销落地页、完整品牌系统、多套行业皮肤 | v0.9 不做 |

建议总预算为 **1 个工作日，约 6–8 小时**；前 4–5 小时完成产品演示优化，后 2–3 小时完成彩排、截图、视频/PPT 脚本。若超时，先砍视觉动画和额外场景，不能砍预检、去个人化、数值格式和真实浏览器彩排。

### Task 11: 冻结一条可复现的演示故事

**Objective:** 让视频、现场演示和 PPT 使用同一份数据、同一组问题和同一套正确答案。

**Files:**
- Reuse: `docs/test_datasets/simple/01_门店月度销售.xlsx`
- Create: `docs/demo/v0.9-demo-runbook.md`
- Create: `docs/demo/v0.9-demo-expected-results.md`

**演示主线：**

1. 用户痛点：门店销售 Excel 需要手工汇总，结果难复核、难分享。
2. 首问：`分析上半年各门店总销售额，给出完整排名，生成一张排名图，并导出 CSV 和 Excel。`
3. 标准答案：杭州西湖店 753.3、北京旗舰店 739.7、上海南京路店 664.9、广州天河店 664.8、成都春熙路店 566.7。
4. 追问：`只保留销售额最高的两个门店，并说明它们与第三名的差距，输出 CSV。`
5. 收尾：展示报告、图表、表格预览和下载，再刷新页面证明结果可恢复。

**Steps:**

1. 在 expected-results 中记录源表人工计算口径、完整排名、Top 2 和差值，禁止以模型输出反推标准答案。
2. 将主问题控制在一条消息内，避免录制时临时改词导致产物类型变化。
3. 在 runbook 中写出 90–120 秒成片版和 3 分钟现场版的逐镜头台词、点击位置与预期画面。
4. 准备一个已真实跑完且数值核对正确的备用会话；它只作为网络故障时切换展示，不伪装成刚完成的实时分析。

**Gate:** 连续两次使用同一问题都得到正确主结论，并生成可预览的图表与 CSV/XLSX；否则先收窄问题，不修改核心引擎追求花哨结果。

### Task 12: 统一品牌并去除个人化/技术噪声

**Objective:** 让任何人看到截图都认为这是一个完整产品，而不是开发者调试界面。

**Files:**
- Modify: `README.md`
- Modify: `web/src/pages/HomePage.tsx`
- Modify: `web/src/layout/Sidebar.tsx`
- Modify: `web/src/layout/Topbar.tsx`
- Modify: `web/src/chat/ReasoningCapsule.tsx`
- Modify: `web/src/chat/PlanBlock.tsx`
- Modify: `web/src/chat/ProgressLine.tsx`
- Modify: `web/src/chat/StepItem.tsx`

**Steps:**

1. 产品界面统一使用 `ChatExcel`，版本/交付文档使用 `v0.9 Max（0.9.2）`；`Excel Analyzer` 仅保留为仓库/技术项目名。
2. 把侧栏底部硬编码的 `Natalia X.` 替换为中性信息，如 `本地工作区 · v0.9 Max`；不实现账号系统。
3. 将“思考过程”改为“分析过程”，运行时默认收起，不在业务界面显示 token 数。
4. 保留执行步骤的可解释性，但把 `mixed`、`step 1/3`、`artifacts`、`explore` 等改为自然中文。
5. 脚本路径、stdout 和代码产物统一放进默认折叠的“技术详情”，主画面只显示用户能理解的任务、状态和耗时。

**Validation:**

```bash
npm --prefix web run build
rg -n "Natalia X\.|tokens|mixed|artifacts|step [0-9]" web/src
```

预期：build 通过；上述英文/个人信息不再出现在默认用户可见文案中。

### Task 13: 优化首页的 5 秒理解力

**Objective:** 视频开场或 PPT 首页截图在 5 秒内说明“给什么、做什么、得到什么”。

**Files:**
- Modify: `web/src/pages/HomePage.tsx`
- Modify: `web/src/styles/index.css`

**Steps:**

1. 主标题下使用结果导向文案：`上传 Excel，用一句话得到分析结论、图表和可下载表格。`
2. 增加三个轻量能力标签：`自动理解表格`、`可追问分析`、`结果可下载`。
3. 增加 2–3 个可点击示例问题 chip；点击只填入输入框，不自动提交、不绑定硬编码答案。
4. 上传后明确显示文件已就绪状态；开始按钮的视觉优先级高于其他说明。
5. 保持单屏完成，不增加营销长页、不加入轮播或复杂动画。

**Browser acceptance:** 在 1440×900、100% 缩放下，标题、价值文案、上传区、问题输入和主按钮全部无需滚动即可看到；示例问题可被键盘和鼠标操作。

### Task 14: 把结果页优化成可截图的“结论画面”

**Objective:** 让报告和产物画面可以直接作为 PPT 的产品证据页。

**Files:**
- Modify: `web/src/chat/ReportArticle.tsx`
- Modify: `web/src/chat/ArtifactChips.tsx`
- Modify: `web/src/layout/ArtifactPanel.tsx`
- Modify: `web/src/artifacts/TablePreview.tsx`
- Modify: `web/src/styles/index.css`

**Steps:**

1. 对报告中的“最终答案/简要结论”增加稳定的视觉强调，但不改写模型结论、不解析生成新的业务数字。
2. 产物 chip 明确显示 `表格`、`图表`、`Excel`、`CSV`，弱化 `MD/IMG/XL` 这种需要解释的缩写。
3. 表格数字统一做展示层格式化：去除 `753.3000000000001` 一类二进制尾差，保留原下载文件精度；金额/数值列右对齐。
4. 产物面板的“代码”改为默认隐藏的“技术详情”；首屏优先展示图表和表格。
5. 检查长文件名、长列名、横向表格和 480px 产物面板，保证不会遮住核心结论。

**Validation:**

```bash
npm --prefix web run build
git diff --check
```

真实浏览器必须核对：报告主数字正确、CSV/XLSX 下载内容未被展示格式化影响、表格不再出现明显浮点尾差。

### Task 15: 建立录制前预检和可恢复演示流程

**Objective:** 把“现场不出戏”从经验变成一张每次都能照着执行的清单。

**Files:**
- Create: `scripts/demo_preflight.py`
- Modify: `docs/demo/v0.9-demo-runbook.md`
- Create: `docs/demo/v0.9-demo-checklist.md`
- Test: `tests/test_demo_preflight.py`

**Preflight 只做只读检查：**

1. `/api/health` 为 200，OpenAPI version 为 0.9.2。
2. 演示 Excel 存在、可读取，且关键工作表/列名与标准答案文件一致。
3. 前端 production build 已存在，当前使用稳定的 `make run` 而非 reload 模式。
4. LLM 必要配置存在但不打印 secret；Pi runtime 包含 context/Git 防线。
5. 浏览器录制尺寸、缩放、下载目录、通知免打扰和鼠标轨迹已检查。

**Steps:**

1. 先写 `tests/test_demo_preflight.py`，用临时目录和 mock health response 验证成功、缺文件、版本错误、服务不可达四类结果。
2. 实现脚本；禁止自动删除用户会话、修改 `.env` 或启动/停止服务。
3. 在 runbook 中补充网络异常时的诚实降级路径：停止实时等待，切到已完成备用会话，并明确说明这是已完成样例。

**Validation:**

```bash
python -m pytest tests/test_demo_preflight.py -q
python scripts/demo_preflight.py
```

### Task 16: 真实浏览器完成“录制尺寸”专项彩排

**Objective:** 在最终视频/PPT 使用的分辨率下验证画面，而不是沿用普通功能 QA 的结论。

**Files:**
- Append evidence: `docs/v0.9-max-qa-report.md`
- Create: `docs/demo/v0.9-demo-visual-qa.md`

**Matrix:**

| 画面 | 必须验证 |
|---|---|
| 首页 | 品牌、价值文案、上传、示例问题和按钮同屏 |
| 分析中 | 分析过程默认收起；计划状态清晰；无脚本路径/token/英文调试标签抢镜 |
| 报告完成 | 最终答案在首屏可见；主数值与标准答案一致 |
| 产物预览 | 图表完整；表格数字整洁；下载入口清楚 |
| 追问 | 不重新上传即可继续；Top 2 和差值正确 |
| 刷新恢复 | 消息、报告、产物完整恢复 |

**Steps:**

1. 使用真实浏览器分别在 1440×900 和 1920×1080、100% 缩放走完整主线。
2. 每个关键画面截无裁切原图；截图不得包含 API key、终端、个人通知、无关会话名或本地绝对路径。
3. 录一遍不剪辑的 3 分钟 dry run，记录所有超过 3 秒的无反馈区间和多余点击。
4. 只修影响理解或录制稳定性的 Demo-P0/P1；纯审美意见进入 Backlog。

**Gate:** 主线连续两次通过；没有个人信息和技术噪声；任一关键画面可在不二次拼图的情况下直接用于 PPT。

### Task 17: 生成视频与 PPT 的同源素材包

**Objective:** 用一套事实和截图同时支撑视频、路演 PPT 和交付说明，避免三套口径。

**Files:**
- Create: `docs/demo/v0.9-video-script.md`
- Create: `docs/demo/v0.9-deck-outline.md`
- Create directory: `docs/demo/screenshots/`
- Create later after outline approval: `docs/demo/ChatExcel-v0.9-Max-Demo.pptx`

**视频建议结构（90–120 秒）：**

1. 0–10s：手工 Excel 分析的痛点与一句话价值。
2. 10–25s：上传门店销售表并提出自然语言问题。
3. 25–50s：展示分析计划和进度；等待段可等比加速，但不能伪造结果。
4. 50–80s：展示结论、排名图、表格预览和下载。
5. 80–105s：追问 Top 2 与差距，体现上下文连续性。
6. 105–120s：刷新恢复 + `v0.9 Max` 定位和已知边界。

**PPT 建议结构（8 页）：**

1. 痛点：Excel 数据多、汇总慢、复核难。
2. 产品定位：一句话说明 ChatExcel。
3. 用户流程：上传 → 提问 → 自动分析 → 报告/产物。
4. 产品实录：首页 + 分析中界面。
5. 结果证据：正确排名、图表、表格与下载。
6. 连续工作：追问、历史恢复、可解释步骤。
7. 稳定性证据：293 tests、真实浏览器故障路径、P0=0。
8. 边界与下一步：本地单用户 MVP、6 个 SheetBench 已知限制、v1.0 路线。

**Rules:** 所有 benchmark、测试数、产品能力和限制必须引用当前 QA/release 文档；不写“生产级”“100% 准确”“完全自动化”等超出证据的表述。

### Task 18: 演示发布 Gate

**Objective:** 产品、视频、PPT 三者口径一致后，才进入正式录制和 release commit。

**Verification commands:**

```bash
python -m pytest tests/ -q
npm --prefix web run build
python scripts/demo_preflight.py
git diff --check
```

**Manual gate checklist:**

- [x] 固定演示问题连续两次得出正确主结论和指定产物。
- [x] 1440×900 与 1920×1080 关键画面无裁切、遮挡或 UI 浮点尾差。
- [x] 默认画面无个人信息、绝对路径、token 数、stdout 或英文调试标签。
- [x] 90–120 秒视频脚本与 3 分钟现场脚本完成；真实操作 dry run 两轮完成，未伪造屏幕录制文件。
- [x] 6 张核心截图可直接放入 PPT，且来自真实运行。
- [x] PPT 大纲的测试数字、benchmark、版本号和已知限制与 release note 一致。
- [x] 已准备网络/模型异常时的诚实备用会话与切换话术。
- [x] 新增演示优化未破坏上传、分析、追问、下载和刷新恢复。

**本阶段 Go / No-Go：**

- **GO:** Demo-P0 全部完成，Demo-P1 无阻断，连续两次彩排成功，素材口径一致。
- **CONDITIONAL GO:** 仅剩不会出现在最终镜头里的视觉 P2，可通过取景规避并已记录。
- **NO-GO:** 结果随机错误、关键产物不稳定、录制画面泄露个人/技术信息、PPT 数据与 QA 证据不一致。
