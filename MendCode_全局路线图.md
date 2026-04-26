# MendCode 全局路线图

## 1. 文档目的

本文档只回答一个问题：

`后续开发如何始终朝最新 TUI Code Agent 产品形态推进。`

所有产品判断以根目录下的 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 为准。本文档不再维护旧 fixed-flow、CLI-first、batch-eval-first 的路线。

开发清单机制：

- 使用 Markdown checkbox 表示路线状态。
- `[ ]` 表示尚未完成或尚未验证。
- `[x]` 表示已经完成并通过对应测试或验证。
- 每完成一项功能，必须同步更新本文档、[MendCode_开发方案.md](/home/wxh/MendCode/MendCode_开发方案.md)、[MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 中的对应清单。
- 只有代码落地并有验证证据的项目才能勾选。

---

## 2. 当前最终目标

MendCode 的最终入口是：

```bash
mendcode
```

用户进入 TUI 后，用自然语言描述问题。Agent 根据上下文自主调用工具、读取结果、决定下一步动作，并在隔离 worktree 中完成修复、验证和工程审查收尾。

一句话目标：

`MendCode 是面向本地代码仓的可验证修复型 TUI Code Agent。`

核心原则：

- [x] 聊天优先
- [x] 动态工具调用底座
- [ ] 摘要优先，详情可展开
- [x] 默认 Guided Mode
- [x] 修改先进入隔离 worktree
- [x] 没有验证结果不声称修复完成
- [ ] 用户最终决定 apply / discard / commit

---

## 3. 当前项目真实状态

截至 2026-04-26，项目已经完成的是底座能力，不是最终产品形态：

- [x] Typer CLI 基础入口
- [x] `MendCodeAction` / `Observation` schema
- [x] `ScriptedAgentProvider` provider 边界
- [x] Agent loop runner
- [x] Provider-driven next-action loop
- [x] Hybrid ToolRegistry / OpenAI 原生 tool call 支持；JSON Action 保留为 fallback
- [x] Git worktree 隔离
- [x] command policy / executor
- [x] shell policy / executor
- [x] TUI 自然语言工具请求进入 AgentLoop，由模型选择结构化工具并回传 observation
- [x] `repo_status` / `detect_project`
- [x] `read_file` / `search_code`
- [x] `run_shell_command`
- [x] 自然语言 shell 意图识别和 TUI 执行流
- [x] shell pending confirmation
- [x] worktree patch proposal 执行
- [x] verification command 执行
- [x] diff summary
- [x] JSONL trace
- [x] TUI 会话日志写入 `data/conversations/*.md` 与 `*.jsonl`
- [x] `mendcode fix "<problem>" --test "<command>"` 过渡入口
- [x] pytest 风格失败日志解析
- [x] `ReviewSummary` 会话审查摘要模型
- [x] `AttemptRecord` 失败尝试记录模型
- [x] TUI review action 菜单：`view_diff` / `view_trace` / `apply` / `discard`
- [x] `run_command` 收敛为 verification-only 工具

这些能力的定位：

`TUI Agent 的安全执行底座和早期验证切片。`

不要再把它们包装成最终产品主线。

---

## 4. 已废弃或降级的旧路线

以下旧方向不再作为主线：

- [x] 移除 `mendcode task run <json>` 作为主要用户入口
- [x] 移除手工文本替换补丁作为主要任务表达方式
- [x] 移除 fixed-flow demo 产品核心体验
- [x] 暂停补更多 demo suite
- [x] 暂停 batch eval 平台
- [x] 暂停 API 服务化
- [x] 暂停复杂 Web UI
- [x] 暂停多 Agent 编排

当前处理原则：

- [x] 旧 task JSON、fixed-flow demo、batch eval、API 服务入口已从主线代码移除。
- [x] 后续如需回归验证，围绕 Agent loop 新建 fixture，不恢复旧产品入口。
- [x] 如果 eval 与 TUI Agent loop 抢资源，优先推进 TUI Agent loop。

---

## 5. 新主线

后续路线统一为：

`TUI 输入 -> Agent Action Loop -> Permission Gate -> Tool Execution -> Observation -> Patch Proposal -> Worktree Verification -> Engineering Review -> Apply/Discard`

这条链路比旧路线更重要：

`task JSON -> fixed-flow patch -> verification`

---

## 6. 阶段路线

### Phase A：Agent Loop 底座

目标：

让系统具备模型驱动的动态工具调用基础，而不是固定流程。

交付：

- [x] `MendCodeAction` schema
- [x] `Observation` schema
- [x] `assistant_message` / `tool_call` / `patch_proposal` / `user_confirmation_request` / `final_response`
- [x] Action 解析与校验
- [x] Action trace 事件
- [x] step budget
- [x] 非法 Action 的分级降级

停手点：

- [x] 能在无 TUI 的测试中模拟一轮 `tool_call -> observation -> next action`
- [x] 非法 action 不会让系统崩溃

当前状态：

- [x] `MendCodeAction` schema 已落地
- [x] `Observation` schema 已落地
- [x] 合法 tool call 可解析
- [x] 未知工具会被 schema 拒绝
- [x] 非法 action 可转换为 rejected observation
- [x] action / observation 可写入 trace payload

Phase A 已完成。

### Phase B：Permission Gate

目标：

把 Safe / Guided / Full / Custom 权限模式落成可执行策略。

交付：

- [x] 权限模式 schema
- [x] 工具风险等级
- [x] permission decision
- [x] 中高风险动作确认请求
- [x] 默认 Guided Mode

停手点：

- [x] `read_file` / `search_code` 可自动通过
- [ ] `apply to workspace` 必须确认
- [x] 未授权工具能形成清晰 observation

当前状态：

- [x] Permission Gate 最小实现已落地
- [x] Safe / Guided / Full / Custom 模式已定义
- [x] 首批工具风险等级已定义
- [x] Guided Mode 已允许只读工具、验证命令和 worktree patch
- [x] Safe Mode 对中风险工具返回确认请求
- [x] 确认请求已统一为 `user_confirmation_request` action
- [x] Permission Gate 已接入 Agent loop

### Phase C：LLM Provider 抽象

目标：

支持 OpenAI、Anthropic、OpenAI-compatible，并统一归一化为 MendCode Action。

交付：

- [x] `ScriptedAgentProvider` provider 边界
- [x] provider step input / observation history
- [x] Provider env 配置 schema
- [ ] OpenAI adapter
- [ ] Anthropic adapter
- [x] OpenAI-compatible adapter
- [x] JSON Action fallback
- [x] provider 错误降级
- [x] provider-driven loop 错误降级
- [x] provider prompt context / repair contract
- [x] ToolRegistry primitives 与 Pydantic args models
- [x] OpenAI-compatible provider 可发送 tools schema 并解析原生 `tool_calls`
- [x] prompt context 可把原生 tool observation 写回 OpenAI assistant/tool message
- [x] Agent loop 可顺序执行原生 `ToolInvocation`，并保留 JSON Action fallback

验证证据：

- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q`
- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .`

停手点：

- [x] CLI 不直接硬编码 action 列表
- [x] 业务层可处理 provider failure observation
- [x] provider 可基于 observation history 逐步返回下一条 MendCode Action
- [x] 业务层只处理真实 provider 归一化后的 MendCode Action，不直接依赖厂商 tool calling 格式
- [x] provider prompt context 支持 bounded summary 和 secret redaction

### Phase D：Tool Execution 与检索增强

目标：

让 Agent 能根据 observation 自主继续定位问题。

交付：

- [x] `repo_status`
- [x] `detect_project`
- [x] `run_command`，仅用于声明过的验证命令
- [x] `run_shell_command`，用于普通低风险诊断命令
- [x] shell policy / executor
- [x] `read_file`
- [x] `list_dir`
- [x] `glob_file_search`
- [x] `rg`
- [x] `git`
- [x] `apply_patch`
- [x] fake provider 修复闭环验证
- [x] `search_code`
- [x] 失败测试文件读取
- [x] 基于 failed node / test name / rg 的候选文件检索

停手点：

- [x] 用户描述“pytest 失败”后，过渡入口能运行测试并解析失败
- [x] 用户描述“pytest 失败”后，Agent 能读取测试文件、搜索候选实现
- [x] 用户输入 `ls`、`git status` 或“列一下当前目录”后，TUI 能自动运行安全 shell 并展示摘要
- [x] 高风险 shell 命令会进入确认状态，不立即执行

### Phase E：Patch Proposal 与验证闭环

目标：

让 Agent 能提出补丁，在 worktree 中应用，并用验证命令证明结果。

交付：

- [x] patch proposal schema
- [x] patch apply to worktree
- [x] diff summary
- [x] verification gate
- [x] failed attempt record
- [ ] max_attempts retry
- [ ] failed patch trace

停手点：

- [x] 修复通过时能输出 changed files、diff summary、verification result
- [ ] 修复失败时能在 TUI/CLI 中输出尝试记录和下一步选项

### Phase F：TUI MVP

目标：

实现最终主入口：

```bash
mendcode
```

交付：

- [ ] 启动轻量 repo scan
- [x] 聊天输入
- [x] 自然语言工具请求输入
- [x] 自然语言 shell 查询输入
- [x] Guided Mode 默认权限
- [x] 工具调用摘要展示
- [x] 本地可读会话日志
- [ ] 详情展开
- [x] 工程审查收尾
- [x] view diff / trace / apply / discard
- [ ] 独立 logs viewer

停手点：

- [x] 用户可以在 TUI 中描述一个 pytest 失败问题
- [x] Agent 能通过测试驱动 action 完成一次 worktree 内修复尝试
- [x] 用户能基于审查摘要决定 apply 或 discard

当前接续点：

- [x] `AgentSession.run_turn()` 单轮会话抽象
- [x] `session.turns` 持续追加，为后续多轮聊天保留状态
- [x] TUI shell confirmation 与 `/status` pending shell 状态

---

## 7. 暂缓事项

第一版 TUI Agent MVP 不做：

- [ ] 多任务并行
- [ ] 后台长期任务
- [ ] 多仓库切换
- [ ] 复杂布局拖拽
- [ ] 完整配置 UI
- [ ] 项目记忆自动写入
- [ ] commit / push 自动化
- [ ] 复杂 diff viewer
- [ ] 本地模型
- [ ] 多 provider 深度适配
- [ ] 企业权限系统
- [ ] GitHub PR 自动化

---

## 8. 每轮开发前判断

每轮开始前只问五个问题：

1. 这项工作是否推进 TUI Agent 主线？
2. 它是否服务 `Action loop -> Permission gate -> Tool execution -> Observation -> Patch -> Verification`？
3. 它是否减少用户手写补丁或手动定位的负担？
4. 它是否保持 worktree 隔离和用户确认边界？
5. 它是否与 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 一致？

如果答案不清楚，就先不要做。
