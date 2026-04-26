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

1. 运行时闭环稳定性
2. ToolRegistry 和 PermissionPolicy 收敛
3. 会话日志、trace、resume 能力
4. TUI 工具调用展示和确认交互
5. 修复链路的 patch / verify / review 体验

## 3. 当前能力状态

### 3.1 AgentLoop

已完成：

- [x] `MendCodeAction` / `Observation`
- [x] Provider-driven step loop
- [x] step budget
- [x] observation history
- [x] provider failure observation
- [x] OpenAI-compatible native `tool_calls`
- [x] JSON Action fallback
- [x] native tool invocation 执行
- [x] assistant/tool message 回填
- [x] 工具后普通文本包装为 `final_response`
- [x] final response gate 阻止失败 observation 被标记 completed
- [x] `allowed_tools` 执行期检查
- [x] deterministic mock provider harness 覆盖 native tool-call 闭环
- [x] read/list/rg/multi-tool/shell/error/allowed-tools/confirmation stop 场景测试

当前不足：

- [ ] legacy JSON action path 和 native tool path 仍有部分重复逻辑
- [ ] 没有等价只读工具调用去重
- [ ] Provider request/response 调试摘要不足
- [ ] legacy/builtin 工具结果尚未完全收敛到统一 envelope

下一步：

- 把 `_execute_tool_call` 中的 legacy 分支逐步收敛到 ToolRegistry。
- 给 AgentLoop 增加最近工具调用指纹，处理重复 `list_dir` / `read_file` / `rg`。
- 把 provider 调试摘要写入 trace，注意不要落 API key。

### 3.2 Provider

已完成：

- [x] `ScriptedAgentProvider`
- [x] `OpenAICompatibleAgentProvider`
- [x] OpenAI-compatible tools schema 发送
- [x] 原生 tool call 解析
- [x] tools unsupported fallback
- [x] tool 后普通文本 final response
- [x] API key redaction
- [x] scoped `allowed_tools`
- [x] 越权 tool call 拒绝
- [x] mock tool provider harness 覆盖 tool result 回传后的 final response
- [x] OpenAI native tool result 不再重复写入 user context，避免 prompt 中 observation 双份膨胀

当前不足：

- [ ] mock provider harness 仍需扩展到 future write tools 和 permission allow/deny resume
- [ ] 没有请求快照测试覆盖全部工具 schema
- [ ] 未实现 OpenAI 官方 adapter
- [ ] 未实现 Anthropic adapter

下一步：

- 扩展确定性 mock provider，覆盖 write 工具、权限确认恢复、tool retry 和重复调用去重。
- Provider tests 继续优先使用 fake client，不依赖真实网络。
- 后续新增 provider 时只改 adapter，不改 AgentLoop 主体。

### 3.3 ToolRegistry

已完成：

- [x] `ToolSpec`
- [x] Pydantic args model
- [x] OpenAI tools schema
- [x] `risk_level`
- [x] executor
- [x] `allowed_tools`
- [x] aliases：`read`、`list`、`glob`、`grep`、`search`、`shell`、`bash`、`patch`
- [x] shared tool observation envelope
- [x] `rg` 和 `search_code` observation 保持各自 tool identity

当前工具：

| Tool | 状态 | 说明 |
|---|---|---|
| `read_file` | 已完成 | 读取 repo-relative 文本文件，支持行范围和截断 |
| `list_dir` | 已完成 | 列目录，未截断时完整 entries 进入 prompt context |
| `glob_file_search` | 已完成 | 按 glob 查找路径 |
| `rg` / `search_code` | 已完成 | 文本搜索 |
| `git` | 已完成 | 结构化只读 git status/diff/log |
| `run_shell_command` | 已完成 | 普通 shell，走 ShellPolicy |
| `run_command` | 已完成 | 仅允许 declared verification command |
| `apply_patch` | 已完成 | 应用统一 diff |
| `repo_status` | legacy/builtin | 后续考虑 ToolRegistry 化 |
| `detect_project` | legacy/builtin | 后续考虑 ToolRegistry 化 |
| `show_diff` | legacy/builtin | 后续考虑 ToolRegistry 化 |

下一步工具：

- [ ] `write_file`：默认仅 worktree，写前检查路径和权限
- [ ] `edit_file`：精确替换或小 patch block
- [ ] `todo_write`：记录 Agent 当前短期计划
- [ ] `tool_search`：让模型查询可用工具能力
- [ ] `session_status`：返回当前会话、权限、工具集、workspace 状态

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

- [x] `PermissionMode`: Safe / Guided / Full / Custom
- [x] `PermissionDecision`
- [x] risk level 从 ToolRegistry 派生
- [x] shell low-risk 自动执行
- [x] shell 写入/安装/网络/git mutate 确认
- [x] critical destructive 和 path escape 拒绝
- [x] TUI pending shell confirmation
- [x] stdout-only `printf` 低风险允许，重定向仍需确认

当前不足：

- [ ] PermissionPolicy 仍不是独立对象
- [ ] 工具确认和 shell 确认还没有完全统一
- [ ] allow once / deny / change mode 回写不完整
- [ ] Custom mode 未配置化

下一步：

- 抽出 `PermissionPolicy`，输入 tool spec、mode、shell decision、workspace context，输出 allow/confirm/deny。
- 确认结果要形成 observation 并回传模型。
- 所有写主工作区、安装、网络、commit、push、reset、checkout 都必须有测试覆盖。

### 3.5 TUI

已完成：

- [x] TUI 启动
- [x] `/status`
- [x] chat / fix / shell / tool intent
- [x] shell 自动执行和 pending confirmation
- [x] tool request 进入 AgentLoop
- [x] tool result 摘要展示
- [x] conversation Markdown / JSONL 写入，并对 `tool_result` / `turn_result` 做 compact 摘要
- [x] review actions：view diff / view trace / apply / discard

当前不足：

- [ ] 工具调用不能折叠/展开
- [ ] 完整工具参数和完整输出 viewer 不足
- [ ] permission prompt 交互仍偏简单
- [ ] session list / resume 未实现
- [ ] provider health / doctor 未做 TUI surface

下一步：

- 工具结果摘要保留在聊天流；conversation log 只保留摘要、样本和 trace/workspace 指针，完整 payload 通过 trace 或后续 viewer 查看。
- 对 pending confirmation 支持 allow once / deny / change mode。
- 增加 session picker 和 resume latest。

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

当前不足：

- [ ] 没有会话索引
- [ ] 没有 resume latest/session-id
- [ ] 没有 compact summary
- [ ] 没有 session health probe
- [ ] 还没有独立 viewer 从 trace 中按需展开完整工具输出

下一步：

- 为 `data/conversations` 增加轻量索引或扫描器。
- 支持按 latest 或 session id 恢复上下文。
- 对长会话生成跨轮 compact summary，保留关键工具结果和决策。
- 增加 trace viewer，用于查看 conversation log 中被压缩掉的完整工具 payload。

## 4. 当前重点任务队列

### 任务 1：统一 PermissionPolicy

目标：

把 tool risk、shell policy、allowed tools、permission mode、confirmation request 统一到一个可测试策略对象。

验收：

- Safe / Guided / Full / Custom 行为清晰
- read-only 自动允许
- write/install/network/git mutate 确认
- destructive/path escape 拒绝
- permission decision 写入 observation

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
- 已覆盖 read_file、list_dir、rg、多工具、shell stdout、tool error、allowed-tools denial、confirmation stop。
- 后续继续扩展到 write 工具、permission allow/deny resume 和重复只读工具调用。

场景：

- [ ] streaming text
- [x] read_file roundtrip
- [x] rg roundtrip
- [x] multi-tool turn
- [x] shell stdout
- [ ] permission approve
- [x] permission deny / confirmation stop
- [x] tool error
- [x] plain final text after tool result

验收：

- [x] harness 能跑完整 AgentLoop
- [x] 核心场景都有 observation handoff、tool result、final response 断言

### 任务 4：TUI 会话恢复

目标：

让用户能查看和恢复最近会话。

验收：

- `/status` 展示 latest conversation
- 支持 session list
- 支持 resume latest
- 恢复后模型能看到 compact history

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
- TUI 改动：`tests/unit/test_tui_app.py`、`tests/unit/test_tui_intent.py`
- CLI 改动：`tests/integration/test_cli.py`

测试原则：

- 新行为先写失败测试，再实现。
- 不只测函数存在，要测真实闭环。
- 对“模型可能编造”的问题，测试必须断言进入 tool path，并断言 chat responder 未被调用。
- 对工具调用，测试必须断言 observation 进入下一轮 provider input。

## 6. 文档更新规则

每次开发后执行：

1. 如果用户可见能力变化，更新 `README.md`。
2. 如果阶段优先级或大方向变化，更新 `MendCode_全局路线图.md`。
3. 如果实现状态、接口、模块边界、测试策略或下一步任务变化，更新本文档。
4. 如果发现可复用工程问题，更新 `MendCode_问题记录.md`。

不要把所有细节都塞进路线图。路线图保持简要，本文档承载详细执行状态。

## 7. 当前已验证命令

最近一次文档整理前，以下命令通过：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

每轮代码变更后必须重新运行，不能直接沿用本节历史记录。
