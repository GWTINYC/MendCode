# MendCode TUI 产品基调与交互方案

## 1. 产品定位

MendCode 的最终产品形态不是“用户指定补丁的执行器”，也不只是 `mendcode fix --test` 形式的命令行工具，而是：

`终端里的本地 Code Agent 工作台。`

用户输入：

```bash
mendcode
```

进入 TUI 后，用自然语言描述问题。Agent 根据上下文自主调用工具、读取结果、决定下一步动作，并在隔离 worktree 中完成修复、验证和审查收尾。

一句话定位：

`MendCode 是面向本地代码仓的可验证修复型 Code Agent。`

开发清单机制：

- 使用 Markdown checkbox 表示 TUI MVP 能力状态。
- `[ ]` 表示尚未完成或尚未验证。
- `[x]` 表示已经完成并通过对应测试或验证。
- 每完成一项功能，必须同步更新本文档、[MendCode_开发方案.md](/home/wxh/MendCode/MendCode_开发方案.md)、[MendCode_全局路线图.md](/home/wxh/MendCode/MendCode_全局路线图.md) 中的对应清单。
- 只讨论过但没有代码和验证证据的事项不能勾选。

核心气质：

- [ ] 少废话
- [x] 强验证
- [x] 过程透明
- [x] 改动可控
- [x] 默认安全

---

## 2. TUI 产品基调

第一版 TUI 采用：

`聊天优先的终端 Code Agent。`

它不是表单向导，也不是多任务看板，而是：

```text
聊天输入
工具调用摘要
工程证据收尾
用户确认落地
```

用户体验类似：

```text
$ mendcode

MendCode
repo: /home/wxh/project
branch: main
status: dirty, 3 modified
mode: guided
model: claude-sonnet

Type your task:
> pytest 失败了，帮我修复
```

Agent 默认按摘要展示过程：

```text
✓ repo_status
  branch: main
  dirty: 3 modified

✓ detect_project
  language: python
  suggested_test: python -m pytest -q

✓ run_command
  python -m pytest -q

✗ verification failed
  failed_node: tests/test_calculator.py::test_add
  error: AssertionError: assert -1 == 5
```

最终进入工程审查收尾：

```text
Fix verified in worktree: preview-a31c9

Summary:
- Changed calculator.py (+1 -1)
- Fixed test_add failure
- Verification passed

Actions:
[v] View diff
[l] View logs
[t] View trace
[a] Apply to workspace
[c] Commit
[d] Discard
```

---

## 3. 启动策略

TUI 启动后采用折中型上下文感知：

```text
轻量扫描，主动展示上下文，不自动执行风险动作。
```

启动时允许自动执行：

- [ ] 读取当前目录
- [x] 判断是否 Git repo
- [x] 读取当前 branch
- [x] 检查 dirty status
- [x] 识别项目类型
- [x] 推测常见验证命令
- [ ] 展示最近一次 MendCode run

启动时不自动执行：

- [ ] 不跑测试
- [x] 不改主工作区文件
- [x] 不创建 worktree
- [x] 不调用 LLM
- [x] 不做全仓深度扫描

---

## 4. 权限模型

MendCode 的权限基调：

`默认安全，显式授权，可升级权限，风险由用户确认承担。`

权限模式：

| 模式 | 只读工具 | 测试/构建 | worktree 写入 | apply 到主仓库 | 任意 shell / 网络 |
|---|---|---|---|---|---|
| Safe | 自动 | 每次确认 | 每次确认 | 每次确认 | 禁止 |
| Guided | 自动 | 自动 | 自动写 worktree | 每次确认 | 低风险自动，写入/安装/网络确认或禁止 |
| Full | 自动 | 自动 | 自动 | 可配置自动 | 可配置允许 |
| Custom | 用户自定义 | 用户自定义 | 用户自定义 | 用户自定义 | 用户自定义 |

默认模式建议为：

`Guided Mode`

Guided Mode 下：

- [x] `repo_status` / `read_file` / `search_code` 自动执行
- [x] `ls` / `pwd` / `git status` / `git diff` / `rg` / `cat` / `head` / `tail` / `find` 常见只读 shell 查询自动执行
- [x] 测试、lint 可自动执行
- [x] patch 可自动应用到隔离 worktree
- [x] apply 到当前工作区必须确认
- [x] git commit / push 必须确认
- [x] 任意 shell、安装依赖、联网默认确认或禁止

确认不是打断，而是把风险决策交还给用户。

---

## 5. 过程展示

TUI 可见度采用：

`摘要优先，详情可展开。`

默认展示：

- [ ] 当前阶段
- [ ] 工具调用摘要
- [x] 关键 observation
- [ ] 文件数量和风险
- [x] 验证结果
- [ ] 下一步动作

按需展开：

- [ ] 完整命令输出
- [ ] 完整工具参数
- [x] 完整 trace
- [x] 完整 diff

不默认展示完整 diff。默认展示 diff summary：

```text
Changed Files:
1. calculator.py
   +1 -1
   Risk: low
   Reason: single-line logic fix
```

完整 diff 通过 diff viewer 分页查看：

```text
[v] View diff
[n] next file
[p] previous file
[q] back
```

LLM 上下文默认使用结构化 diff summary，不把完整 diff 全量塞进模型上下文。

---

## 6. LLM Provider 策略

MendCode 使用统一 LLM Provider 抽象。

首批重点支持：

- [ ] OpenAI API
- [ ] Anthropic API
- [x] OpenAI-compatible API

国产模型提供商优先通过 `openai-compatible` 支持，不为每个厂商单独写业务逻辑。

Provider 类型：

```text
openai
anthropic
openai-compatible
```

当前已落地的是 `openai-compatible` 的 Hybrid ToolRegistry provider：优先向支持的模型发送 OpenAI tools schema 并解析原生 `tool_calls`，模型可调用 `read_file` / `list_dir` / `glob_file_search` / `rg` / `search_code` / `git` / `run_shell_command` / `run_command` / `apply_patch` 等结构化工具。JSON Action 仍保留为不支持原生 tool call、模型降级或 endpoint 明确拒绝 `tools` 参数时的 fallback。MendCode 继续负责 schema 校验、权限判断、工具执行和 trace，工具调用不会绕过 Guided Mode 的确认边界。Anthropic 原生 tool calling 适配仍未完成。

验证证据：

- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q`
- [x] `PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .`

推荐配置优先级：

```text
built-in defaults
< ~/.config/mendcode/config.toml
< .mendcode/config.toml
< TUI 当前会话设置
```

API key 不写入项目仓库，优先使用环境变量或系统 keyring。

---

## 7. Agent 决策方式

MendCode 不采用“先生成完整计划再机械执行”的模式。

排障场景应采用动态工具调用：

```text
观察当前状态
决定下一步工具
执行工具
读取 observation
再决定下一步
```

核心原则：

`LLM controls intent and next action, MendCode controls execution and safety.`

也就是：

- [ ] 模型决定下一步想做什么
- [x] Provider-driven loop 每步请求下一条 MendCode Action
- [x] 支持 OpenAI 原生 tool call 形式的结构化工具调用
- [x] MendCode 判断动作是否允许
- [x] MendCode 执行工具
- [x] MendCode 记录 trace
- [x] MendCode 保护 worktree 和主工作区边界

第一版动态工具循环开放的工具应控制在最小集合：

- [x] `repo_status`
- [x] `detect_project`
- [x] `run_command`
- [x] `run_shell_command`
- [x] `read_file`
- [x] `list_dir`
- [x] `glob_file_search`
- [x] `rg`
- [x] `git`
- [x] `search_code`
- [x] `apply_patch`
- [x] `apply_patch_to_worktree`
- [x] `show_diff`

---

## 8. 内部 Action 协议

外部适配不同模型 provider，内部统一成 MendCode Action。

架构：

```text
TUI user input
-> Agent Loop
-> LLM Provider Adapter
-> OpenAI / Anthropic / OpenAI-compatible
-> Provider-specific tool call or JSON response
-> Normalize
-> MendCode Action
-> Permission Gate
-> Tool Executor
-> Observation
-> Agent Loop
```

统一 Action 示例：

```json
{
  "type": "tool_call",
  "action": "search_code",
  "reason": "test_add 失败，需要定位 add 函数实现",
  "args": {
    "query": "def add",
    "glob": "*.py"
  }
}
```

Action 类型：

- `assistant_message`
- `tool_call`
- `patch_proposal`
- `user_confirmation_request`
- `final_response`

Provider 层负责把 OpenAI-compatible tool call、Anthropic tool use、OpenAI-compatible JSON text 统一归一化为 MendCode Action。当前已落地 OpenAI-compatible provider 的原生 `tool_calls` 解析和 JSON Action fallback。

业务层只处理：

- [x] `MendCodeAction`
- [x] `PermissionGate`
- [x] `ToolExecutor`
- [x] `Observation`
- [x] `TraceRecorder`

---

## 9. 失败与降级策略

采用分级降级：

`小错误自动纠正，连续失败后停止并交还给用户。`

处理规则：

- [x] Provider 错误可降级为 failed observation
- [ ] 模型输出非法 Action：自动要求模型重试，超过阈值后停止
- [x] 调用不存在工具：形成 rejected observation
- [x] 未授权工具：按权限模式决定确认、拒绝或升级权限
- [x] 普通 shell 命令先经过独立 shell policy，低风险自动执行，中高风险进入确认，明确破坏性命令拒绝
- [x] 工具执行失败：作为 observation 记录
- [x] 失败验证后自动读取失败测试文件并搜索候选实现
- [ ] 连续无进展：停止自动循环，总结已尝试内容，请用户选择下一步
- [ ] patch 后验证失败：最多 `max_attempts` 次重试，超过后保留 trace 和失败 patch

产品原则：

`MendCode 允许模型犯小错，但不允许无限消耗用户时间。`

---

## 10. 记忆与配置

采用用户级 + 项目级组合。

用户级配置：

```text
~/.config/mendcode/config.toml
```

保存：

- 模型偏好
- 默认权限模式
- TUI 展示偏好
- 默认 step budget

项目级配置：

```text
.mendcode/config.toml
```

保存：

- 项目语言
- 默认测试命令
- 默认 lint 命令
- protected paths
- preferred fix scope
- required verification commands

项目级记忆：

```text
.mendcode/memory.md
```

记忆不是模型随便写日记，而是可审查、可编辑的工程备忘录。

MendCode 可以建议写入项目记忆，但默认需要用户确认。

---

## 11. 任务结束后的落地方式

采用：

`根据权限模式决定默认推荐动作。`

Safe Mode：

- 默认推荐保留 worktree + 查看 diff
- 不主动 apply

Guided Mode：

- 默认推荐查看 diff -> apply 到当前工作区
- apply 前必须确认

Full Access Mode：

- 可配置自动 apply 或自动 commit
- 不默认自动 push

Custom Mode：

- 按用户配置执行

`git push` 始终属于高风险动作，即使 Full Mode 也应单独确认。

---

## 12. MVP 边界

第一版 TUI Agent MVP 支持：

- [x] `mendcode` 启动 TUI
- [ ] 轻量 repo scan
- [x] 聊天输入
- [x] 自然语言工具请求输入
- [x] 自然语言 shell 查询输入
- [x] Guided permission mode
- [x] Provider-driven Action loop 底座
- [x] LLM Action loop 的 OpenAI tool-call prompt/context 底座
- [x] JSON Action prompt/context fallback
- [ ] 真实模型端到端修复稳定性验证
- [x] 工具调用摘要展示
- [x] 自然语言工具请求可进入 AgentLoop，由模型选择 `list_dir` / `read_file` / `search_code` 等结构化工具并回传结果
- [x] 本地可读会话日志：消息、intent、chat/shell/tool/turn 结果写入 Markdown 与 JSONL
- [x] 工具：`repo_status` / `detect_project` / `run_command` / `run_shell_command` / `read_file` / `list_dir` / `glob_file_search` / `rg` / `git` / `search_code`
- [x] 生成 patch proposal schema
- [x] 用户确认后 apply 到 worktree 的底层能力
- [x] 运行验证
- [x] diff summary
- [x] trace 记录
- [x] `ReviewSummary` 会话审查摘要模型
- [x] `AttemptRecord` 失败尝试记录模型
- [x] 工程审查收尾
- [x] TUI review action 菜单：`view_diff` / `view_trace` / `apply` / `discard`
- [x] shell 结果展示：command / cwd / exit_code / risk_level / stdout_excerpt / stderr_excerpt
- [x] shell pending confirmation：确认后执行，取消后放弃

第一版不支持：

- [ ] 多任务并行
- [ ] 后台长期运行任务
- [ ] 多仓库切换
- [ ] 复杂布局拖拽
- [ ] 完整配置 UI
- [ ] 项目记忆自动写入
- [ ] commit / push 自动化
- [ ] 复杂 diff viewer
- [ ] 本地模型
- [ ] 多 provider 全量深度适配

---

## 13. MVP 演示剧本

第一版可演示版本的目标不是展示 JSON 补丁执行器，也不是展示固定流程 CLI，而是展示：

`用户在 TUI 中用自然语言描述问题，MendCode 作为本地 Code Agent 动态调用工具，完成可验证的修复尝试。`

用户启动：

```bash
mendcode
```

TUI 显示轻量仓库上下文：

```text
MendCode
repo: /home/wxh/project
branch: main
status: dirty, 3 modified
mode: guided
model: claude-sonnet

Type your task:
>
```

用户输入：

```text
pytest 失败了，帮我定位并修复
```

用户也可以直接输入低风险 shell 查询：

```text
ls
列一下当前目录
git status
```

MendCode 会在当前 repo 根目录执行安全命令，并在聊天流中展示命令、cwd、退出码、风险等级和输出摘要。若用户输入写入、安装、联网或 Git 提交/推送类命令，TUI 会先进入确认状态。

Agent 动态执行：

```text
✓ repo_status
✓ detect_project
✓ run_command: python -m pytest -q
✗ verification failed
  failed_node: tests/test_calculator.py::test_add
  error: AssertionError: assert -1 == 5

✓ read_file tests/test_calculator.py
✓ search_code "def add"
✓ read_file calculator.py
✓ patch_proposal calculator.py (+1 -1)
✓ apply_patch_to_worktree
✓ run_command: python -m pytest -q
✓ verification passed
```

工程审查收尾：

```text
Fix verified in worktree: preview-a31c9

Summary:
- Changed calculator.py (+1 -1)
- Fixed test_add failure
- Verification passed

Actions:
[v] View diff
[t] View trace
[a] Apply to workspace
[d] Discard
```

---

## 14. MVP 验收标准

演示版本通过的标准：

- [x] 用户不需要写 JSON
- [x] 用户不需要提供手工文本替换补丁
- [x] 用户可以只用自然语言描述问题
- [x] Agent 能展示每一步工具调用摘要
- [x] 用户能通过 `/status` 找到当前会话日志文件
- [x] Agent 的修改只发生在 worktree
- [x] 修复结果必须有验证命令证明
- [x] 用户可以查看 diff summary 的底层数据
- [x] 用户可以 apply 或 discard
- [x] 用户可以用自然语言或直接命令执行低风险 shell 查询
- [x] 高风险 shell 命令不会绕过确认直接执行

如果做不到这些，就还不是目标形态下的可演示 TUI Agent MVP。

---

## 15. 与当前 CLI 形态的关系

当前已落地的：

```bash
mendcode fix "<problem>" --test "<command>"
```

是过渡形态，不是最终产品形态。

它的价值是提前沉淀：

- [x] `problem_statement`
- [x] verification execution
- [x] failure parser
- [x] trace
- [x] worktree safety
- [x] session result models: `ReviewSummary` / `AttemptRecord`

后续 TUI 会复用这些底座，但用户主入口应逐步迁移到：

```bash
mendcode
```

然后在 TUI 中自然语言对话完成任务。

当前接续点：

- [x] `AgentSession.run_turn()` 单轮会话抽象
- [x] `session.turns` 持续追加，为后续多轮聊天保留状态
