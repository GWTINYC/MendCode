# MendCode 全局路线图

## 1. 大方向

MendCode 的目标是成为本地仓库中的可验证 TUI Code Agent。

核心闭环：

```text
自然语言任务
-> 模型选择工具
-> 本地权限校验
-> 工具执行
-> observation 回传模型
-> 基于证据回答或修复
-> 用户审查后落地
```

所有开发都应围绕这个闭环推进，避免回到 fixed-flow、task JSON 或单纯命令行包装器路线。

当前主线采用 Runtime-first 重构：TUI、CLI、Provider、Tool、Permission、Session 都围绕同一个 Agent Runtime 收敛。允许大幅调整内部接口，但不能牺牲工具闭环、安全边界和可复盘性。

## 2. 长期原则

- 工具优先：本地事实必须来自工具结果，不由普通聊天编造。
- 安全优先：工具执行前必须经过工具白名单、权限策略和路径边界检查。
- 证据优先：修复完成必须有验证结果，回答本地事实必须有 observation。
- 会话可复盘：用户输入、工具调用、结果、错误和最终答复都要落盘。
- 主线清晰：TUI AgentLoop 是唯一产品主线，CLI repair 只是过渡入口。

## 3. 阶段规划

### Phase A：运行时闭环

目标：让 OpenAI-compatible 原生 `tool_calls` 稳定完成 `tool_call -> tool_result -> final_response`，并把 AgentLoop 收敛为可复用 Runtime。

状态：基础版已完成，进入 Runtime-first 重构。

下一步重点：

- 统一工具结果结构
- 将 legacy tool path 迁移到 ToolRegistry
- 抽出 AgentRuntime
- 增加等价只读工具调用去重
- 建设确定性 mock provider harness

### Phase B：工具与权限系统

目标：让 ToolRegistry 成为工具 schema、risk、executor 的唯一来源，让权限策略集中可测。

状态：基础版已完成，仍需重构。

下一步重点：

- 抽出完整 PermissionPolicy
- 将剩余 legacy tool path 收敛进 ToolRegistry
- 增加 `write_file`、`edit_file`、`todo_write`、`tool_search`

### Phase C：会话与审计

目标：让每轮对话都能恢复、审计、调试和评估。

状态：早期能力已完成。

下一步重点：

- 会话列表
- resume latest/session-id
- compact summary
- trace viewer

### Phase D：TUI 工作台体验

目标：让用户在 TUI 中完成查看、修复、验证、审查和落地。

状态：可用切片已完成。

下一步重点：

- 工具调用折叠/展开
- permission prompt 完整交互
- diff viewer
- logs viewer
- provider status/doctor

## 4. 暂缓事项

在运行时闭环、工具权限、会话恢复稳定前，暂缓：

- 多 Agent 调度
- MCP 生命周期管理
- 插件市场
- Web 搜索
- Notebook 编辑
- 自动 commit / push
- GitHub PR 自动化
- 企业权限系统
- 长期后台任务

## 5. 开发前检查

每轮开发前只问五个问题：

1. 是否加强了工具闭环？
2. 是否减少模型编造本地事实的机会？
3. 是否让权限边界更集中？
4. 是否让会话更可复盘？
5. 是否有测试锁住 provider、tool、permission 的真实交互？

如果答案不清楚，先不要扩功能。
