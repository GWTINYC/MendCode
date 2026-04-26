# MendCode 开发方案

## 1. 产品定位

MendCode 是运行在本地仓库中的 TUI Code Agent。用户用自然语言描述目标，系统通过模型驱动的工具调用读取仓库、执行安全命令、生成补丁、验证结果，并把全过程保存为可复盘的本地会话。

第一阶段不追求“功能大而全”，而是把 Agent 运行时做扎实：

- 原生工具调用是主路径，JSON Action 是 fallback。
- 工具定义、权限风险、执行结果都结构化。
- 低风险查询自动执行，写入、安装、网络、破坏性操作受权限策略约束。
- 每次工具调用都形成 observation，并进入下一轮模型上下文。
- 每轮对话都落盘，能从日志复盘意图、工具、结果和最终回答。

## 2. 运行时主线

当前主线是：

```text
TUI 输入
-> Intent Router
-> AgentLoop
-> Provider
-> ToolRegistry/OpenAI tools schema
-> PermissionPolicy
-> Tool Executor
-> Observation
-> 下一轮 Provider
-> Final Response
-> Conversation Log / Trace
```

关键约束：

- 模型只决定“要调用什么工具”和“如何基于结果回答”。
- MendCode 负责工具白名单、权限判断、路径边界、执行、截断、日志和验证。
- 任何本地事实问题，如目录、文件、代码、Git 状态，必须走工具路径，不能让普通聊天直接编造。
- 修复类任务必须用 worktree 或明确的补丁边界隔离主工作区。

## 3. 已落地能力

### Agent loop

- [x] `MendCodeAction` / `Observation` 内部协议
- [x] Provider-driven loop
- [x] OpenAI-compatible 原生 `tool_calls`
- [x] JSON Action fallback
- [x] Native tool result 写回 assistant/tool message
- [x] 工具后普通文本可包装为 `final_response`
- [x] final gate 会阻止失败 observation 被错误标记为 completed

### ToolRegistry

- [x] Pydantic args model 生成 OpenAI tools schema
- [x] `allowed_tools` scoped tools
- [x] 工具别名归一：`read`、`glob`、`grep`、`shell` 等
- [x] 未知工具和越权工具拒绝执行
- [x] 工具风险等级作为 PermissionPolicy 的来源

当前工具集：

- [x] `read_file`
- [x] `list_dir`
- [x] `glob_file_search`
- [x] `rg` / `search_code`
- [x] `git` 只读操作
- [x] `run_shell_command`
- [x] `run_command`，仅用于已声明 verification command
- [x] `apply_patch`
- [x] `repo_status`
- [x] `detect_project`
- [x] `show_diff`

### TUI

- [x] `mendcode` 启动 TUI
- [x] 自然语言 chat / fix / shell / tool intent
- [x] `ls`、`pwd`、`git status`、`git diff`、`rg` 等低风险 shell 自动执行
- [x] 危险 shell 进入 pending confirmation
- [x] 自然语言目录/文件请求进入工具 Agent
- [x] 工具结果摘要展示在聊天流
- [x] `/status` 展示会话和 pending shell 状态
- [x] 会话保存到 `data/conversations/*.md` 和 `*.jsonl`

### 安全与验证

- [x] Safe / Guided / Full / Custom 权限模式
- [x] shell policy 区分只读、写入、安装、网络、git mutate、路径逃逸和破坏性命令
- [x] `run_command` 与普通 shell executor 分离
- [x] worktree patch 和验证闭环
- [x] pytest 失败解析
- [x] ReviewSummary / AttemptRecord / ToolCallSummary
- [x] TUI review actions：view diff / view trace / apply / discard

## 4. 设计原则

### 工具优先，而不是命令行拼接优先

能用结构化工具表达的动作，不让模型直接写 shell：

- 文件读取用 `read_file`
- 目录查看用 `list_dir`
- 路径发现用 `glob_file_search`
- 文本搜索用 `rg` / `search_code`
- Git 查询用结构化 `git`
- shell 只用于没有结构化工具覆盖的诊断动作

### 权限策略集中

新增工具时必须同步：

- ToolRegistry spec
- args schema
- risk level
- executor
- prompt contract
- permission 测试
- native tool path 测试

不要在多个模块复制风险等级或工具白名单。

### 运行时负责闭环

Provider 不可信任为唯一安全边界。即使 provider 已经裁剪 tools schema，AgentLoop 仍必须在执行前检查：

- 工具是否存在
- 工具是否在 `allowed_tools`
- 权限模式是否允许
- shell policy 是否允许
- 路径是否在 workspace 内

### 会话可恢复、可审计

每轮对话至少保留：

- 用户输入
- intent decision
- provider request 关键上下文
- tool calls
- observations
- final response
- 错误和权限拒绝

后续 resume、debug、质量评估都基于这些日志，而不是依赖终端画面。

## 5. 下一步开发重点

### 5.1 Runtime 稳定性

- [ ] 抽出独立 `PermissionPolicy` 对象，统一 ToolRegistry risk、shell policy、确认规则
- [ ] 将 legacy JSON action 工具执行逐步迁移到 ToolRegistry executor
- [ ] 增加等价只读工具调用去重，避免模型重复 `list_dir` / `read_file`
- [ ] 给工具结果增加统一字段：`tool_name`、`status`、`summary`、`payload`、`truncated`、`is_error`

### 5.2 工具能力

- [ ] `write_file`，默认仅允许 worktree
- [ ] `edit_file`，基于精确替换或 patch block
- [ ] `todo_write`，记录 Agent 内部短期计划
- [ ] `tool_search`，让模型按能力发现可用工具
- [ ] `session_status`，返回当前会话、权限、工具集和 workspace 状态

### 5.3 Provider 与测试

- [ ] 增加更完整的 OpenAI-compatible mock harness
- [ ] 覆盖 read_file、rg、multi-tool、permission approve/deny、tool error、plain final text
- [ ] 记录每个 provider 请求的 tools schema 快照
- [ ] 后续再考虑 OpenAI 官方 adapter 和 Anthropic adapter

### 5.4 TUI 体验

- [ ] 工具调用折叠/展开
- [ ] 工具参数和完整输出 viewer
- [ ] 会话列表与 resume
- [ ] diff viewer 分页
- [ ] permission prompt 的 allow once / deny / change mode

## 6. 验证命令

每轮代码改动至少运行：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

涉及 TUI、工具调用、权限或 provider 的改动，必须补对应单测，不只做手工验证。
