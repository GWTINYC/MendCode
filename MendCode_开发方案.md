# MendCode 开发方案

## 1. 文档职责

本文档是 MendCode 的详细开发执行说明。它回答：

- 当前系统已经具备什么能力
- 各模块的边界和契约是什么
- 下一轮应该优先改哪里
- 每次开发后哪些文档和测试需要同步

维护规则：

- 每次代码实现后，如果能力、接口、风险边界、测试策略或开发优先级发生变化，必须更新本文档。
- 全局方向变化才更新 `MendCode_全局路线图.md`。
- 出现可复用的工程教训才更新 `MendCode_问题记录.md`。
- README 面向使用者和新贡献者，本文档面向继续开发的人。

## 2. 当前产品目标

MendCode 是运行在本地仓库中的 TUI Code Agent。用户用自然语言描述任务，模型通过工具调用获取本地事实，MendCode 在本地安全执行工具，并把结果回传给模型继续推理。

目标闭环：

```text
User Message
-> Intent Router
-> AgentLoop
-> Provider
-> ToolRegistry / OpenAI tools schema
-> Permission Gate
-> Tool Executor
-> Observation
-> Provider receives tool result
-> Final Response or next Tool Call
-> Conversation Log / Trace
```

当前优先级：

1. Runtime-first 重构：把 AgentLoop、ToolRegistry、PermissionPolicy、SessionStore 拆成清晰运行时边界
2. ToolRegistry 收敛：所有 provider-visible 工具都从注册表生成 schema、risk 和 executor
3. PermissionPolicy 收敛：统一工具权限、shell 风险、allowed tools 和用户确认
4. 会话日志、trace、compact context、resume 能力
5. Layered Memory 第一切片：本地记忆、文件摘要缓存、失败 trace 经验候选和可控 recall 工具
6. TUI 真实体验测试：用 PTY 启动真实 TUI 进程，覆盖真实 provider/tool-call 闭环和高频自然语言问题
7. TUI 工作台体验：让 Textual UI 成为 runtime 的薄展示层

当前重构设计：

- 设计文档：`docs/superpowers/specs/2026-04-26-runtime-first-refactor-design.md`
- 实施计划：`docs/superpowers/plans/2026-04-26-runtime-first-refactor.md`
- 第一轮已完成：`repo_status`、`detect_project`、`show_diff` 已迁入 ToolRegistry，permission risk 从注册表派生。

## 3. 当前能力状态

### 3.1 AgentLoop

已完成：

- [x] `MendCodeAction` / `Observation`
- [x] `AgentRuntime` compatibility wrapper
- [x] `RuntimeTurnInput` / `RuntimeTurnResult` / `RuntimeToolStep`
- [x] `app.runtime.agent_loop.run_agent_loop_turn`
- [x] `app.runtime.final_response_gate.apply_final_response_gate`
- [x] Provider-driven step loop
- [x] step budget
- [x] observation history
- [x] provider failure observation
- [x] OpenAI-compatible native `tool_calls`
- [x] Provider-driven normal turn 禁用 legacy JSON action / free-text fallback
- [x] native tool invocation 执行
- [x] assistant/tool message 回填
- [x] 工具后普通文本包装为 `final_response`
- [x] final response gate 阻止失败 observation 被标记 completed
- [x] `allowed_tools` 执行期检查
- [x] 重复等价只读工具调用检测，第三次重复调用返回结构化 rejected observation
- [x] deterministic mock provider harness 覆盖 native tool-call 闭环
- [x] read/list/rg/multi-tool/shell/error/allowed-tools/confirmation stop 场景测试

当前不足：

- [ ] runtime loop 仍依赖 `app.agent.loop` 中的 action parsing / tool invocation helpers
- [ ] direct `loop_input.actions` 仍作为 scripted/repair 兼容路径保留
- [ ] Provider request/response 调试摘要不足
- [ ] `apply_patch_to_worktree` 仍是 legacy/builtin 工具路径

下一步：

- 继续把 `_handle_action_payload`、`_handle_tool_invocation` 等 helper 拆入 runtime 内部小模块，最终让 `app.agent.loop` 只保留兼容数据模型和 wrapper。
- 把 `_execute_tool_call` 中的 legacy 分支逐步收敛到 ToolRegistry。
- 删除 legacy scripted action compatibility path once CLI repair no longer uses it。
- 将 `/fix` 兼容路径迁移为纯工具化 repair flow。
- 扩展重复调用策略到更多语义稳定的只读工具，并把拒绝原因写入更清晰的 TUI 摘要。
- 把 provider 调试摘要写入 trace，注意不要落 API key。

### 3.2 Provider

已完成：

- [x] `ScriptedAgentProvider`
- [x] `OpenAICompatibleAgentProvider`
- [x] OpenAI-compatible tools schema 发送
- [x] 原生 tool call 解析
- [x] tools unsupported 明确失败，不再静默 fallback
- [x] tool 后普通文本 final response
- [x] tool 后 `final_response` provider-local tool call
- [x] API key redaction
- [x] scoped `allowed_tools`
- [x] Provider 使用 `ToolPool` 暴露当前权限和场景下可用的 OpenAI tools schema
- [x] 越权 tool call 拒绝
- [x] mock tool provider harness 覆盖 tool result 回传后的 final response
- [x] OpenAI native tool result 不再重复写入 user context，避免 prompt 中 observation 双份膨胀
- [x] Provider 不再对正常用户轮次静默 fallback 到 JSON action 或 free text

当前不足：

- [ ] mock provider harness 仍需扩展到 future write tools 和 permission allow/deny resume
- [ ] 没有请求快照测试覆盖全部工具 schema
- [ ] 真实 provider 行为仍需要更多 TUI 回放场景覆盖
- [ ] 未实现 OpenAI 官方 adapter
- [ ] 未实现 Anthropic adapter

下一步：

- 扩展确定性 mock provider，覆盖 write 工具、权限确认恢复、tool retry 和重复调用去重。
- Provider tests 继续优先使用 fake client，不依赖真实网络。
- 后续新增 provider 时只改 adapter，不改 AgentLoop 主体。

### 3.3 ToolRegistry

已完成：

- [x] `ToolSpec`
- [x] `ToolPool`
- [x] Pydantic args model
- [x] OpenAI tools schema
- [x] `risk_level`
- [x] executor
- [x] `allowed_tools`
- [x] aliases：`read`、`list`、`glob`、`grep`、`search`、`shell`、`bash`、`patch`、`write`、`edit`、`todo`、`tools`
- [x] shared tool observation envelope
- [x] `rg` 和 `search_code` observation 保持各自 tool identity
- [x] Provider-visible tools 从 `ToolPool` 派生，支持 permission mode、`allowed_tools` 和 simple mode 过滤
- [x] `tool_search` 可按当前 context 的 `available_tools` 搜索，避免向模型推荐不可用工具
- [x] 宽泛 `search_code` 默认排除 `.git`、`.worktrees`、`data` 运行产物；显式 `glob='data/**'` 时仍可分析对话记录
- [x] `read_file` 拒绝二进制文件，`write_file` / `edit_file` 有文本大小上限，`edit_file` 拒绝二进制编辑
- [x] 工具别名支持递归 group/profile，例如 `fs_read`、`git_read`、`introspection`、`read_only_agent`、`coding_agent`、`full_coding_agent`

当前工具：

| Tool | 状态 | 说明 |
|---|---|---|
| `repo_status` | 已完成 | 通过 ToolRegistry 读取当前分支和短状态 |
| `detect_project` | 已完成 | 通过 ToolRegistry 识别项目类型和建议验证命令 |
| `show_diff` | 已完成 | 通过 ToolRegistry 读取 compact diff stat |
| `read_file` | 已完成 | 读取 repo-relative 文本文件，支持行范围、尾部读取和截断 |
| `list_dir` | 已完成 | 列目录，未截断时完整 entries 进入 prompt context |
| `glob_file_search` | 已完成 | 按 glob 查找路径 |
| `rg` / `search_code` | 已完成 | 文本搜索，宽泛搜索默认避开运行产物目录 |
| `git` | 已完成 | 结构化只读 git status/diff/log |
| `run_shell_command` | 已完成 | 普通 shell，走 ShellPolicy |
| `run_command` | 已完成 | 仅允许 declared verification command |
| `apply_patch` | 已完成 | 应用统一 diff |
| `write_file` | 已完成 | 写入 repo-relative 文本文件，拒绝路径逃逸 |
| `edit_file` | 已完成 | 精确替换 repo-relative 文本文件内容，拒绝二进制文件 |
| `todo_write` | 已完成 | 返回当前短期结构化 todo 列表 |
| `tool_search` | 已完成 | 按名称和描述搜索可用工具 |
| `session_status` | 已完成 | 返回当前权限、可见工具、验证命令、trace 和近期步骤 |
| `memory_search` | 已完成 | 查询本地 layered memory，返回 compact matches |
| `memory_write` | 已完成 | 写入本地 layered memory，受写权限裁剪 |
| `file_summary_read` | 已完成 | 读取或构建 repo-relative 文件摘要，按内容 hash 校验缓存是否过期 |
| `file_summary_refresh` | 已完成 | 刷新并写入文件摘要记忆，受写权限裁剪 |
| `trace_analyze` | 已完成 | 只读分析 trace/conversation JSONL，生成失败经验候选 |
| `process_start` / `process_poll` / `process_write` / `process_stop` / `process_list` | 已完成 | 管理本轮后台进程和增量日志；`process_start` 走 ShellPolicy，日志写入 `data/processes/` |
| `lsp` | 已完成 | 返回语言服务诊断、定义、引用、hover、symbols 等结构化结果；不可用时明确 rejected |
| `apply_patch_to_worktree` | legacy/builtin | 后续删除或迁移为 `apply_patch` 兼容别名 |

下一步工具：

- [ ] `write_file` / `edit_file` 的更细粒度确认和 diff preview
- [ ] 文件系统元信息工具，例如 `stat` / `tree` 的受限版本
- [ ] LSP transport 配置和多语言 server 管理
- [ ] `memory_write` 的用户确认、去重和敏感内容过滤策略

新增工具检查表：

- [ ] args model
- [ ] executor
- [ ] risk level
- [ ] OpenAI schema 测试
- [ ] 参数非法测试
- [ ] permission 测试
- [ ] native tool call 测试
- [ ] JSON fallback 如需兼容则补测试
- [ ] prompt contract 更新
- [ ] 本文档更新

### 3.4 Permission / Shell Policy

已完成：

- [x] `PermissionMode`: target `read-only` / `workspace-write` / `danger-full-access`
- [x] transitional aliases：`safe -> read-only`、`guided -> workspace-write`、`full -> danger-full-access`、`custom -> confirm`
- [x] `PermissionDecision`
- [x] 独立 `app.permissions.policy.PermissionPolicy`
- [x] `PermissionDecision.required_mode`
- [x] risk level 从 ToolRegistry 派生
- [x] ShellPolicy 作为 shell classifier，最终 allow/confirm/deny 由 PermissionPolicy 统一判断
- [x] shell low-risk 自动执行
- [x] shell 写入/安装/网络/git mutate 确认
- [x] critical destructive 和 path escape 拒绝
- [x] TUI pending shell confirmation
- [x] stdout-only `printf` 低风险允许，重定向仍需确认
- [x] `sed -n` 只读查看允许，`sed -i` 要求确认
- [x] `rg` / `sed` 的显式读取路径逃逸会要求确认，写入路径逃逸会拒绝

当前不足：

- [ ] ToolPool 还未贯穿所有 legacy JSON action 调试入口
- [ ] 工具确认和 TUI pending confirmation 还没有完全统一为 allow once / deny / change mode
- [ ] allow once / deny / change mode 回写不完整
- [ ] Custom mode 未配置化

下一步：

- 所有 Provider 和 prompt contract 都必须通过 ToolPool 获取当前可见工具。
- 把 TUI pending shell confirmation 和通用 tool confirmation 合并。
- 确认或拒绝结果要形成 observation 并回传模型。
- 所有写主工作区、安装、网络、commit、push、reset、checkout 都必须有测试覆盖。

### 3.5 TUI

已完成：

- [x] TUI 启动
- [x] `TuiController` 接管输入解析、slash commands 和 AgentLoop 调度
- [x] `/status`
- [x] `/sessions`
- [x] `/resume [session_id]`
- [x] 自然语言 TUI 请求统一走 schema tool-call AgentLoop
- [x] TUI 规则路由不再直接执行自然语言 shell/tool 请求
- [x] slash command 和 pending confirmation 仍本地处理
- [x] tool result 摘要展示
- [x] conversation Markdown / JSONL 写入，并对 `tool_result` / `turn_result` 做 compact 摘要
- [x] review actions：view diff / view trace / apply / discard
- [x] 第一批 TUI experience scenario tests 覆盖目录查看、文件问题、失败场景和 resume
- [x] 新增 PTY live TUI e2e 测试入口，启动真实 `python -m app.cli.main` 并模拟用户输入
- [x] TUI scenario audit 默认覆盖 `tests/scenarios` 和 `tests/e2e`
- [x] PTY live 场景扩展到多轮目录+Git、明确读文件、代码定位、危险自然语言 shell 不走本地 pending、路径查看、git diff、会话列表
- [x] TUI 只读工具面加入 `session_status`、`tool_search`、基础 `lsp`，不暴露 `process_*`
- [x] TUI 只读工具面加入 `memory_search`、`file_summary_read`，不暴露 `memory_write`
- [x] PTY live 覆盖“现在你能用哪些工具”，并断言 `session_status` / `tool_search` 来自 `openai_tool_call`
- [x] PTY live 对工具面断言要求 `session_status` 和 `tool_search` payload 都有非空证据，并检查只读工具面不暴露 `memory_write`
- [x] 新增 `tests/scenarios/tool_parity_scenarios.json`，固定 read/rg/write/multi-tool/bash/permission 的核心工具闭环场景
- [x] e2e 测试可自动读取项目根目录 `.env` 中的真实 provider 配置

当前不足：

- [ ] worker 执行、渲染和 review action 仍主要在 `MendCodeTextualApp`
- [ ] PTY live TUI 测试依赖真实 OpenAI-compatible provider 环境；本地环境变量和项目 `.env` 都未配置时会明确失败
- [ ] 工具调用不能折叠/展开
- [ ] 完整工具参数和完整输出 viewer 不足
- [ ] permission prompt 交互仍偏简单
- [ ] session picker / trace 展开界面仍偏基础
- [ ] provider health / doctor 未做 TUI surface

下一步：

- 优先扩展 PTY live TUI 用例，覆盖用户真实会问的目录、Git、文档末句、文件定位、失败恢复等问题。
- 将 parity manifest 中的核心工具场景逐步接入真实 PTY runner，而不是只停留在清单校验。
- 每个 live 用例都要断言：没有 `Provider failed`、没有可见 `trace_path`、结果来自 conversation JSONL 中的 tool/shell 证据。
- 继续把 worker 启动、completion 处理和 review action 迁到 controller 或 runtime-facing service。
- 工具结果摘要保留在聊天流；conversation log 只保留摘要、样本和 trace/workspace 指针，完整 payload 通过 trace 或后续 viewer 查看。
- 对 pending confirmation 支持 allow once / deny / change mode。
- 增加 session picker，并把 trace viewer 做成可按需展开完整 payload 的 TUI 入口。

### 3.6 Session / Trace / Conversation Log

已完成：

- [x] JSONL trace
- [x] Markdown conversation log
- [x] JSONL conversation log
- [x] `/status` 展示路径
- [x] tool/shell/chat/turn event
- [x] `tool_result` / `turn_result` 日志压缩，避免 read_file 内容和完整步骤过程淹没最终回答
- [x] ReviewSummary
- [x] AttemptRecord
- [x] ToolCallSummary
- [x] Session / CLI 能读取 enveloped `run_command` raw verification payload
- [x] `SessionStore` 扫描 `data/conversations/*.jsonl`，支持 list/latest/session-id lookup
- [x] compact resume context 包含最终回答和工具摘要，不回灌完整文件内容
- [x] `/resume [session_id]` 会把 compact context 注入后续 chat history
- [x] trace viewer helper 能读取工具事件摘要并保留完整 payload 入口
- [x] conversation compact `tool_result` 保留安全的 tool args 摘要、memory matches 样本和 session tool surface 样本，便于测试和复盘工具调用真实参数

当前不足：

- [ ] 没有 compact summary
- [ ] 没有 session health probe
- [ ] 还没有 TUI 独立 viewer 从 trace 中按需展开完整工具输出

下一步：

- 对长会话生成跨轮 compact summary，保留关键工具结果和决策。
- 把 trace viewer helper 接到 TUI 展开界面，用于查看 conversation log 中被压缩掉的完整工具 payload。

### 3.7 Layered Memory

已完成：

- [x] `app/memory/models.py` 定义 `project_fact`、`task_state`、`file_summary`、`failure_lesson`、`trace_insight` 等记录类型
- [x] `MemoryStore` 使用 `data/memory/memories.jsonl` 作为本地 JSONL 存储，支持 append、search、list 和 update
- [x] update 保留无法解析或未来 schema 的原始 JSONL 行，避免重写时丢失未知记录
- [x] 文件摘要缓存按 repo-relative path、content sha256、mtime、size、line count 和 symbols 存储
- [x] `file_summary_read` 会校验当前文件 hash，缓存过期时重建摘要
- [x] `memory_search` / `memory_write` / `file_summary_read` / `file_summary_refresh` / `trace_analyze` 已通过 ToolRegistry 暴露
- [x] `memory_write` / `file_summary_refresh` 按高风险工具处理，默认/guided 工具池不暴露，避免模型静默写长期状态
- [x] AgentLoop/runtime 创建并传递 `MemoryStore(settings.data_dir / "memory")`
- [x] `trace_analyze` 默认只读，`write_memory=True` 会拒绝，避免只读工具绕过写权限
- [x] `trace_analyze` 只能读取 `settings.traces_dir` 内的 JSONL 路径
- [x] trace analyzer 能把失败或 rejected observation 转成 `failure_lesson` 候选，并忽略最终已 completed 的恢复 trace
- [x] TUI scenario 覆盖记忆召回问题，断言 `memory_search` 的真实 compact args 和 payload

当前不足：

- [ ] 记忆召回还没有进入 system prompt 的自动 recall 阶段，当前由模型显式调用 `memory_search`
- [ ] `memory_write` 还缺少用户确认、重复记忆合并、敏感信息过滤和人工审查界面
- [ ] 文件摘要缓存没有批量 repo map，也没有和 prompt context 的重复读文件统计联动
- [ ] trace failure lesson 仍是候选生成，尚未形成“失败归因 -> prompt/skill/memory 更新”的闭环
- [ ] 还没有 SKILL.md-compatible skill 系统

下一步：

- 为 `memory_search` 增加更稳定的 ranking、recency 和 kind/tag 组合测试。
- 设计 `memory_write` 的 confirm-on-write 和去重策略，避免模型静默写入错误长期记忆。
- 将文件摘要缓存接入长会话 context compaction，减少重复读取大文件。
- 基于 trace analyzer 生成可审查的 failure lesson 列表，并在 TUI 中提供采纳/忽略入口。
- 在 memory 和 trace 稳定后，再启动 SKILL.md 系统计划。

## 4. 当前重点任务队列

### 任务 1：统一 PermissionPolicy

目标：

把 tool risk、shell policy、allowed tools、permission mode、confirmation request 统一到一个可测试策略对象。

验收：

- `read-only` / `workspace-write` / `danger-full-access` 行为清晰，旧模式仅作兼容别名
- read-only 自动允许
- read-only 下写工具直接拒绝，workspace-write 下 danger shell 走确认
- install/network/git mutate 确认
- destructive/path escape 拒绝
- permission decision 写入 observation

状态：

- 已完成基础抽取，`app.agent.permission` 现在只是兼容入口。
- AgentLoop 已把 ShellPolicy decision 交给 PermissionPolicy 做最终判断。
- 后续继续处理 pending confirmation 的用户选择回写。

### 任务 2：工具结果统一结构

目标：

让所有工具返回模型可理解、日志可复盘的统一字段。

状态：

- 基础 observation envelope 已完成。
- ToolRegistry 中的 read/list/glob/rg/search_code/git/shell/run_command/apply_patch 已接入。
- envelope 顶层保留通用字段；原始工具 payload 保留在 nested `payload`。
- 与 envelope 顶层键冲突的原始字段，例如 verification `status=passed`，从 nested `payload.status` 读取。
- AgentSession 和 CLI 已兼容 enveloped `run_command` payload。
- 后续继续收敛 legacy/builtin tool payload。

建议字段：

```text
tool_name
status
summary
is_error
payload
truncated
next_offset
stdout_excerpt
stderr_excerpt
duration_ms
```

验收：

- [x] read/list/rg/git/shell/patch 结果都能稳定进入 prompt context
- [x] 错误结果也能作为 tool result 回传模型
- [x] native tool result 只通过 OpenAI tool message 回传，不在 user context 中重复保存

### 任务 3：Mock Provider Harness

目标：

用确定性 fake provider 覆盖真实工具闭环，避免每次依赖真实模型行为。

状态：

- Mock provider harness 已完成基础版。
- 已覆盖 read_file、read_file tail_lines、list_dir、rg、多工具、shell stdout、tool error、allowed-tools denial、confirmation stop、OpenAI final_response tool call。
- 已覆盖重复等价只读工具调用保护。
- 后续继续扩展到 write 工具和 permission allow/deny。

场景：

- [ ] streaming text
- [x] read_file roundtrip
- [x] read_file tail_lines roundtrip
- [x] OpenAI final_response tool call roundtrip
- [x] rg roundtrip
- [x] multi-tool turn
- [x] shell stdout
- [ ] permission approve
- [x] permission deny / confirmation stop
- [x] tool error
- [x] plain final text after tool result
- [x] repeated equivalent read-only tool rejection

验收：

- [x] harness 能跑完整 AgentLoop
- [x] 核心场景都有 observation handoff、tool result、final response 断言

### 任务 4：真实 TUI PTY 测试系统

目标：

用 PTY 启动真实 TUI 进程，模拟用户在终端里输入自然语言问题，观察真实 provider、AgentLoop、schema 工具执行、聊天流渲染和 conversation log 的端到端行为。

状态：

- [x] 新增 `tests/e2e/test_tui_pty_live.py`
- [x] 使用 `pexpect` 启动 `python -m app.cli.main`
- [x] 每个用例在临时 Git 仓库中构造真实文件和脏工作区
- [x] 默认要求真实 OpenAI-compatible provider 环境变量，不静默 skip
- [x] 覆盖文档最后一句、当前目录查看、中文 Git 状态、多轮对话、明确读文件、代码定位、路径查看、git diff、危险自然语言命令不产生本地 shell pending、会话列表

环境要求：

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL=<model>
export MENDCODE_BASE_URL=<base-url>
export MENDCODE_API_KEY=<api-key>
```

验收：

- [x] 缺少 provider 环境时，测试明确失败并列出缺失变量
- [x] 配置真实 provider 后，live tests 能稳定通过
- [x] audit report 能把 live e2e 失败记录成可读问题
- [ ] 后续每个用户暴露的 TUI 体验问题，都先补一个 PTY live 或 `tests/scenarios` 回归用例

### 任务 5：TUI 会话恢复

目标：

让用户能查看和恢复最近会话。

验收：

- [x] `/sessions` 展示 conversation sessions
- [x] 支持 resume latest/session-id
- [x] 恢复后模型能看到 compact history
- [ ] TUI 中支持 trace payload 展开

### 任务 6：Runtime 主循环迁移

目标：

让 AgentRuntime 不再调用 `app.agent.loop._run_agent_loop_impl` 的真实实现，而是由 runtime 模块承载主循环。

状态：

- `app.runtime.agent_loop.run_agent_loop_turn` 已承载 trace-stable 主循环。
- final response gate 已抽到 `app.runtime.final_response_gate` 并有独立单测。
- `AgentRuntime._default_runner` 已改为调用 runtime loop。
- `app.agent.loop._run_agent_loop_impl` 仅保留为兼容转发入口。

下一步：

- 把 action parsing、tool invocation handling 从 `app.agent.loop` 拆到 runtime 内部模块。
- 拆分后补 provider loop/request/observation 的更细粒度单测。

### 任务 7：Layered Memory 继续演进

目标：

把当前“可显式调用的本地记忆工具”推进到“可控召回、可审查写入、可度量压缩效果”的 Runtime 能力。

验收：

- [x] 第一切片：JSONL store、file summary cache、memory tools、trace analyzer、runtime wiring、TUI 只读召回工具面
- [ ] `memory_write` 需要确认和去重
- [ ] 长会话开始前可按任务自动 recall 少量相关 memory
- [ ] prompt context 中记录 memory recall 命中和文件重复读取指标
- [ ] trace failure lesson 可在 TUI 中审查后写入 memory
- [ ] 建立 memory 相关 PTY/scenario 测试集：召回已记录事实、拒绝写入、摘要缓存过期、trace 失败归因

## 5. 测试策略

基础验证命令：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

按改动类型补测试：

- Provider 改动：`tests/unit/test_openai_compatible_provider.py`
- Prompt context 改动：`tests/unit/test_prompt_context.py`
- AgentLoop 改动：`tests/unit/test_agent_loop.py`
- ToolRegistry 改动：`tests/unit/test_tool_registry.py`
- 权限改动：`tests/unit/test_permission_gate.py`、`tests/unit/test_shell_policy.py`
- TUI 改动：`tests/unit/test_tui_app.py`、`tests/unit/test_tui_controller.py`
- TUI 体验场景测试：`tests/scenarios/` 覆盖常见用户问题，断言 route、tool evidence、简洁输出和 no-fabrication。
- TUI 真实终端测试：`tests/e2e/` 使用 PTY 启动真实 TUI 进程；默认要求真实 OpenAI-compatible provider 环境变量，缺失时应明确失败。
- TUI 巡检：`python -m app.runtime.tui_scenario_audit --report-dir data/tui-scenario-reports` 默认同时运行 `tests/scenarios` 和 `tests/e2e`。
- Memory 改动：`tests/unit/test_memory_store.py`、`tests/unit/test_file_summary_cache.py`、`tests/unit/test_memory_tools.py`、`tests/unit/test_trace_analyzer.py`、`tests/scenarios/test_tui_repository_inspection_scenarios.py::test_memory_recall_question_uses_memory_search`
- CLI 改动：`tests/integration/test_cli.py`

测试原则：

- 新行为先写失败测试，再实现。
- 不只测函数存在，要测真实闭环。
- 对“模型可能编造”的问题，测试必须断言进入 tool path，并断言 chat responder 未被调用。
- 对工具调用，测试必须断言 observation 进入下一轮 provider input。
- 对用户真实抱怨的 TUI 行为，优先补 PTY live 测试；如果真实 provider 环境不可用，至少补 fake provider 的 `run_test()` 回归，并在文档中标记 live 验证未完成。
- 对宽泛文件/代码搜索，测试必须覆盖运行产物目录不会污染普通项目事实；如需分析 `data/conversations`，必须显式指定对应路径或 glob。

## 6. 文档更新规则

每次开发后执行：

1. 如果用户可见能力变化，更新 `README.md`。
2. 如果阶段优先级或大方向变化，更新 `MendCode_全局路线图.md`。
3. 如果实现状态、接口、模块边界、测试策略或下一步任务变化，更新本文档。
4. 如果发现可复用工程问题，更新 `MendCode_问题记录.md`。

不要把所有细节都塞进路线图。路线图保持简要，本文档承载详细执行状态。

## 7. 当前已验证命令

2026-04-28 本轮 Layered Memory 第一切片和 TUI/PTY 工具面更新后，以下命令通过：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

每轮代码变更后必须重新运行，不能直接沿用本节历史记录。
