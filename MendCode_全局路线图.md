# MendCode 全局路线图

## 1. 文档目的

本文档只回答一个问题：

`后续开发如何始终朝最新 TUI Code Agent 产品形态推进。`

所有产品判断以根目录下的 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 为准。本文档不再维护旧 fixed-flow、CLI-first、batch-eval-first 的路线。

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

- 聊天优先
- 动态工具调用
- 摘要优先，详情可展开
- 默认 Guided Mode
- 修改先进入隔离 worktree
- 没有验证结果不声称修复完成
- 用户最终决定 apply / discard / commit

---

## 3. 当前项目真实状态

截至 2026-04-24，项目已经完成的是底座能力，不是最终产品形态：

- Typer CLI 基础入口
- `TaskSpec` / `RunState` / verification schema
- Git worktree 隔离
- command policy / executor
- `read_file` / `search_code` / `apply_patch`
- verification command 执行
- JSONL trace
- fixed-flow demo 兼容能力
- fixed-flow 工具权限检查
- batch eval 辅助回归能力
- demo task suite 与 Python unit-fix fixture
- `mendcode fix "<problem>" --test "<command>"` 过渡入口
- pytest 风格失败日志解析

这些能力的定位：

`TUI Agent 的安全执行底座和早期验证切片。`

不要再把它们包装成最终产品主线。

---

## 4. 已废弃或降级的旧路线

以下旧方向不再作为主线：

- `mendcode task run <json>` 作为主要用户入口
- `old_text/new_text` 作为主要任务表达方式
- fixed-flow demo 作为产品核心体验
- 先补更多 demo suite
- 先做 batch eval 平台
- 先做 API 服务化
- 先做复杂 Web UI
- 先做多 Agent 编排

它们可以作为兼容能力、测试 fixture 或后续增强，但不应抢占 TUI Agent 主线。

当前处理原则：

- 已从历史分支迁回 demo suite 与 batch eval 的有用实现。
- 它们的定位是“底座回归验证”和“演示辅助”，不是下一阶段主线。
- 后续如果 eval 与 TUI Agent loop 抢资源，优先推进 TUI Agent loop。

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

- `MendCodeAction` schema
- `Observation` schema
- `assistant_message` / `tool_call` / `patch_proposal` / `user_confirmation_request` / `final_response`
- Action 解析与校验
- Action trace 事件
- step budget
- 非法 Action 的分级降级

停手点：

- 能在无 TUI 的测试中模拟一轮 `tool_call -> observation -> next action`
- 非法 action 不会让系统崩溃

当前状态：

- `MendCodeAction` schema 已落地
- `Observation` schema 已落地
- 合法 tool call 可解析
- 未知工具会被 schema 拒绝
- 非法 action 可转换为 rejected observation
- action / observation 可写入 trace payload

Phase A 的 schema 基础已具备。后续仍需在 Agent loop runner 中真正消费这些 schema。

### Phase B：Permission Gate

目标：

把 Safe / Guided / Full / Custom 权限模式落成可执行策略。

交付：

- 权限模式 schema
- 工具风险等级
- permission decision
- 中高风险动作确认请求
- 默认 Guided Mode

停手点：

- `read_file` / `search_code` 可自动通过
- `apply to workspace` 必须确认
- 未授权工具能形成清晰 observation

当前状态：

- Permission Gate 最小实现已落地
- Safe / Guided / Full / Custom 模式已定义
- 首批工具风险等级已定义
- Guided Mode 已允许只读工具、验证命令和 worktree patch
- Safe Mode 对中风险工具返回确认请求
- 确认请求已统一为 `user_confirmation_request` action
- fixed-flow runner 已接入 `allowed_tools` 检查，未授权工具会返回 rejected tool result 并进入 trace
- runner 的阶段状态已从统一 `summarize` 收敛为更精确的 `bootstrap/locate/inspect/patch/verify/summarize`

后续需要把 Permission Gate 接入 Agent loop，而不是停留在独立函数。

### Phase C：LLM Provider 抽象

目标：

支持 OpenAI、Anthropic、OpenAI-compatible，并统一归一化为 MendCode Action。

交付：

- Provider 配置 schema
- OpenAI adapter
- Anthropic adapter
- OpenAI-compatible adapter
- JSON Action fallback
- provider 错误降级

停手点：

- 业务层只处理 MendCode Action，不直接依赖厂商 tool calling 格式

### Phase D：Tool Execution 与检索增强

目标：

让 Agent 能根据 observation 自主继续定位问题。

交付：

- `repo_status`
- `detect_project`
- `run_command`
- `read_file`
- `search_code`
- 失败测试文件读取
- 基于 failed node / import / rg 的候选文件检索

停手点：

- 用户描述“pytest 失败”后，Agent 能运行测试、解析失败、读取测试文件、搜索候选实现

### Phase E：Patch Proposal 与验证闭环

目标：

让 Agent 能提出补丁，在 worktree 中应用，并用验证命令证明结果。

交付：

- patch proposal schema
- patch apply to worktree
- diff summary
- verification gate
- max_attempts retry
- failed patch trace

停手点：

- 修复通过时能输出 changed files、diff summary、verification result
- 修复失败时能输出尝试记录和下一步选项

### Phase F：TUI MVP

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

停手点：

- 用户可以在 TUI 中描述一个 pytest 失败问题
- Agent 能动态调用工具完成一次 worktree 内修复尝试
- 用户能基于审查摘要决定 apply 或 discard

---

## 7. 暂缓事项

第一版 TUI Agent MVP 不做：

- 多任务并行
- 后台长期任务
- 多仓库切换
- 复杂布局拖拽
- 完整配置 UI
- 项目记忆自动写入
- commit / push 自动化
- 复杂 diff viewer
- 本地模型
- 多 provider 深度适配
- 企业权限系统
- GitHub PR 自动化

---

## 8. 每轮开发前判断

每轮开始前只问五个问题：

1. 这项工作是否推进 TUI Agent 主线？
2. 它是否服务 `Action loop -> Permission gate -> Tool execution -> Observation -> Patch -> Verification`？
3. 它是否减少用户手写补丁或手动定位的负担？
4. 它是否保持 worktree 隔离和用户确认边界？
5. 它是否与 [MendCode_TUI产品基调与交互方案.md](/home/wxh/MendCode/MendCode_TUI产品基调与交互方案.md) 一致？

如果答案不清楚，就先不要做。
