# MendCode 开发方案

## 1. 文档目的

本文档是当前开发执行方案。所有产品定义以 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 为准。

旧方案中的 CLI-first、fixed-flow-first、batch-eval-first 内容已清理，不再作为当前开发主线。

开发清单机制：

- 使用 Markdown checkbox 维护开发状态。
- `[ ]` 表示计划中或尚未完成。
- `[x]` 表示代码已落地，并已通过对应测试或验证。
- 每完成一项功能，必须在本文件、[MendCode_全局路线图.md](/home/wxh/MendCode/MendCode_全局路线图.md)、[MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 中同步勾选对应条目。
- 只讨论过但没有代码和验证证据的事项不能勾选。

---

## 2. 当前产品目标

MendCode 的目标形态：

`终端里的本地 Code Agent 工作台。`

用户通过：

```bash
mendcode
```

进入 TUI，用自然语言描述问题。Agent 通过动态工具调用完成排障、修复、验证和审查收尾。

---

## 3. 当前已完成能力

截至 2026-04-26，已完成能力主要是新 TUI Agent 路线的底座：

- [x] CLI 基础命令
- [x] `MendCodeAction` / `Observation` 动作协议
- [x] 最小 `AgentLoop`
- [x] `ScriptedAgentProvider`，用于在真实 LLM provider 前逐步生成 MendCode actions
- [x] Provider-driven Agent loop：每步基于 observation history 请求下一条 action
- [x] OpenAI-compatible JSON Action provider
- [x] Hybrid ToolRegistry / OpenAI 原生 tool call 支持；JSON Action 保留为 fallback
- [x] Provider prompt context 与修复契约
- [x] fake provider 修复闭环：patch proposal -> worktree apply -> verify -> diff -> final
- [x] worktree 内 patch proposal 执行
- [x] verification gate：最后一次关键 observation 未成功时不能 completed
- [x] Permission Gate
- [x] Safe / Guided / Full / Custom 权限模式
- [x] worktree 隔离
- [x] command policy / executor
- [x] verification command 执行
- [x] 普通 shell command policy / executor
- [x] TUI 自然语言 shell 意图识别
- [x] Guided Mode 下低风险 shell 查询自动执行
- [x] 高风险 shell 命令进入确认状态
- [x] Agent loop `run_shell_command` 工具
- [x] `run_command` 保持 verification-only 语义
- [x] JSONL trace
- [x] `read_file`
- [x] `search_code`
- [x] `apply_patch_to_worktree` 底层 patch helper
- [x] `mendcode fix "<problem>" --test "<command>"` 过渡入口，已在隔离 worktree 中执行
- [x] pytest 失败日志解析
- [x] `ReviewSummary` 会话审查摘要模型
- [x] `AttemptRecord` 失败尝试记录模型
- [x] 自然语言 shell 查询：`ls` / `pwd` / `git status` / `git diff` / `rg` / `cat` / `head` / `tail` / `find`
- [x] shell 命令结果在 TUI 聊天流中展示命令、cwd、退出码、风险等级和输出摘要

已删除的旧主线：

- [x] 删除 task JSON 入口
- [x] 删除固定流程补丁 demo
- [x] 删除 batch eval 平台
- [x] 删除 HTTP health API
- [x] 删除 demo task suite 产品数据

这些删除是为了让后续开发只围绕 TUI Agent 主线推进。

---

## 4. 当前主要缺口

距离 TUI Agent MVP 还缺：

- [x] LLM Provider 抽象底座
- [x] OpenAI-compatible JSON Action adapter
- [x] OpenAI 原生 tool-call registry 支持
- [ ] Anthropic 原生 adapter
- [x] Provider 错误降级为 observation
- [x] Provider-driven 动态 tool-use loop 底座
- [x] 真实 provider 的 prompt/action 契约底座
- [ ] 真实模型端到端修复稳定性验证
- [x] patch proposal schema
- [x] 真实 LLM 可通过 OpenAI tool calls 调用结构化工具，JSON Action 保留为 fallback
- [ ] 真实 LLM 输出 patch proposal 稳定性验证
- [x] diff summary 与 TUI review 收尾
- [x] 最小单轮 TUI-shaped 入口
- [x] 工具调用摘要展示
- [x] apply / discard 收尾动作
- [x] 自然语言 shell 工具调用
- [x] shell pending confirmation 状态
- [x] `/status` 展示 pending shell 状态

---

## 5. 开发原则

后续开发遵循：

- 先底座，后 TUI 外壳
- 先 Action loop，后复杂模型能力
- 先 Guided Mode，后 Full / Custom
- 先 worktree 修改，后主工作区 apply
- 先 diff summary，后完整 diff viewer
- 先 OpenAI / Anthropic / OpenAI-compatible 抽象，后更多 provider 细节
- 先单任务，后多任务

禁止重新回到：

- 让用户提供手工文本替换补丁
- 让 JSON task 成为主要用户入口
- 继续扩固定流程 demo 当产品主线
- 先做复杂 UI 而不做 Agent loop
- 先做多 Agent、平台化 eval 或企业权限

说明：

- 旧 task JSON、固定流程 demo、batch eval、API 服务化入口已经从主线代码中删除。
- 后续如需回归验证，应围绕 Agent loop 重新建立测试 fixture，不恢复旧产品入口。

---

## 6. 阶段一：Action 协议与 Observation

目标：

把模型输出统一成 MendCode 内部动作，不让业务层直接依赖不同 provider 的 tool calling 格式。

交付：

- [x] `MendCodeAction`
- [x] `ActionType`
- [x] `ToolCallAction`
- [x] `PatchProposalAction`
- [x] `ConfirmationRequestAction`
- [x] `FinalResponseAction`
- [x] `Observation`
- [x] action validation
- [x] action trace payload

验收：

- [x] 能解析一个合法 `search_code` action
- [x] 非法 action 能返回结构化错误
- [x] action 和 observation 都能写入 trace

当前进展：

- [x] 已新增 `app/schemas/agent_action.py`
- [x] 已定义 `MendCodeAction` 统一动作协议
- [x] 已支持 `assistant_message` / `tool_call` / `patch_proposal` / `user_confirmation_request` / `final_response`
- [x] 已定义 `Observation`
- [x] 已提供 `parse_mendcode_action`
- [x] 已提供 `build_invalid_action_observation`
- [x] 已通过单测覆盖合法 action、未知工具拒绝、非法 action observation 和 trace payload 序列化

下一步应进入阶段二：

`PermissionMode -> tool risk level -> permission decision -> confirmation request`

---

## 7. 阶段二：Permission Gate

目标：

把权限模式从产品设定落成工程机制。

交付：

- [x] `PermissionMode`: Safe / Guided / Full / Custom
- [x] 工具风险等级
- [x] permission decision
- [x] deny / confirm / allow
- [x] 默认 Guided Mode

验收：

- [x] Guided Mode 自动允许只读工具
- [x] Guided Mode 允许 worktree patch
- [ ] Guided Mode 对主工作区 apply 返回确认请求
- [x] 未授权工具不执行，并形成 observation

当前进展：

- [x] 已新增 `app/agent/permission.py`
- [x] 已定义 `PermissionMode`: Safe / Guided / Full / Custom
- [x] 已定义 `PermissionDecision`
- [x] 已建立首批工具风险等级
- [x] Guided Mode 已允许只读工具、`run_command` 和 worktree patch
- [x] Safe Mode 会对中风险工具返回确认请求
- [x] Full Mode 允许已知工具
- [x] Custom Mode 默认要求显式配置
- [x] 已支持把需要确认的 tool call 转成 `user_confirmation_request`
- [x] 已接入最小 Agent loop，能把需要确认的工具转成 confirmation action 和 rejected observation

当前尚未完成：

- [ ] 主工作区 apply 的独立 action 和高风险判定
- [ ] 用户确认结果回写 observation
- [ ] 自定义权限配置文件

下一步应进入阶段三或先补阶段四前置：

`Agent loop runner -> permission decision -> tool execution/confirmation observation`

---

## 8. 阶段三：LLM Provider 抽象

目标：

支持 OpenAI、Anthropic、OpenAI-compatible，并统一输出 MendCode Action。

当前先保留 `ScriptedAgentProvider` 作为 provider 边界，CLI 不再直接硬编码 action 列表。Agent loop 已能每步把 observation history 交回 provider 并请求下一条 MendCode Action。后续真实 provider 只需要替换 action 生成层，不改 Agent loop 主体。

交付：

- [x] Provider env config
- [x] OpenAI adapter 原生 tool-call registry 支持
- [ ] Anthropic adapter
- [x] OpenAI-compatible adapter
- [x] JSON action fallback
- [x] provider error observation
- [x] provider step input / observation history
- [x] prompt context summary / repair contract

验收：

- [x] CLI 只消费 provider 生成的 MendCode actions
- [x] 业务层可消费 provider 结构化响应并处理 provider failure observation
- [x] provider failure 可降级为 failed observation
- [x] 切换 provider 不影响 Agent loop 主体
- [x] 业务层只消费真实 provider 归一化后的 MendCode Action
- [x] API key 不写入项目仓库，provider prompt 支持 secret redaction
- [x] OpenAI-compatible provider 可发送 ToolRegistry 生成的 tools schema，并解析原生 `tool_calls`
- [x] Prompt context 可把原生 tool observation 写回 OpenAI assistant/tool message
- [x] JSON Action 仍作为不支持原生 tool call 或模型降级时的 fallback

验证证据：

- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q`
- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .`

---

## 9. 阶段四：动态 Tool-use Loop

目标：

实现“观察 -> 决策 -> 工具 -> observation -> 再决策”的循环。

交付：

- [x] Agent loop runner
- [x] Provider-driven next-action loop
- [x] step budget
- [x] worktree execution context
- [x] observation history
- [x] trace event
- [x] ToolRegistry primitives 与 Pydantic args models
- [x] Agent loop 可顺序执行原生 `ToolInvocation`，同时保留 JSON Action fallback 与 legacy JSON git 兼容

首批工具：

- [x] `repo_status`
- [x] `detect_project`
- [x] `run_command`，仅用于已声明 verification command
- [x] `run_shell_command`，用于普通低风险诊断命令
- [x] `read_file`
- [x] `list_dir`
- [x] `glob_file_search`
- [x] `rg`
- [x] `git`
- [x] `search_code`
- [x] `apply_patch_to_worktree`
- [x] `apply_patch`
- [x] `show_diff`

验收：

- [x] 用户描述 pytest 失败后，过渡入口能在隔离 worktree 中运行验证、解析失败并留下 trace
- [x] 用户描述 pytest 失败后，过渡入口能自动读取失败测试文件
- [x] 用户描述 pytest 失败后，过渡入口能执行基于失败测试名的 `search_code`
- [x] 测试驱动的 Agent loop 能在 worktree 中应用 patch proposal、复跑验证、输出 diff summary
- [x] fake provider 修复链路能完成 patch、验证、diff 和 final response
- [x] Agent loop 中 `run_shell_command` 可执行低风险命令并形成 observation
- [x] `run_command` 会拒绝未声明的 verification command

---

## 10. 阶段五：Patch 与验证闭环

目标：

让 Agent 能提出补丁，在 worktree 中应用，并验证结果。

交付：

- [x] patch proposal schema
- [x] apply patch to worktree
- [x] diff summary
- [x] verification gate
- [x] failed attempt record
- [ ] max_attempts retry
- [ ] failed attempt trace

验收：

- [x] 修复成功时输出 changed files、diff summary、verification result
- [ ] 修复失败时在 TUI/CLI 中输出尝试记录和下一步选项
- [x] 未验证通过时不能声称修复完成

---

## 11. 阶段六：TUI MVP

目标：

实现最终主入口：

```bash
mendcode
```

交付：

- [ ] 启动轻量 repo scan
- [x] 聊天输入
- [x] 自然语言 shell 查询输入
- [x] Guided Mode 默认权限
- [x] 工具调用摘要展示
- [ ] 详情展开
- [x] 工程审查收尾
- [x] view diff / trace / apply / discard
- [ ] 独立 logs viewer

验收：

- [x] 用户可以在 TUI 中描述问题
- [x] Agent 能完成一次 worktree 内修复尝试
- [x] 用户可以基于工程审查摘要决定 apply 或 discard
- [x] 用户不需要写 JSON
- [x] 用户不需要提供手工文本替换补丁
- [x] Agent 每一步工具调用都有摘要
- [x] 修复结果必须有验证命令证明
- [x] 用户输入 `ls`、`git status` 或“列一下当前目录”时能自动运行安全命令并展示摘要
- [x] 用户输入危险 shell 命令时，TUI 先进入确认状态，不立即执行

---

## 12. 当前过渡入口的定位

当前已有：

```bash
mendcode fix "<problem>" --test "<command>"
```

该入口只作为过渡能力保留，用于沉淀：

- [x] `problem_statement`
- [x] verification execution
- [x] failure parser
- [x] trace
- [x] worktree safety
- [x] session result models: `ReviewSummary` / `AttemptRecord`

当前接续点：

- [x] `AgentSession.run_turn()` 单轮会话抽象
- [x] `session.turns` 持续追加，为后续多轮聊天保留状态

后续不要继续把它扩展成完整产品。新增能力应优先服务 TUI Agent 主线。

---

## 13. 文档维护规则

后续每轮开发都要同步更新：

- [ ] [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md)：产品设定变化时更新
- [ ] [MendCode_开发方案.md](/home/wxh/MendCode/MendCode_开发方案.md)：执行路线变化时更新
- [ ] [MendCode_全局路线图.md](/home/wxh/MendCode/MendCode_全局路线图.md)：阶段优先级变化时更新
- [ ] [MendCode_问题记录.md](/home/wxh/MendCode/MendCode_问题记录.md)：记录真实问题和解决方案

如果其它文档与 TUI 产品方案冲突，以 TUI 产品方案为准。
