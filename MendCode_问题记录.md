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

### 问题 7：根文档职责不清，容易让开发回到旧主线

状态：已解决基础整理，后续每轮需维护

现象：

多个根文档同时描述产品定位、路线和问题，旧内容中还残留 CLI-first、fixed-flow、batch eval 等方向，容易造成判断混乱。上一轮整理中过度收缩文档，误删了项目必需的 `README.md`。

根因：

- 文档按历史阶段累积，没有按当前主线重塑
- README、产品基调、开发方案、路线图之间职责重叠
- 忽略了 README 对项目入口、快速上手和新贡献者导航的必要性

处理：

- 根目录保留四份长期文档：
  - `README.md`
  - `MendCode_开发方案.md`
  - `MendCode_全局路线图.md`
  - `MendCode_问题记录.md`
- 删除旧产品基调文档，将其有效内容合并进 README、路线图和开发方案
- README 面向使用者和新贡献者；开发方案面向继续实现；路线图只保留大方向；问题记录保存工程教训

后续约束：

- README 是项目必需文档，不得删除
- 全局路线只写整体方向和阶段优先级，保持简要
- 开发方案写详细实现状态、模块契约、测试策略和下一步任务，并且每次开发后按现实状态更新
- 问题记录写“哪些坑不能再踩”
- 不再新增同类根文档，除非先明确文档职责并合并重叠内容

### 问题 8：ShellPolicy 只识别带空格重定向会留下写入绕过

状态：已修复，后续需持续覆盖

现象：

`printf hello > marker.txt` 会被识别为重定向并要求确认，但 `printf hello>marker.txt`、`cat README.md>copy.txt` 这类无空格相邻重定向曾被 `shlex.split` 保留在普通参数 token 中，绕过重定向确认。

根因：

- ShellPolicy 只检测独立 token 或 token 开头的 `>`、`>>`、`1>`、`2>`、`&>`。
- shell 语法允许重定向操作符与参数相邻，不要求空格。
- 低风险 allowlist 扩展到 `printf` 后，stdout-only 命令可自动执行，放大了该解析缺口。

处理：

- ShellPolicy 增加 token 内部相邻输出重定向检测。
- `printf hello>marker.txt`、`cat README.md>copy.txt` 现在要求确认。
- `printf hello>../outside.txt`、`cat README.md>../copy.txt` 现在直接拒绝为 critical path escape。

后续约束：

- 新增 shell allowlist 命令时，必须同时测试带空格和无空格的重定向写入。
- ShellPolicy 测试要覆盖 shell 语法等价形式，不能只测人类常写的空格格式。
- 任何低风险 shell 命令都不能绕过 redirection、compound command、path escape 三类安全检查。

### 问题 9：工具过程日志和 prompt context 重复膨胀

状态：已修复基础路径，仍需补 trace viewer

现象：

最新 conversation log 中，`tool_result` 事件比最终回答大很多：TUI 把完整 `AgentLoopResult` 写进 Markdown/JSONL，包含每一步 action、observation、完整 `read_file` 内容和目录 entries；OpenAI native tool 的 observation 又同时进入 user context 和 tool message，导致同一工具结果在下一轮请求中重复出现。

根因：

- conversation log 直接使用 `result.model_dump()` / `turn.model_dump()`，没有区分“可读复盘摘要”和“完整 trace 数据”。
- native tool result 已经必须作为 OpenAI `tool` message 回传，但 user context 仍保留同一 observation。
- 日志和 prompt context 共用“越完整越好”的思路，缺少按用途裁剪。

处理：

- TUI 写 `tool_result` / `turn_result` 时使用 compact 摘要，只保留 run/status/summary、trace/workspace 指针、步骤状态、payload 样本和文本 excerpt。
- 完整工具 payload 继续保留在 trace 中，conversation log 不再承担完整原始数据存储职责。
- OpenAI native tool result 只通过 assistant/tool message 链回传，不再重复写入 user context；JSON action 和 provider failure 仍保留在 user context。

后续约束：

- 面向人的 conversation log 只能写摘要、样本和定位指针，不能直接 dump 完整 agent result。
- 面向模型的 prompt context 要避免同一 observation 在不同消息槽重复出现。
- 如需查看完整工具输出，应通过 trace viewer 或按需展开，而不是扩大聊天流或 conversation log。

### 问题 10：AgentLoop 直接维护工具分支会阻碍 Runtime 化

状态：开始修复，第一批只读内置工具已迁移

现象：

`repo_status`、`detect_project`、`show_diff` 曾经直接写在 `app/agent/loop.py` 中，而 `read_file`、`list_dir`、`rg`、`git` 等工具走 `ToolRegistry`。这导致 provider-visible tools、JSON action fallback、权限风险表、执行器和测试分散在多个位置。

根因：

- 早期 AgentLoop 先承担了运行时、工具执行、权限确认、trace 写入等职责。
- 后续引入 ToolRegistry 后，没有及时把旧 builtin 工具迁走。
- Permission risk 对 builtin 工具保留了独立表，削弱了“工具能力由注册表定义”的约束。

处理：

- `repo_status`、`detect_project`、`show_diff` 已迁入 `ToolRegistry`。
- 这些工具的 OpenAI schema、executor、risk level 现在由注册表提供。
- allowed tools aliases 增加 `status`、`project`、`diff`。

后续约束：

- 新增 provider-visible 工具必须先进入 ToolRegistry，不能直接在 AgentLoop 加分支。
- AgentLoop 中剩余 legacy 分支只能作为迁移兼容层，不能扩张。
- PermissionPolicy 后续必须从 ToolSpec 读取 required mode/risk，避免再维护平行风险表。

### 问题 11：自然语言本地事实提问仍会漏到 chat 或刷屏

状态：已修复本轮暴露路径，后续需持续扩展场景库

现象：

- 用户输入“查看当前git状态”时，请求被判为 chat，模型没有执行工具却编造了 `git status` 输出。
- 用户询问“某文档的最后一句是什么”时，请求进入 tool path，但 TUI 把 `read_file` 的文件内容直接渲染到聊天流，导致用户看到大段全文，而不是只看最终答案。
- 用户询问“Mendcode问题记录的最后一句是什么”时，模型多次 `glob_file_search` / `read_file`，又尝试不可用的 `rg`，最后耗尽 step budget，没有给出已经读到的答案。

根因：

- `plan_rule_based_shell_command` 只覆盖 `git status` 和“仓库状态”，没有覆盖“当前git状态 / git状态”这类无空格中文表达。
- TUI 的 tool result renderer 直接追加 `read_file` payload 中的 `content`，把工具原始内容和面向用户的最终回答混在一起。
- `read_file` 只支持从头或指定行号读取，没有表达“读文件尾部”的参数，模型只能猜测行号并反复调用工具。
- `search_code` 完全依赖外部 `rg` 二进制，TUI 运行环境 PATH 不完整时会让可降级的只读搜索变成失败 observation。
- TUI 只读工具 Agent 的 step budget 偏紧，模型在最后一步拿到足够信息后没有剩余轮次生成 final response。
- 旧场景测试覆盖了“第一句话”和 `git status` 字面命令，但没有覆盖这两类真实自然语言变体。

处理：

- 规则路由增加中文 Git 状态表达，确保“查看当前git状态”直接进入 shell path 并执行 `git status`。
- TUI 工具结果不再直接渲染 `read_file.content`，改为展示 `content_length` / `content_truncated` 等紧凑元信息，完整内容仍保留在 trace / observation 中。
- `read_file` 增加 `tail_lines` 参数，并在 prompt contract 中明确最后一行、最后一句、文件末尾问题应使用该参数，避免猜 `end_line`。
- `search_code` 在 `rg` 不可用时降级为 Python 只读文本搜索，保持工具链可用。
- TUI 只读工具 Agent 的 step budget 从 8 提升到 12，给工具调用后的 final response 留出余量。
- 场景测试新增“中文 git 状态不走 chat”和“文档最后一句不刷全文”回归用例。
- TUI 场景自动巡检报告明确记录文件内容不刷屏、中文 Git 状态和文档末句提问覆盖范围。

后续约束：

- 本地事实类自然语言变体必须持续进入 `tests/scenarios/`，不能只测英文命令或 slash command。
- 聊天流默认展示摘要和最终答案；完整工具 payload 只能通过 trace / viewer 按需查看。
- 新增 `read_file` 类场景时，必须断言不会把不相关的文件正文刷到 visible transcript。
- 问文件末尾内容时必须优先用 `tail_lines`，不要让模型通过猜测行号完成。

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
