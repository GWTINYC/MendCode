# MendCode 开发方案

## 1. 文档职责

本文档面向继续开发 MendCode 的人，记录当前系统状态、模块边界、近期缺口和下一步执行计划。

维护规则：

- 每次实现后，如果能力、接口、风险边界、测试策略或开发优先级发生变化，必须更新本文档。
- `MendCode_全局路线图.md` 只记录长期方向和阶段优先级，避免写成细碎任务列表。
- `README.md` 面向使用者和新贡献者，说明项目定位、启动方式和当前能力。
- 运行日志、conversation、trace、memory、benchmark report 和本地参考 clone 属于 `data/` 运行产物，不提交仓库。

## 2. 当前定位

MendCode 当前定位是 TUI-first 的本地 Code Agent Runtime。用户用自然语言提出任务，模型通过 OpenAI-compatible tool calling 选择工具，MendCode 负责注册表校验、权限策略、本地执行、observation 回传、trace 落盘和必要的验证闭环。

目标架构：

```text
User Message
-> Textual TUI
-> AgentLoop
-> OpenAI-compatible Provider
-> ToolPool exposes scoped tool schemas
-> ToolRegistry validates args
-> PermissionPolicy gates execution
-> Local Executor returns Observation
-> Provider receives tool result
-> Final Response / next Tool Call
-> Conversation Log / JSONL Trace / Memory / Benchmark
```

当前整体进度可概括为：

- 工具与权限主链路：已基本成型，继续补安全细节和 legacy 收敛。
- TUI 自然语言主线：已可用，继续补真实体验、折叠展示和 provider doctor。
- 记忆与上下文：第一切片已完成，下一步是 tokenizer-aware compact、repo map 和长会话健康度。
- 自进化机制：已有候选、规则审查和 analysis report ingestion 基础；analysis report 已能生成 memory / rule / prompt_rule / tool_schema_hint / skill 候选，距离“接受候选 -> 回归验证收益”的完整闭环仍有明显差距。
- Benchmark：固定 manifest、PTY live 和 gate 已建立，下一步是把失败报告接入 EvolutionRuntime。

## 3. 模块现状

### 3.1 Agent Runtime / Provider

已完成：

- `RuntimeTurnInput`、`RuntimeTurnResult`、`RuntimeToolStep` 和 `run_agent_loop_turn`。
- OpenAI-compatible native tool calls。
- Provider-visible tools 由 ToolPool 生成，不再直接暴露完整注册表。
- 工具调用后通过 OpenAI tool message 回填 observation，再由模型继续回答。
- Provider 不支持 tools 时明确失败，不退回普通聊天。
- final response gate 阻止失败 observation 被包装成 completed。
- 重复等价只读工具调用检测，第三次重复会返回 rejected observation。
- `ContextManager` 已接入 AgentLoop，负责构建 provider context 和记录 context metrics。
- `EvolutionRuntime.after_turn()` 已接入 AgentLoop，采用 best-effort，不影响用户最终回答。

主要不足：

- `app.agent.loop` 中仍保留部分 legacy action parsing 和 helper。
- direct scripted action path 仍作为 repair/测试兼容入口存在。
- Provider 请求/响应调试摘要还不够完整。

近期任务：

- 把 action parsing、tool invocation helper 继续拆入 runtime 内部模块。
- 收敛 legacy JSON action / scripted compatibility path，保持 TUI 自然语言主线只走 schema tool call。
- 给 provider request/response 增加安全摘要 trace，确保不泄露 API key。
- 扩展 deterministic mock provider，覆盖写工具、权限确认恢复、retry 和重复调用去重。

### 3.2 ToolRegistry / ToolPool

已完成：

- `ToolSpec`、Pydantic args model、OpenAI tools schema、risk level、executor、aliases 和 shared observation envelope。
- `ToolPool` 支持 permission mode、allowed tools、simple mode 和 group/profile 过滤。
- `tool_search` 只返回当前 context 中实际可用的工具，避免模型请求不可见工具。
- `read_file`、`list_dir`、`glob_file_search`、`rg`、`search_code`、`git`、`repo_status`、`show_diff`、`detect_project`、`apply_patch`、`write_file`、`edit_file`、`todo_write`、`session_status` 等基础工具已接入。
- `memory_search`、`memory_write`、`file_summary_read`、`file_summary_refresh`、`trace_analyze` 已接入。
- `review_queue_*`、`evolution_rule_*` 已接入，用于 TUI-first 审查候选经验和规则。
- `process_*` 和基础 `lsp` 已接入。
- 宽泛搜索默认排除 `.git`、`.worktrees`、`data` 等运行产物；显式搜索 `data/**` 时仍可分析对话记录。
- 文本工具有二进制拒绝和大小上限。

当前工具池已超过 20 类本地能力，符合最终目标的数量基础。

主要不足：

- 写入工具的 diff preview、确认恢复和失败摘要还需要更细。
- 文件系统元信息工具不完整，例如受限 `stat` / `tree`。
- LSP transport 配置和多语言 server 管理仍偏基础。
- 部分 legacy 调试入口还没有完全贯穿 ToolPool。

近期任务：

- 增加写入工具 preview 和 permission resume 测试。
- 补受限 `stat` / `tree` 工具，确保默认只读、路径不能逃逸。
- 建立 provider schema snapshot 测试，避免工具描述变更破坏模型调用。

### 3.3 PermissionPolicy / ShellPolicy

已完成：

- 权限目标模式：`read-only`、`workspace-write`、`danger-full-access`。
- 兼容别名：`safe -> read-only`、`guided -> workspace-write`、`full -> danger-full-access`、`custom -> confirm`。
- `PermissionDecision`、`required_mode` 和通用 pending confirmation payload。
- ShellPolicy 负责 shell 风险分类，最终 allow/confirm/deny 由 PermissionPolicy 统一判断。
- 低风险只读 shell 自动执行；写入、安装、网络、git mutate 需要确认；critical destructive 和明显 path escape 直接拒绝。
- TUI pending tool confirmation 支持确认、取消和切换权限模式。
- 用户取消时会形成 rejected observation，模型不能假装工具已执行。

主要不足：

- Custom mode 还没有配置化。
- 写工具和高风险 shell 的覆盖还需要继续扩展到更多真实用户措辞。

近期任务：

- 所有写主工作区、安装、网络、commit、push、reset、checkout、path escape 都必须有单测和 scenario 覆盖。
- 在 TUI 中展示更清晰的风险说明和 allow-once 语义。

### 3.4 TUI / Conversation

已完成：

- Textual TUI 启动和聊天主视图。
- `TuiController` 接管输入解析、slash commands、AgentLoop 调度和 pending confirmation。
- 自然语言请求统一走 schema tool-call AgentLoop；规则旁路不再直接替模型执行 shell/tool。
- `/status`、`/sessions`、`/resume [session_id]`。
- tool result 和 turn result 在聊天流与 conversation log 中做 compact 摘要。
- Conversation Markdown / JSONL 写入，trace path 和完整 payload 留在后台记录。
- PTY live e2e 测试用 `pexpect` 启动真实 TUI 进程并模拟用户输入。
- TUI scenario audit 能把 scenario、PTY live、integration 结果映射到 benchmark report 和 analysis report。

主要不足：

- 工具调用折叠/展开、完整 payload viewer、trace viewer 和 review 面板仍不完整。
- worker 执行、渲染和 review action 仍有一部分留在 `MendCodeTextualApp`。
- provider health / doctor 未形成 TUI surface。
- 真实 PTY 依赖 provider 环境，缺环境时会明确失败。

近期任务：

- 每个用户暴露的 TUI 体验问题必须补 scenario / PTY / benchmark case。
- 增加 trace viewer：聊天流只显示摘要，用户需要时按 trace id 展开完整 payload。
- 增加 review 面板：统一审查 memory、rule、skill candidate。
- 建 provider doctor，检查 env、base URL、model、tool support 和一次最小 tool-call roundtrip。

### 3.5 Session / Trace / Analysis

已完成：

- JSONL trace、Markdown conversation、JSONL conversation。
- `SessionStore` 扫描 `data/conversations/*.jsonl`，支持 list/latest/session-id lookup。
- `/resume` 注入 compact context，不回灌完整文件内容。
- `mendcode trace analyze-session` 支持分析 conversation Markdown 和 JSONL trace。
- Session analysis 输出 expected tools、observed tools、missing/repeated/failed tools、oversized outputs、unsupported claims、risk events、root causes 和 recommendations。
- Benchmark gate 失败会写入 `data/analysis-reports/`。

主要不足：

- 离线 analysis 仍是规则化第一版。
- analysis report 已能通过 schema tool 进入 EvolutionRuntime 并生成 review candidates。
- 还没有长会话 session health probe。

近期任务：

- 扩展 analysis report reader/model，覆盖 session analysis 和 benchmark analysis 的更多字段。
- 将 root causes 继续扩展为 memory/rule/skill/tool schema hint candidate。
- 把候选统一送入 review queue 或 evolution rule review。
- 在 TUI 中支持“有哪些失败可以沉淀？”这类自然语言审查入口。

### 3.6 Layered Memory / Context Management

已完成：

- `MemoryStore` 使用 `data/memory/memories.jsonl`，支持 append/search/list/update。
- 记忆类型包括 `project_fact`、`task_state`、`file_summary`、`failure_lesson`、`trace_insight`。
- 文件摘要缓存按 path、sha256、mtime、size、line count 和 symbols 校验。
- `MemoryRuntime` 支持 recall、file summary 和 review queue。
- AgentLoop 每轮开始前通过 `ContextManager -> MemoryRuntime.recall_for_turn()` 召回少量相关 memory。
- Context metrics 记录 observation、memory recall、read_file、重复 read_file、raw/compact 字符量和节省量。
- `memory_write` 和 `file_summary_refresh` 属于写长期状态能力，默认不暴露给普通只读工具池。
- `trace_analyze` 只读，不允许绕过权限静默写 memory。

主要不足：

- Context compaction 仍是字符预算，未接入真实 tokenizer。
- 文件摘要还未形成稳定 repo map。
- 长会话 compact summary 还不完整。
- `memory_write` 仍缺确认、合并、敏感信息过滤和专用审查界面。

近期任务：

- 接入 tokenizer-aware budget，根据模型窗口动态裁剪 context。
- 扩展 repo map：目录结构、关键入口、测试命令、核心模块摘要。
- 把 repeated read 和 file summary 命中率作为 benchmark 指标长期观察。
- 设计 memory 写入审查：模型只生成候选，用户接受后才进入长期 memory。

### 3.7 Evolution / SKILL

已完成：

- `EvolutionRuntime` 可根据失败 turn、rejected tool、重复读取和验证恢复生成 lesson candidate。
- `AnalysisIngestionRuntime` 可读取 `data/analysis-reports/*.json`，把 root causes 转成 pending memory/rule candidates。
- Lesson candidate 使用确定性 hash，避免重复候选。
- Review queue 保存候选，accept 才提升为长期 memory。
- `analysis_report_list` 和 `analysis_report_ingest` 已暴露为 schema tools，TUI 自然语言可以触发“列出失败分析/沉淀失败经验”的审查入口。
- `evolution_rule_list/view/accept/reject/accept_with_edits` 已暴露为 schema tools。
- Accepted rules 写入 `data/evolution/rules.jsonl`，运行时按相关性召回 top 3 active rules。
- Pending / rejected candidate 不影响模型行为。

主要不足：

- 还没有 SKILL.md-compatible skill system。
- Analysis ingestion 仍是第一版，只覆盖 benchmark failure analysis 的核心 root causes。
- 候选已能生成 prompt_rule、tool_schema_hint 和 skill 第一版审查项，但它们接受后还没有专用 runtime store 或 benchmark proof。
- 尚未形成“接受候选后再次跑 benchmark 证明收益”的闭环。

近期任务：

- 完善 `data/analysis-reports/*.json -> candidate -> TUI review -> accepted runtime context` 的真实 TUI 场景覆盖。
- 扩展 prompt_rule、skill、tool_schema_hint 候选的接受后生效路径，避免只停留在 review queue 状态。
- SKILL 第一批只做 Debug、Test-Fix、Review、Repo-Map，不追求复杂插件化。
- 每个 accepted candidate 都记录来源 trace、analysis report、用户操作和回滚标识。

### 3.8 Benchmark / PTY 评测

已完成：

- `app.runtime.benchmark` 计算 case pass rate、tool chain pass rate、dangerous command block rate、route pass rate、answer concise rate、provider failure、trace exposure、token-ish reduction 和 repeated read。
- `tests/scenarios/benchmark_manifest.json` 固定目录查看、路径查看、Git、文件末句、文件读取、代码定位、工具面、危险命令、会话列表、多轮对话、记忆召回和修复链路等真实用户问题。
- `app.runtime.benchmark_gate` 能把 pytest failure 映射到 benchmark case。
- `app.runtime.tui_scenario_audit` 支持 manifest 驱动 pytest node selection，并输出 benchmark report 和 analysis report。
- PTY live 回归覆盖“文档最后一句不应返回全文”等真实体验问题。

主要不足：

- 没有真实 provider env 时，PTY live 会失败；这是预期，但本地开发需要更明确的 doctor 和降级说明。
- Token 降低仍是 token-ish / context-ish 指标，未接入真实 tokenizer。
- 评测集仍需扩展到更多长链路修复任务和自进化任务。

近期任务：

- 把每个用户反馈的问题沉淀为 benchmark case。
- 把 benchmark failure analysis 接入 EvolutionRuntime。
- 增加对“回答简洁、不泄露 trace path、不重复输出全文、不编造 git 状态”的强断言。
- 固定回归命令：非 e2e pytest、ruff、benchmark gate；真实 provider 环境下再跑 PTY live。

## 4. 下一阶段优先级

当前最应该补的是自进化闭环，而不是单纯增加更多工具。

建议按以下顺序推进：

1. Analysis Report -> Evolution Candidate
   - 已完成第一版：读取 `data/analysis-reports/*.json`。
   - 已完成第一版：将 root causes 映射成 memory / rule / prompt_rule / tool_schema_hint / skill 候选。
   - 下一步：为 prompt_rule / skill / tool_schema_hint 增加专用 store、runtime recall 和 benchmark proof。
   - 候选必须带来源 trace、benchmark case、失败证据和建议改动。

2. TUI-first Review Loop
   - 用户用自然语言问“有哪些 benchmark 失败可以沉淀？”。
   - 模型调用 `analysis_report_list` / `analysis_report_ingest` / review tools 列出候选。
   - 用户可以查看、编辑、接受或拒绝。
   - 接受后才写入 `data/evolution/` 或 `data/memory/`。

3. Context Budget V2
   - 引入 tokenizer-aware 估算。
   - 给 observation、memory、file summary、conversation history 设置分层预算。
   - 让 benchmark report 能看到 compact 前后差异。

4. SKILL.md 第一切片
   - 定义 skill schema 和加载规则。
   - 先沉淀 Debug、Test-Fix、Review、Repo-Map 四类流程。
   - Skill 不自动修改仓库；先作为 provider context 和可审查候选。

5. TUI 体验收尾
   - trace viewer。
   - review 面板。
   - tool call 折叠/展开。
   - provider doctor。

## 5. 验证策略

常规验证：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Benchmark gate：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt \
  python -m app.runtime.tui_scenario_audit \
  --benchmark-manifest tests/scenarios/benchmark_manifest.json \
  --benchmark-output data/benchmark-reports/latest.json \
  --analysis-report-dir data/analysis-reports
```

真实 PTY：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

真实 PTY 需要 provider env：

```bash
MENDCODE_PROVIDER
MENDCODE_MODEL
MENDCODE_BASE_URL
MENDCODE_API_KEY
```

缺环境时失败是正确结果，不应静默 skip。

## 6. 开发约束

- 新功能默认走 ToolRegistry / ToolPool，不能给模型开规则旁路。
- 本地事实必须来自 observation，不能靠模型自由聊天。
- 写入、Patch、Shell、Git mutate、进程、长期 memory 和 evolution 写入必须经过 PermissionPolicy。
- 修复类任务必须有验证 observation。
- Conversation log 只保存摘要和定位信息；完整 payload 留在 trace。
- `data/` 下的运行产物不得提交。
- 长期 memory、rule、skill 必须可审查、可追踪、可回滚。
- 新增用户体验修复时，先补 scenario / PTY / benchmark case，再改实现。
