# MendCode 全局路线图

## 1. 总目标

MendCode 的长期目标是成为本地仓库中的可验证 Code Agent 工作台。

最终形态：

```text
自然语言任务
-> 模型规划工具调用
-> 本地安全执行
-> 结构化 observation
-> 模型基于真实结果继续推理
-> worktree 内修改和验证
-> 用户审查并决定落地
```

当前路线不再围绕旧 fixed-flow 或 task JSON 展开，所有新增能力都必须服务运行时工具闭环。

## 2. 架构方向

### 2.1 Runtime Core

目标是形成一个稳定的会话运行时，而不是把逻辑散落在 TUI、provider 和工具函数里。

核心模块：

- Session：保存消息、工具调用、结果、摘要、resume 信息
- AgentLoop：协调 provider、工具、权限、trace 和 step budget
- Provider：只负责模型协议适配
- ToolRegistry：工具定义、schema、risk、executor 的唯一来源
- PermissionPolicy：决定 allow / confirm / deny
- ToolExecutor：执行工具并返回结构化 observation
- Trace / ConversationLog：用于审计、调试和回放

### 2.2 ToolRegistry

工具系统要满足：

- 工具定义可被 provider 转成 OpenAI tools schema
- 工具参数由 Pydantic 校验
- 工具 risk level 与权限策略共享同一来源
- 工具结果统一结构，适合传给模型和写入日志
- 支持 `allowed_tools` 按场景裁剪工具表面
- 支持别名和工具发现，但不让模型调用未注册工具

### 2.3 PermissionPolicy

权限系统要满足：

- Safe：只读工具自动，其他动作确认或拒绝
- Guided：只读和验证自动，worktree 写入自动，主工作区和高风险动作确认
- Full：仍保留关键风险边界，不默认 push / destructive
- Custom：后续由配置文件定义

所有 shell 命令必须先分类：

- read-only
- write
- install
- network
- git mutate
- destructive
- path escape
- unknown

### 2.4 Provider Contract

OpenAI-compatible 是当前主路径：

- 原生 `tool_calls` 优先
- JSON Action fallback 保留
- provider 必须接收 observation history
- provider 输出的工具名必须经过 ToolRegistry 和 `allowed_tools` 校验
- 工具后普通文本可以收束为 final response

后续新增 provider 时，不允许改变 AgentLoop 主体。

## 3. 阶段路线

### Phase 0：基础清理

状态：已完成

- [x] 移除旧 task JSON 主入口
- [x] 移除 fixed-flow demo 主线
- [x] 明确 TUI AgentLoop 为唯一主线
- [x] data/conversations 进入忽略范围

### Phase 1：Action / Observation 协议

状态：已完成

- [x] `MendCodeAction`
- [x] `Observation`
- [x] `ToolCallAction`
- [x] `PatchProposalAction`
- [x] `FinalResponseAction`
- [x] invalid action observation
- [x] trace payload

验收标准：

- [x] 非法 action 不崩溃
- [x] 未知工具被拒绝
- [x] final response 受 observation gate 约束

### Phase 2：Provider-driven AgentLoop

状态：已完成基础版，继续加固

- [x] Provider step input
- [x] Observation history
- [x] step budget
- [x] provider failure observation
- [x] OpenAI-compatible adapter
- [x] 原生 `tool_calls`
- [x] JSON fallback
- [x] tool result message 回填
- [x] tool 后普通文本收束

下一步：

- [ ] 记录 provider request/response 的调试摘要
- [ ] 增加 provider mock parity harness
- [ ] 增加真实 provider smoke checklist

### Phase 3：ToolRegistry 与工具闭环

状态：进行中

- [x] ToolRegistry primitives
- [x] OpenAI tools schema
- [x] `allowed_tools`
- [x] tool alias normalization
- [x] native invocation 执行期 allowed gate
- [x] `read_file`
- [x] `list_dir`
- [x] `glob_file_search`
- [x] `rg` / `search_code`
- [x] structured `git`
- [x] `run_shell_command`
- [x] `run_command`
- [x] `apply_patch`

下一步：

- [ ] 统一所有工具结果字段
- [ ] 增加 `write_file`
- [ ] 增加 `edit_file`
- [ ] 增加 `todo_write`
- [ ] 增加 `tool_search`
- [ ] 将 legacy tool path 收敛到 ToolRegistry

### Phase 4：权限与执行安全

状态：基础版已完成，策略对象待重构

- [x] PermissionMode
- [x] PermissionDecision
- [x] risk level 从 ToolRegistry 派生
- [x] shell policy
- [x] pending shell confirmation
- [x] `run_command` verification-only
- [x] path escape 防护

下一步：

- [ ] 抽出统一 PermissionPolicy 类
- [ ] 支持 allow once / deny / change mode 的确认回写
- [ ] 增加配置化 allow/deny/ask 规则
- [ ] 增加主工作区 apply 的独立确认路径

### Phase 5：Session / Resume / Audit

状态：早期完成

- [x] Markdown conversation log
- [x] JSONL conversation log
- [x] trace recorder
- [x] `/status` 展示日志路径
- [x] ReviewSummary
- [x] AttemptRecord

下一步：

- [ ] 会话列表
- [ ] resume latest/session-id
- [ ] compact summary
- [ ] session health probe
- [ ] trace viewer

### Phase 6：TUI 工作台

状态：可用切片，体验继续补齐

- [x] TUI 启动
- [x] chat/fix/shell/tool intent
- [x] shell 自动执行和确认
- [x] 工具结果摘要展示
- [x] review actions

下一步：

- [ ] 工具调用折叠/展开
- [ ] permission prompt 交互完善
- [ ] diff viewer
- [ ] logs viewer
- [ ] session picker
- [ ] provider status/doctor 页面

## 4. 测试路线

### 单元测试

- ToolRegistry schema / aliases / allowed tools
- PermissionPolicy allow / confirm / deny
- ShellPolicy 命令分类
- Provider native tool calls
- Prompt context tool result messages
- AgentLoop final gate

### 集成测试

- 自然语言目录查看
- 文件读取后回答
- 多工具同轮调用
- 权限拒绝后模型收尾
- shell approve / deny
- patch -> verify -> final

### Mock harness

需要建设一个确定性 mock provider，覆盖：

- streaming text
- read_file roundtrip
- grep/rg result assembly
- multi-tool turn
- bash stdout
- permission approve
- permission deny
- write/edit allowed in worktree
- write/edit denied in read-only mode

## 5. 暂缓事项

以下能力在当前阶段不作为主线：

- 多 Agent 调度
- MCP 生命周期管理
- 插件市场
- Web 搜索
- Notebook 编辑
- 自动 commit / push
- GitHub PR 自动化
- 企业权限系统
- 长期后台任务

这些能力只有在 Runtime Core、ToolRegistry、PermissionPolicy、Session Resume 稳定后再进入路线。

## 6. 每轮开发判断

每轮开发前检查：

1. 是否加强了工具闭环？
2. 是否减少模型编造本地事实的机会？
3. 是否让权限边界更集中？
4. 是否让会话更可复盘？
5. 是否有测试锁住 provider/tool/permission 的真实交互？

如果不能回答这些问题，就先不要扩功能。
