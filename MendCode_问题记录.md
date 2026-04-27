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

- 旧规则 shell helper 只覆盖 `git status` 和“仓库状态”，没有覆盖“当前git状态 / git状态”这类无空格中文表达。
- TUI 的 tool result renderer 直接追加 `read_file` payload 中的 `content`，把工具原始内容和面向用户的最终回答混在一起。
- `read_file` 只支持从头或指定行号读取，没有表达“读文件尾部”的参数，模型只能猜测行号并反复调用工具。
- `search_code` 完全依赖外部 `rg` 二进制，TUI 运行环境 PATH 不完整时会让可降级的只读搜索变成失败 observation。
- TUI 只读工具 Agent 的 step budget 偏紧，模型在最后一步拿到足够信息后没有剩余轮次生成 final response。
- 旧场景测试覆盖了“第一句话”和 `git status` 字面命令，但没有覆盖这两类真实自然语言变体。

处理：

- 自然语言请求统一进入 schema tool-call AgentLoop，中文 Git 状态表达由模型通过 `git` 或 `run_shell_command` 工具获取事实。
- TUI 工具结果不再直接渲染 `read_file.content`，改为展示 `content_length` / `content_truncated` 等紧凑元信息，完整内容仍保留在 trace / observation 中。
- `read_file` 增加 `tail_lines` 参数，并在 prompt contract 中明确最后一行、最后一句、文件末尾问题应使用该参数，避免猜 `end_line`。
- `search_code` 在 `rg` 不可用时降级为 Python 只读文本搜索，保持工具链可用。
- TUI 只读工具 Agent 的 step budget 从 8 提升到 12，给工具调用后的 final response 留出余量。
- 场景测试新增“中文 git 状态不走 chat”和“文档最后一句不刷全文”回归用例。
- TUI 场景自动巡检报告明确记录文件内容不刷屏、中文 Git 状态和文档末句提问覆盖范围。

后续约束：

- 本地事实类自然语言变体必须持续进入 `tests/scenarios/` 或 PTY live 测试，不能只测英文命令或 slash command。
- 聊天流默认展示摘要和最终答案；完整工具 payload 只能通过 trace / viewer 按需查看。
- 新增 `read_file` 类场景时，必须断言不会把不相关的文件正文刷到 visible transcript。
- 问文件末尾内容时必须优先用 `tail_lines`，不要让模型通过猜测行号完成。

### 问题 12：真实 provider 会把最终回答作为 tool call 返回

状态：已修复 OpenAI-compatible 路径

现象：

用户询问“Mendcode问题记录的最后一句话是什么”时，真实 TUI 会话中模型已经通过 `read_file(tail_lines=10)` 读到了正确尾部内容，但下一轮 provider 返回 `final_response` tool call，被 MendCode 判定为 unknown tool call，最终显示 `Provider failed`。

根因：

- prompt 要求模型在 observation 足够时返回 `final_response`，但 OpenAI-compatible 请求只暴露 ToolRegistry 中的执行工具。
- 部分 OpenAI-compatible 模型在启用 tools 后会继续用 tool call 形式表达最终回答，而不是返回普通文本或 JSON action。
- 既有测试覆盖了“工具后普通文本 final answer”，但没有覆盖“工具后 final_response tool call”这一真实分支。

处理：

- OpenAI-compatible provider 增加 provider-local `final_response` tool，仅用于收尾，不进入 ToolRegistry、权限策略或执行链。
- 已有 observation 后才把 `final_response` 暴露给模型；收到该 tool call 时转换为 MendCode `final_response` action。
- 同一轮混合 `final_response` 和普通执行工具时直接失败，避免边执行边收尾。
- AgentLoop 和 TUI 测试增加 `glob_file_search -> read_file(tail_lines) -> final_response tool call` 闭环覆盖。

后续约束：

- provider-local action tool 必须和可执行工具分层，不能进入 ToolRegistry risk 表。
- 新增 provider 时必须覆盖“工具调用后模型如何最终回答”的真实协议变体。
- TUI 场景不能只 mock 最终 AgentLoopResult，还要保留至少一条真实 AgentLoop + fake provider 的端到端用例。

### 问题 13：只靠 Textual run_test 和 fake runner 无法代表真实 TUI 使用

状态：开始修复，已新增 PTY live e2e 测试入口

现象：

用户在真实 TUI 中询问“文档最后一句是什么”时仍然失败，但既有测试看起来已经覆盖了类似问题。测试体系主要调用 `app.run_test()` 或直接注入 fake runner，绕过了真实终端、真实 provider、OpenAI-compatible tool call 细节和 TUI 进程生命周期。

根因：

- `tests/scenarios/` 更适合验证路由、渲染摘要和 no-fabrication，但不启动真实命令行进程。
- fake runner 直接返回最终 `AgentLoopResult`，无法暴露真实 provider 在 tool result 后继续返回 `final_response` tool call 的协议差异。
- 缺少“像用户一样在终端输入一句话并等待结果”的自动化测试层。
- 巡检命令只跑轻量 scenario tests，没有把真实 PTY 用例纳入默认质量门。

处理：

- 新增 `tests/e2e/test_tui_pty_live.py`，使用 `pexpect` 启动真实 `python -m app.cli.main`。
- live 用例在临时 Git 仓库中构造真实文件、Git 状态和 conversation log。
- 默认要求真实 OpenAI-compatible provider 环境变量，缺失时测试明确失败，不静默跳过。
- TUI scenario audit 默认同时运行 `tests/scenarios` 和 `tests/e2e`。

后续约束：

- 用户在真实 TUI 暴露的问题，优先补 PTY live 回归；只有无法稳定自动化时才退到 fake provider scenario。
- live 用例必须断言可见输出和后台 conversation JSONL 中的工具证据，不能只看屏幕文本。
- 缺少真实 provider 环境时，测试可以阻塞验证，但不能伪装成通过。

### 问题 14：运行产物污染工具搜索会误导模型回答

状态：已修复基础路径

现象：

真实 PTY 巡检中，用户问“MendCode问题记录的最后一句话是什么”。模型没有读取根目录 `MendCode_问题记录.md`，而是用 `search_code` 命中了当前 `data/conversations/*.md` 会话日志，随后读取该日志，并把日志里的“Running tools: MendCode问题记录的最后一句话是什么”当作最终答案。

根因：

- TUI 启动后会立刻在当前仓库写入 `data/conversations` 和 `data/traces`。
- 宽泛 `search_code` 默认扫描整个工作区，模型容易被当前会话、trace 或历史运行记录中的同名文本吸引。
- 运行产物对复盘很有价值，但不应该参与普通“项目文件/文档内容”事实检索。

处理：

- `search_code` 宽泛搜索默认排除 `.git`、`.worktrees`、`data`。
- 显式 `glob='data/**'` 时仍允许搜索运行记录，保留分析 conversation log 的能力。
- 单测覆盖 broad search 排除 runtime data，以及显式 data glob 可搜索。
- 真实 PTY TUI 巡检复跑通过，确认文档末句场景不再被 conversation log 污染。

后续约束：

- 面向模型的默认项目检索必须区分“用户项目内容”和“MendCode 自身运行产物”。
- 新增搜索、glob、上下文恢复能力时，都要考虑运行产物是否会被模型误当成目标事实。
- 分析 `data/conversations` 应作为显式路径任务，而不是普通项目检索的默认结果。

### 问题 15：口语化本地事实请求会漏到 chat

状态：已由 schema tool-call 主路径修复，后续持续扩展场景库

现象：

新增 PTY 场景中，“先帮我看看当前目录里有什么”被判成 chat，模型只输出“我来查看当前目录”和代码块 `ls -la`，没有真正执行 shell；“帮我找一下 print('hello') 在哪个文件”也被判成 chat，模型编造 `<search_files>` 标签，没有调用 `search_code` / `rg`。

根因：

- 旧规则路由覆盖了“列一下当前目录”“查看当前git状态”等较规整表达，但没有覆盖“看看当前目录里有什么”这类口语问法。
- 代码定位请求同时包含“文件”和代码片段，但不符合既有“文件内容读取”规则，因此落到模型分类；真实 provider 在 ambiguous intent 下可能返回 chat。
- 普通 chat responder 没有工具调用能力，一旦本地事实请求漏进去，就容易产生“计划执行工具但实际没执行”的假反馈。

处理：

- 普通自然语言不再经过 TUI 规则路由，统一进入 schema tool-call AgentLoop。
- 模型通过 `list_dir`、`git`、`rg` / `search_code` 等 schema 工具获取本地事实。
- 补充 scenario 和 PTY live 回归，覆盖多轮目录+Git、代码定位真实路径。

后续约束：

- 本地事实请求必须走 schema tool-call AgentLoop，不能落到无工具 chat。
- 任何 chat 输出中出现“我来查看/我来搜索/```bash”但没有工具事件，都应视为体验问题。
- 新增真实用户问法时，要先判断它是“本地事实”还是“解释讨论”；前者必须有 shell/tool 证据。

### 问题 16：Provider 暴露工具面和权限策略容易漂移

状态：已修复基础路径

现象：

ToolRegistry 能输出全部 tools schema，PermissionPolicy 又在执行期判断工具风险。如果 Provider 直接把完整 Registry 暴露给模型，只读或简单任务会看到不必要的写入、shell 或验证工具；如果 Provider 只靠 `allowed_tools` 裁剪，又无法表达当前权限模式、simple mode 和 denied tools。

根因：

- ToolRegistry 是工具定义来源，但不是会话级工具视图。
- Provider、prompt contract、执行期 allowed-tools gate 各自处理一部分工具过滤逻辑。
- `tool_search` 如果搜索完整 Registry，会向模型推荐当前轮不可用的工具。

处理：

- 增加 `ToolPool`，按 permission mode、`allowed_tools`、denied tools 和 simple mode 派生模型当前可见工具集。
- OpenAI-compatible Provider 和 system prompt 改为从 `ToolPool` 获取工具列表。
- `tool_search` 支持 `ToolExecutionContext.available_tools`，可只搜索当前工具池。
- 保持 guided/workspace-write 下 `run_shell_command` 可见，由 ShellPolicy 对具体命令做 allow/confirm/deny。

后续约束：

- 面向模型的工具 schema 必须来自 ToolPool，不能直接 dump 完整 Registry。
- 执行期 allowed-tools gate 仍必须保留，不能只信任 Provider 暴露面。
- 新增工具时要同时考虑 Registry 定义、ToolPool 过滤、PermissionPolicy 决策和 `tool_search` 可见性。

### 问题 17：规则旁路会绕开模型工具选择

状态：已修复主路径

现象：

自然语言 `ls`、`git status`、文件读取等请求曾由 TUI 规则直接执行，和模型 schema tool-call 主线并行。这让测试同时维护“规则 shell/tool 路由”和“模型工具调用”两套行为，容易出现真实 TUI 和 AgentLoop 主线不一致。

根因：

规则路径最初用于补足工具能力，但在工具体系建立后变成第二套执行入口。它绕开模型的工具选择、ToolPool 当前可见工具面和 provider tool-call 协议，也让普通自然语言危险命令进入本地 pending shell 状态，而不是由 AgentLoop 形成工具 observation 或拒绝结果。

处理：

普通自然语言请求统一交给 AgentLoop，模型必须通过 schema tool call 获取本地事实。Slash commands、`/status`、`/sessions`、`/resume` 和 pending confirmation 仍作为 TUI 控制逻辑保留。遗留 `app/tui/intent.py` 和对应单测已删除。

后续约束：

- 新增自然语言能力时，优先新增 ToolSpec 和 tool-call 测试，不新增 TUI 规则执行旁路。
- PTY live 测试应断言 conversation JSONL 中存在 `tool_result.steps[*].action` 证据，而不是只看屏幕文本或最终回答是否提到工具名。
- 本地事实回答必须来自 tool evidence；provider 不支持原生 tools 时应明确失败，不回退到普通聊天。

### 问题 18：模型重复读取同一事实会浪费上下文

状态：已修复基础路径

现象：

模型在已经拿到文件内容、目录结果或搜索结果后，仍可能连续调用等价工具，导致 step budget 和上下文被工具过程占满。

根因：

AgentLoop 只按 step budget 限制总次数，没有识别“同一个工具 + 同一组语义参数”的重复调用。

处理：

AgentLoop 增加重复工具调用指纹，对 read-only 工具的第三次等价调用返回 rejected observation，提醒模型使用已有 observation 或收尾。

后续约束：

- 新增只读工具时要判断是否加入重复检测集合。
- 写工具只有在幂等语义明确后才能加入重复检测。
- 测试必须覆盖默认参数归一化，避免 `{"path": "README.md"}` 和 `{"path": "./README.md", "max_chars": 12000}` 被当成不同事实。

## 3. 后续重点风险

### 风险 A：模型重复调用等价只读工具

基础路径已修复，后续继续扩展检测范围和交互提示。当前指纹包括：

- tool name
- normalized args
- target path/query
- observation status

当等价只读调用第三次出现时，AgentLoop 返回 rejected observation，提示模型基于已有结果回答。后续可根据 `truncated=false`、分页状态和 LSP 结果类型做更精细的判断。

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
