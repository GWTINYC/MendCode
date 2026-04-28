# MendCode

MendCode 是一个面向本地代码仓库的 TUI Code Agent Runtime。它从当前仓库启动，接受自然语言任务，让大模型通过结构化工具读取代码、搜索文件、执行受控命令、应用补丁并运行验证，最后基于真实 observation 给出回答或修复结果。

该项目关注的是代码任务拆成一条可控、可复盘的本地执行链路：

```text
自然语言任务
-> Agent Runtime
-> 模型选择工具
-> 权限校验
-> 本地执行
-> Observation 回传
-> 继续调用工具或给出最终回答
-> Trace / Conversation Log 落盘
```

## 项目目标

MendCode 的目标是成为一个轻量但可进化的本地 Code Agent Runtime，重点解决代码 Agent 在多轮任务中常见的几个问题：

- 本地事实容易被模型编造，而不是来自真实文件、Git 状态或命令输出。
- 工具调用、Shell 执行、文件写入和 Git 操作缺少统一权限边界。
- 长任务中上下文不断膨胀，模型重复读文件、重复搜索、丢失任务状态。
- 修复是否真的成功缺少验证闭环，失败原因也难以复盘。
- 成功经验和失败经验无法沉淀，下一轮任务又从零开始。

因此，MendCode 的设计重点放在三件事上：结构化工具、分层记忆和可复盘的自进化机制。

## 工具系统

MendCode 使用 `Agent Runtime + ToolRegistry + PermissionPolicy` 作为核心工具架构。

`ToolRegistry` 负责统一注册工具、生成 OpenAI-compatible tool schema、校验参数并绑定本地 executor。`PermissionPolicy` 负责在工具执行前判断当前权限模式、工具风险等级和具体 Shell 风险，避免模型绕过本地安全边界。Agent Runtime 则负责把“模型 tool call -> 本地执行 -> observation -> 下一轮模型输入”串成完整循环。

当前已经接入的主要工具包括：

- 文件与代码：`read_file`、`list_dir`、`glob_file_search`、`rg` / `search_code`
- 写入与补丁：`write_file`、`edit_file`、`apply_patch`
- Shell 与验证：`run_shell_command`、`run_command`
- Git 与项目状态：`git`、`repo_status`、`show_diff`、`detect_project`
- 会话与工具发现：`session_status`、`tool_search`
- 记忆与摘要：`memory_search`、`memory_write`、`file_summary_read`、`file_summary_refresh`、`trace_analyze`
- 后台与语言服务：`process_*`、基础 `lsp`

工具并不是一股脑暴露给模型。MendCode 会通过 `ToolPool` 按任务场景和权限模式裁剪工具面：只读问答默认只能看到读取、搜索、Git 状态、记忆查询等低风险工具；写文件、Patch、长期记忆写入、后台进程和危险 Shell 不会出现在普通只读对话里。

当前权限体系正在收敛到三档：

- `read-only`：只允许读取、搜索、状态查询等低风险工具。
- `workspace-write`：允许工作区写入和受控修复，但危险命令仍需确认。
- `danger-full-access`：用于更高风险操作，仍保留策略检查和路径边界。

其中 `run_command` 只用于声明过的验证命令，普通诊断命令走 `run_shell_command`。这个区分很重要：修复是否成功必须由明确的 verification gate 证明，不能让模型随便跑一个命令就声称完成。

## 记忆系统

MendCode 已经落地 Layered Memory 的第一切片：本地 JSONL 记忆库、文件摘要缓存、记忆查询工具和失败 trace 分析工具。

记忆系统会把不同类型的信息分层保存：

- `project_fact`：项目事实，例如技术栈、常用验证命令、重要约定。
- `task_state`：当前任务状态和阶段性决策。
- `file_summary`：按文件内容 hash 缓存的文件摘要。
- `failure_lesson`：失败任务中提炼出的经验候选。
- `trace_insight`：从运行 trace 中分析出的结构化线索。

这些信息不会直接无限塞进 prompt。模型需要时通过 `memory_search` 显式召回，文件摘要通过 `file_summary_read` 按 repo-relative path 和内容 hash 校验，conversation log 和 tool result 也会做 compact，避免把完整文件内容、长目录列表和重复 observation 反复塞回上下文。

目前记忆写入保持保守：`memory_write` 和 `file_summary_refresh` 属于长期状态写入能力，按高风险工具处理，默认/guided 工具池不暴露。`trace_analyze` 默认只读，只能分析 `data/traces/` 内的 trace 文件，并生成可审查的失败经验候选，不会静默写入长期记忆。

后续记忆系统会继续补齐自动相关性召回、长会话 compact、重复读文件统计和人工审查入口，让上下文压缩变成可度量的 Runtime 能力。

## 自进化方向

MendCode 的长期方向是 `SKILL.md + JSONL Trace-driven Evolution`。

这部分还在演进中，目标是把高频任务流程沉淀成可复用 Skill，例如 Debug、Test-Fix、Review、Repo-Map 等；同时基于每轮运行产生的 JSONL Trace 分析失败原因，反向优化 memory、skill、prompt rule、tool schema 和测试集。

预期闭环是：

```text
任务执行
-> Trace 记录工具调用、错误和验证结果
-> 失败归因生成 lesson 候选
-> 用户审查后沉淀到 memory / skill / prompt rule
-> Benchmark 和 PTY 场景回归验证收益
```

这条路线的原则是保守演进：失败经验可以被分析，但不能自动固化；长期记忆和 Skill 更新必须可追溯、可审查、可回滚。

## 快速开始

安装依赖并运行测试：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

在仓库中启动 TUI：

```bash
mendcode
```

可以尝试这些自然语言请求：

```text
帮我查看当前文件夹里的文件
读取 README.md 的前几行
看下 git status
之前记录的 pytest 命令是什么
pytest 失败了，帮我修复
/sessions
/resume <session_id>
```

直接 CLI 修复仍作为过渡入口保留：

```bash
mendcode fix "fix the failing test" --test "python -m pytest -q"
```

## Provider 配置

当前主线使用 OpenAI-compatible chat completions，并要求 provider 支持原生 tool calls。如果 provider 不支持 tools，MendCode 会明确失败，而不是退回普通聊天去编造本地事实。

需要配置的环境变量：

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL="your-model"
export MENDCODE_BASE_URL="https://your-provider.example/v1"
export MENDCODE_API_KEY="your-api-key"
```

API key 不应写入项目仓库。优先使用环境变量或用户本地配置。

## 架构地图

```text
app/
├── agent/          # Provider adapter、prompt context、兼容层和会话模型
├── memory/         # Layered Memory、JSONL store、文件摘要缓存
├── runtime/        # Agent Runtime、运行循环、final response gate、session store
├── tools/          # ToolRegistry、工具 schema、工具 executor
├── tui/            # Textual UI、TuiController、slash commands、对话日志
├── workspace/      # ShellPolicy、ShellExecutor、验证 executor、worktree helper
├── schemas/        # MendCodeAction、Observation、trace 和 verification schema
└── tracing/        # JSONL trace recorder
```

几个关键约束：

- 本地事实必须来自工具 observation，不能来自普通聊天文本。
- 面向模型的工具 schema 必须来自 `ToolPool`，不能直接暴露完整注册表。
- 工具执行前必须经过权限策略和路径边界检查。
- 修复任务必须有验证结果，不能只靠模型描述“已修复”。
- 对话日志保存摘要和定位指针，完整 payload 放在 trace 中按需查看。
- 长期记忆必须可审查，不能静默固化错误事实。

## data 目录

`data/` 用于存放本地运行产物，不是源码目录：

- `data/conversations/`：Markdown 和 JSONL 对话日志。
- `data/traces/`：Agent Runtime trace。
- `data/memory/`：本地 layered memory JSONL 和文件摘要记录。
- `data/processes/`：后台进程日志。
- `data/reference-*` 或其它本地分析 clone：参考材料，默认被 git 忽略。

不要提交运行日志或本地 clone 的参考仓库。

## 文档

根目录保留几份长期文档：

- `README.md`：项目概览、启动方式、当前状态和文档导航。
- `MendCode_全局路线图.md`：整体方向和阶段优先级。
- `MendCode_开发方案.md`：详细实现状态、模块契约、测试策略和下一步任务。
- `MendCode_问题记录.md`：架构相关问题、风险和约束。

每轮开发后，如果实现现实发生变化，需要更新 `MendCode_开发方案.md`。只有高层方向或阶段优先级变化时才更新路线图。发现新的反复风险或架构约束时，更新问题记录。

## 开发原则

任何有意义的改动都必须维护这条主线：

```text
模型请求工具
-> MendCode 校验权限
-> MendCode 在本地执行
-> Observation 回传模型
-> 最终回答或修复基于证据
```

如果某项改动削弱了这个闭环，就不应该合入。
