# MendCode

MendCode 是一个运行在本地代码仓库中的 TUI Code Agent，用于仓库查看、问题修复、结果验证和工程审查。它从当前仓库启动，接受自然语言请求，让模型调用结构化工具，并在本地安全规则下执行这些工具，最后把对话过程保存下来，方便后续复盘。

当前产品方向是：

```text
自然语言输入
-> 意图路由
-> 模型发起工具调用
-> 本地权限校验
-> 结构化工具执行
-> observation 回传给模型
-> 基于证据的最终回答或已验证修复
```

## 当前状态

MendCode 目前已经支持早期 TUI Agent 工作流：

- 自然语言 chat、shell、tool、repair 路由。
- 以 OpenAI-compatible 原生 `tool_calls` 作为主要模型工具调用路径。
- 对拒绝 tools 参数或不支持工具调用的 provider / endpoint，保留 JSON Action fallback。
- 结构化工具包括 `read_file`、`list_dir`、`glob_file_search`、`rg` / `search_code`、只读 `git`、`run_shell_command`、`run_command`、`apply_patch`、`repo_status`、`detect_project` 和 `show_diff`。
- 通过 `allowed_tools` 按场景裁剪暴露给模型的工具，避免只读请求暴露写入工具。
- Guided 权限模式下，低风险只读动作自动执行，高风险命令需要确认或直接拒绝。
- `run_command` 只用于验证命令，与普通 shell 执行分离。
- 对话日志以 Markdown 和 JSONL 写入 `data/conversations/`。
- AgentLoop action 会产生 trace 输出。
- 支持基于 worktree 的修复路径和审查动作。

MendCode 还不是一个打磨完整的最终产品。当前工程重点已经切到 Runtime-first 重构：让 TUI、Provider、ToolRegistry、PermissionPolicy、Session 和 Trace 都围绕同一个本地 Agent Runtime 收敛。

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

TUI 中可以尝试：

```text
帮我查看当前文件夹里的文件
读取 README.md 的前几行
看下 git status
pytest 失败了，帮我修复
```

直接 CLI 修复仍作为过渡入口保留：

```bash
mendcode fix "fix the failing test" --test "python -m pytest -q"
```

## Provider 配置

当前主要支持 OpenAI-compatible chat completions。

需要配置的环境变量：

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL="your-model"
export MENDCODE_BASE_URL="https://your-provider.example/v1"
export MENDCODE_API_KEY="your-api-key"
```

API key 不能写入项目仓库。优先使用环境变量或用户本地配置。

## 架构地图

```text
app/
├── agent/          # 当前 AgentLoop、provider adapter、prompt context、权限、会话
├── tools/          # ToolRegistry、工具 schema、只读工具和 patch 工具
├── tui/            # Textual UI、意图路由、对话日志
├── workspace/      # shell policy/executor、验证 executor、worktree helper
├── schemas/        # MendCodeAction、Observation、trace 和 verification schema
└── tracing/        # JSONL trace recorder
```

关键运行时契约：

- `ToolRegistry` 是工具 schema、风险等级和 executor 的来源。
- `repo_status`、`detect_project`、`show_diff` 等只读内置能力也应通过 `ToolRegistry` 暴露。
- `AgentLoop` 是执行边界，在运行 native tool call 前必须重新检查 allowed tools。
- `PermissionPolicy` 逻辑必须保持集中，避免重复维护风险表。
- 工具 observation 必须足够结构化，既能回传给模型，也能持久化到日志。
- 本地事实必须来自工具结果，不能来自普通聊天文本。

## 文档

根目录文档保持精简：

- `README.md`：项目概览、启动方式、当前状态和文档导航。
- `MendCode_全局路线图.md`：简要长期方向和阶段优先级。
- `MendCode_开发方案.md`：详细实现状态、子系统契约和下一步任务。
- `MendCode_问题记录.md`：架构相关问题、风险和约束。

每轮开发后，如果实现现实发生变化，需要更新 `MendCode_开发方案.md`。只有高层方向或阶段优先级变化时才更新路线图。发现新的反复风险或架构约束时，更新问题记录。

## data 目录

`data/` 用于存放本地运行产物，不是源码目录：

- `data/conversations/`：Markdown 和 JSONL 对话日志。
- `data/traces/`：AgentLoop trace。
- `data/reference-*` 或其它本地分析 clone：参考材料，默认被 git 忽略。

不要提交运行日志或本地 clone 的参考仓库。

## 开发规则

任何有意义的改动都必须维护核心闭环：

```text
模型请求工具
-> MendCode 校验权限
-> MendCode 在本地执行
-> observation 回传模型
-> 最终回答或修复基于证据
```

如果某项改动削弱了这个闭环，就不应该合入。
