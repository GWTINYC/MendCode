# MendCode 问题记录

## 1. 记录目的

本文档只记录会影响 MendCode 长期架构和开发判断的问题。旧 fixed-flow、task JSON、demo suite 相关细节不再展开，除非它们能形成当前 AgentLoop 主线的约束。

记录格式：

```text
问题 -> 根因 -> 处理 -> 后续约束
```

目标不是保存流水账，而是避免同类工程错误反复出现。

## 2. 当前高优先级问题

### 问题 1：普通聊天回答本地事实，容易编造

状态：已解决基础路径，仍需持续防回归

现象：

用户询问当前目录、文件内容或 Git 状态时，如果请求进入普通 chat responder，模型会在没有工具结果的情况下编造答案。

根因：

- intent routing 早期允许模型把规则识别出的工具请求改判为 chat
- 普通 chat 没有工具绑定
- 本地事实必须依赖工具执行结果，而不是 prompt 约束

处理：

- 规则识别出的工具请求不再被模型覆盖为 chat
- 文件/目录/代码/Git 状态请求进入 tool path
- TUI 工具请求调用 AgentLoop，由模型选择结构化工具

后续约束：

- 本地事实问题必须走工具路径
- 普通聊天只能回答解释、讨论、建议类问题
- 新增 intent 类型时必须有 TUI 行为测试和 conversation log 断言

### 问题 2：工具结果进入模型上下文不完整，会导致重复调用或错误收尾

状态：已解决基础路径

现象：

工具已经成功返回目录结果后，模型仍重复调用 `list_dir`，或者在工具后返回普通文本导致 provider 报 invalid action。

根因：

- 未截断目录结果在 prompt context 中被二次截断
- prompt contract 没有明确 `truncated=false` 的语义
- provider 对工具后的普通文本过于严格

处理：

- `list_dir` 未截断时完整 entries 进入 prompt context
- prompt 明确：结果足够时返回 final response，不重复工具
- 工具 observation 后普通文本可包装为 final response

后续约束：

- 工具 observation 不能丢失影响模型判断的完整性字段
- 工具后普通文本只能在已有 observation 时放宽
- 仍需增加等价只读工具调用去重

### 问题 3：工具表面过宽，会让只读任务暴露写入能力

状态：已解决基础路径

现象：

只读请求如果收到完整 tools schema，模型能看到 `apply_patch`、`run_shell_command`、`run_command` 等不需要的工具。

根因：

- ToolRegistry 最初只支持输出全部 tools schema
- provider 没有场景级工具裁剪
- AgentLoop 没有执行期 allowed-tools 二次检查

处理：

- ToolRegistry 支持 `allowed_tools`
- Provider 按 `allowed_tools` 发送裁剪后的 OpenAI tools schema
- Provider 拒绝越权 tool call
- AgentLoop 执行前再次拒绝越权 native tool invocation
- TUI 自然语言工具请求默认只暴露只读工具

后续约束：

- 面向模型的工具集必须按场景裁剪
- 执行期检查不能只依赖 provider
- 修复类任务和只读查询任务必须使用不同工具表面

### 问题 4：权限风险等级重复维护，容易漂移

状态：已解决基础路径

现象：

权限模块曾维护一份工具风险表，ToolRegistry 中也维护 `risk_level`。新增工具时可能只改其中一处。

根因：

- 工具定义与权限策略没有单一事实来源
- run_shell_command 一度被 safe mode 当作低风险工具

处理：

- Permission Gate 从 ToolRegistry 派生风险等级
- 仅保留少量 legacy/builtin action 的风险映射
- 测试覆盖 restricted shell 在 Safe 模式下需要确认

后续约束：

- 新增工具必须先进入 ToolRegistry
- risk level 只能有一个主来源
- 后续应抽出完整 PermissionPolicy 对象

### 问题 5：verification command 与普通 shell 混用，会破坏验证语义

状态：已解决基础路径

现象：

如果普通 shell 和验证命令共用 executor，模型可能用任意命令绕过 declared verification gate。

根因：

- 早期 `run_command` 容易被当作通用 shell
- 修复验证需要比普通诊断更严格的 allowlist

处理：

- `run_command` 仅允许执行声明过的 verification command
- `run_shell_command` 走独立 shell policy
- prompt contract 明确两者区别

后续约束：

- 证明修复结果只能用 `run_command`
- 普通诊断用 `run_shell_command` 或结构化只读工具
- TUI 展示时也要区分 shell result 和 verification result

### 问题 6：会话不可复盘时，调试只能依赖终端画面

状态：已解决基础路径

现象：

用户发现模型编造或工具调用失败时，如果没有本地对话日志，只能凭终端画面推测是哪条路径出了问题。

根因：

- TUI 最初只展示即时消息
- intent、tool result、final response 没有统一落盘

处理：

- 每轮对话写入 Markdown 和 JSONL
- `/status` 展示 conversation log 路径
- tool/shell/chat/turn result 都写 event

后续约束：

- 新增交互路径必须写 conversation event
- JSONL 保留结构化 payload，Markdown 方便人工查看
- 后续 resume 和质量评估都应基于会话日志

### 问题 7：文档过多且方向重叠，容易让开发回到旧主线

状态：已解决本轮整理

现象：

多个根文档同时描述产品定位、路线和问题，旧内容中还残留 CLI-first、fixed-flow、batch eval 等方向，容易造成判断混乱。

根因：

- 文档按历史阶段累积，没有按当前主线重塑
- README、产品基调、开发方案、路线图之间职责重叠

处理：

- 根目录只保留三份长期文档：
  - `MendCode_开发方案.md`
  - `MendCode_全局路线图.md`
  - `MendCode_问题记录.md`
- 删除旧 README 和旧产品基调文档
- 三份文档都围绕 Runtime Core、ToolRegistry、PermissionPolicy、Session、TUI AgentLoop 展开

后续约束：

- 开发方案写“当前怎么做”
- 全局路线写“长期怎么走”
- 问题记录写“哪些坑不能再踩”
- 不再新增同类根文档，除非先删除或合并旧文档

## 3. 后续重点风险

### 风险 A：模型重复调用等价只读工具

需要在 AgentLoop 层记录最近工具调用指纹：

- tool name
- normalized args
- target path/query
- observation status

当同一路径/查询已经返回 `truncated=false` 或完整结果时，应拒绝重复调用并提示模型基于已有结果回答。

### 风险 B：工具结果字段不统一

当前不同工具 payload 仍有差异。后续应统一：

- `tool_name`
- `status`
- `summary`
- `is_error`
- `payload`
- `truncated`
- `next_offset`
- `stdout_excerpt`
- `stderr_excerpt`
- `duration_ms`

### 风险 C：权限确认结果没有完整回写

pending shell 已有基础交互，但通用工具确认还需要：

- allow once
- deny
- change permission mode
- 记录用户选择
- 把拒绝也作为 observation 反馈给模型

### 风险 D：mock provider 覆盖不足

需要建立确定性 mock harness，避免真实模型行为变化导致测试不稳定。重点覆盖：

- read file roundtrip
- grep/rg roundtrip
- multi-tool turn
- shell stdout
- permission approve
- permission deny
- write allowed in worktree
- write denied in read-only mode

## 4. 记录规则

新增问题必须满足至少一条：

- 影响工具闭环正确性
- 影响权限边界
- 影响会话可复盘性
- 影响验证结论可信度
- 影响长期架构方向

不再记录纯讨论、一次性环境噪声、旧路线细枝末节。
