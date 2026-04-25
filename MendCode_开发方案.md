# MendCode 开发方案

## 1. 文档目的

本文档是当前开发执行方案。所有产品定义以 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 为准。

旧方案中的 CLI-first、fixed-flow-first、batch-eval-first 内容已清理，不再作为当前开发主线。

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

截至 2026-04-25，已完成能力主要是新 TUI Agent 路线的底座：

- CLI 基础命令
- `MendCodeAction` / `Observation` 动作协议
- 最小 `AgentLoop`
- worktree 内 patch proposal 执行
- verification gate：最后一次关键 observation 未成功时不能 completed
- Permission Gate
- Safe / Guided / Full / Custom 权限模式
- worktree 隔离
- command policy / executor
- verification command 执行
- JSONL trace
- `read_file`
- `search_code`
- `apply_patch_to_worktree` 底层 patch helper
- `mendcode fix "<problem>" --test "<command>"` 过渡入口，已在隔离 worktree 中执行
- pytest 失败日志解析

已删除的旧主线：

- task JSON 入口
- 固定流程补丁 demo
- batch eval 平台
- HTTP health API
- demo task suite 产品数据

这些删除是为了让后续开发只围绕 TUI Agent 主线推进。

---

## 4. 当前主要缺口

距离 TUI Agent MVP 还缺：

- LLM Provider 抽象
- OpenAI / Anthropic / OpenAI-compatible adapter
- 真实模型驱动的动态 tool-use loop
- patch proposal schema
- 真实 LLM 输出 patch proposal
- diff summary 与 TUI review 收尾
- TUI 聊天界面
- 工具调用摘要展示
- apply / discard 收尾动作

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

- `MendCodeAction`
- `ActionType`
- `ToolCallAction`
- `PatchProposalAction`
- `ConfirmationRequestAction`
- `FinalResponseAction`
- `Observation`
- action validation
- action trace payload

验收：

- 能解析一个合法 `search_code` action
- 非法 action 能返回结构化错误
- action 和 observation 都能写入 trace

当前进展：

- 已新增 `app/schemas/agent_action.py`
- 已定义 `MendCodeAction` 统一动作协议
- 已支持 `assistant_message` / `tool_call` / `patch_proposal` / `user_confirmation_request` / `final_response`
- 已定义 `Observation`
- 已提供 `parse_mendcode_action`
- 已提供 `build_invalid_action_observation`
- 已通过单测覆盖合法 action、未知工具拒绝、非法 action observation 和 trace payload 序列化

下一步应进入阶段二：

`PermissionMode -> tool risk level -> permission decision -> confirmation request`

---

## 7. 阶段二：Permission Gate

目标：

把权限模式从产品设定落成工程机制。

交付：

- `PermissionMode`: Safe / Guided / Full / Custom
- 工具风险等级
- permission decision
- deny / confirm / allow
- 默认 Guided Mode

验收：

- Guided Mode 自动允许只读工具
- Guided Mode 允许 worktree patch
- Guided Mode 对主工作区 apply 返回确认请求
- 未授权工具不执行，并形成 observation

当前进展：

- 已新增 `app/agent/permission.py`
- 已定义 `PermissionMode`: Safe / Guided / Full / Custom
- 已定义 `PermissionDecision`
- 已建立首批工具风险等级
- Guided Mode 已允许只读工具、`run_command` 和 worktree patch
- Safe Mode 会对中风险工具返回确认请求
- Full Mode 允许已知工具
- Custom Mode 默认要求显式配置
- 已支持把需要确认的 tool call 转成 `user_confirmation_request`
- 已接入最小 Agent loop，能把需要确认的工具转成 confirmation action 和 rejected observation

当前尚未完成：

- 主工作区 apply 的独立 action 和高风险判定
- 用户确认结果回写 observation
- 自定义权限配置文件

下一步应进入阶段三或先补阶段四前置：

`Agent loop runner -> permission decision -> tool execution/confirmation observation`

---

## 8. 阶段三：LLM Provider 抽象

目标：

支持 OpenAI、Anthropic、OpenAI-compatible，并统一输出 MendCode Action。

交付：

- Provider config
- OpenAI adapter
- Anthropic adapter
- OpenAI-compatible adapter
- JSON action fallback
- provider error observation

验收：

- 业务层只消费 MendCode Action
- 切换 provider 不影响 Agent loop
- API key 不写入项目仓库

---

## 9. 阶段四：动态 Tool-use Loop

目标：

实现“观察 -> 决策 -> 工具 -> observation -> 再决策”的循环。

交付：

- Agent loop runner
- step budget
- worktree execution context
- observation history
- trace event

首批工具：

- `repo_status`
- `detect_project`
- `run_command`
- `read_file`
- `search_code`

验收：

- 用户描述 pytest 失败后，过渡入口能在隔离 worktree 中运行验证、解析失败并留下 trace
- 测试驱动的 Agent loop 能在 worktree 中应用 patch proposal、复跑验证、输出 diff summary

---

## 10. 阶段五：Patch 与验证闭环

目标：

让 Agent 能提出补丁，在 worktree 中应用，并验证结果。

交付：

- patch proposal schema
- apply patch to worktree
- diff summary
- verification gate
- max_attempts retry
- failed attempt trace

验收：

- 修复成功时输出 changed files、diff summary、verification result
- 修复失败时输出尝试记录和下一步选项
- 未验证通过时不能声称修复完成

---

## 11. 阶段六：TUI MVP

目标：

实现最终主入口：

```bash
mendcode
```

交付：

- 启动轻量 repo scan
- 聊天输入
- Guided Mode 默认权限
- 工具调用摘要展示
- 详情展开
- 工程审查收尾
- view diff / logs / trace / apply / discard

验收：

- 用户可以在 TUI 中描述问题
- Agent 能完成一次 worktree 内修复尝试
- 用户可以基于工程审查摘要决定 apply 或 discard
- 用户不需要写 JSON
- 用户不需要提供手工文本替换补丁
- Agent 每一步工具调用都有摘要
- 修复结果必须有验证命令证明

---

## 12. 当前过渡入口的定位

当前已有：

```bash
mendcode fix "<problem>" --test "<command>"
```

该入口只作为过渡能力保留，用于沉淀：

- `problem_statement`
- verification execution
- failure parser
- trace
- worktree safety

后续不要继续把它扩展成完整产品。新增能力应优先服务 TUI Agent 主线。

---

## 13. 文档维护规则

后续每轮开发都要同步更新：

- [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md)：产品设定变化时更新
- [MendCode_开发方案.md](/home/wxh/MendCode/MendCode_开发方案.md)：执行路线变化时更新
- [MendCode_全局路线图.md](/home/wxh/MendCode/MendCode_全局路线图.md)：阶段优先级变化时更新
- [MendCode_问题记录.md](/home/wxh/MendCode/MendCode_问题记录.md)：记录真实问题和解决方案

如果其它文档与 TUI 产品方案冲突，以 TUI 产品方案为准。
