# MendCode

MendCode 是一款面向本地代码仓的可验证修复型 Code Agent。

它的目标形态是终端里的 TUI Code Agent 工作台：用户在本地仓库中运行
`mendcode`，用自然语言描述问题，Agent 在隔离 git worktree 中读取代码、
运行验证命令、提出补丁、复跑验证，并在用户确认后再把改动应用回主工作区。

当前版本已经具备 TUI 主线的早期可用切片，但还不是完整全屏 TUI。更准确地说，
当前 `mendcode` 是一个单轮、TUI-shaped 的终端交互入口。

## 当前能力

- Typer CLI 入口：`mendcode`、`mendcode fix`、`mendcode health`、`mendcode version`
- 单轮 `mendcode` 交互：输入任务描述和验证命令，展示工具摘要和审查摘要
- Provider-driven Agent loop：每一步由 provider 返回一个 MendCode Action
- 默认 `scripted` provider：用于基础验证链路和开发 smoke test
- OpenAI-compatible JSON Action provider：支持 OpenAI-compatible chat completions endpoint
- Minimax provider alias：`MENDCODE_PROVIDER=minimax` 走同一条 OpenAI-compatible 路径
- 工具调用：`repo_status`、`detect_project`、`run_command`、`read_file`、`search_code`
- Patch proposal：模型可返回 unified diff，MendCode 在隔离 worktree 中应用
- Verification gate：没有通过验证时不会把结果标记为已完成
- Review actions：`view_diff`、`view_trace`、`apply`、`discard`
- JSONL trace：每次 Agent loop 会写入 `data/traces/`
- 安全边界：修改先进入 `.worktrees/`，`apply` 到主工作区前需要用户显式选择

## 环境要求

- Python `>=3.11`
- Git
- `rg` / ripgrep，供 `search_code` 使用

注意：如果系统默认 `python` 是 3.8，不能直接用于安装和运行本项目。可以使用
Python 3.11+ 虚拟环境，或用 `uv --python 3.12` 运行。

## 安装

推荐使用虚拟环境：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

安装完成后确认 CLI 可用：

```bash
mendcode health
mendcode version
```

如果你没有激活虚拟环境，可以直接使用虚拟环境里的脚本：

```bash
.venv/bin/mendcode health
```

也可以在开发环境中直接运行模块：

```bash
python -m app.cli.main health
python -m app.cli.main version
```

如果你使用 `uv`，可以不创建长期虚拟环境，直接运行：

```bash
uv run --isolated --python 3.12 --with-requirements requirements.txt --with-editable . mendcode health
uv run --isolated --python 3.12 --with-requirements requirements.txt --with-editable . mendcode
```

## 快速开始

在要修复的 git 仓库中运行：

```bash
mendcode
```

MendCode 会先显示当前仓库上下文：

```text
MendCode
repo: /path/to/project
branch: main
status: clean
mode: guided
```

然后要求输入：

```text
Type your task: pytest 失败了，请定位并修复
Verification command: python -m pytest -q
```

执行结束后会展示：

- `Tool Summary`：Agent 调用过哪些工具、每步是否成功
- `Review`：整体状态、验证状态、worktree 路径、trace 路径、变更文件、推荐动作
- `Review Actions`：可选的审查/落地动作

如果修复已通过验证，常见操作顺序是：

```text
Review action: view_diff
Review action: apply
```

如果不想保留本次 worktree：

```text
Review action: discard
```

如果只想退出，不输入 action，直接回车即可。

## 主要命令

### `mendcode`

最终主入口的早期单轮实现。

```bash
mendcode
```

当前行为：

1. 展示当前仓库路径、分支、clean/dirty 状态
2. 读取用户自然语言任务描述
3. 读取用户提供的验证命令
4. 创建隔离 worktree
5. 运行 Agent loop
6. 展示工具摘要和审查摘要
7. 提供 `view_diff` / `view_trace` / `apply` / `discard`

### `mendcode fix`

过渡入口，不是最终产品主线。适合脚本化 smoke test 或调试 Agent loop。

```bash
mendcode fix "pytest 失败了，请定位并修复" --repo . --test "python -m pytest -q"
```

支持多个验证命令：

```bash
mendcode fix "修复失败测试" \
  --repo . \
  --test "python -m pytest -q" \
  --test "python -m ruff check ."
```

当前行为：

- 创建隔离 worktree
- 运行 provider-driven Agent loop
- 执行验证命令
- 提取 pytest 风格失败信息
- 输出 workspace path 和 trace path

注意：`fix` 不提供交互式 review action 菜单；新增能力优先接入 `mendcode` 主入口。

### `mendcode health`

检查 MendCode 基础路径配置：

```bash
mendcode health
```

会输出：

- app name / version
- project root
- traces directory
- workspace root

### `mendcode version`

输出当前版本：

```bash
mendcode version
```

## Review Actions

`mendcode` 单轮结束后会根据结果给出可用 action。

### `view_diff`

展示 worktree 中相对 `HEAD` 的 diff summary 和完整 diff。

### `view_trace`

展示本次 Agent loop 的 JSONL trace 摘要。trace 文件保存在：

```text
data/traces/
```

### `apply`

把已验证的 worktree 改动应用回主工作区。

安全策略：

- 主工作区必须是 clean
- worktree diff 必须能通过 `git apply --check`
- 如果主工作区有未提交改动，MendCode 会拒绝 apply
- 如果 patch 不能干净应用，MendCode 会拒绝 apply
- 拒绝 apply 时不会删除 worktree

### `discard`

删除本次隔离 worktree，不应用改动到主工作区。trace 文件仍会保留。

## Provider 配置

默认 provider 是 `scripted`。它适合开发验证，但不会像真实 LLM 一样自主读代码、
生成补丁。要尝试真实模型修复，需要配置 OpenAI-compatible provider。

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
MENDCODE_PROVIDER=openai-compatible
MENDCODE_MODEL="<model>"
MENDCODE_BASE_URL="<base-url>"
MENDCODE_API_KEY="<key>"
MENDCODE_PROVIDER_TIMEOUT_SECONDS=60
```

Minimax-compatible endpoint 可以使用：

```dotenv
MENDCODE_PROVIDER=minimax
MENDCODE_MODEL="<model>"
MENDCODE_BASE_URL="<base-url>"
MENDCODE_API_KEY="<key>"
```

环境变量优先级高于 `.env` 文件。`.env` 已被 git 忽略，不要把真实 API key
提交到仓库。

当前 provider 约定：

- 模型每一步必须返回一个 MendCode Action JSON 对象
- MendCode 负责 schema 校验、权限判断、工具执行和 trace
- 当前还没有接 OpenAI / Anthropic 原生 tool calling 格式

## 推荐使用方式

1. 先保证当前仓库是 git 仓库。
2. 使用前尽量保持主工作区 clean：

   ```bash
   git status --short
   ```

3. 优先使用明确、可重复的验证命令：

   ```bash
   python -m pytest -q
   python -m ruff check .
   ```

4. 运行：

   ```bash
   mendcode
   ```

5. 修复成功后先 `view_diff`，确认后再 `apply`。
6. 不满意结果时使用 `discard`。

## 当前限制

- `mendcode` 目前是单轮交互，不是完整多轮聊天 TUI
- 默认 `scripted` provider 不会真正自主修复代码
- 真实模型修复稳定性仍在建设中
- 尚未支持 OpenAI / Anthropic 原生 tool calling adapter
- 尚未支持 `max_attempts` 自动重试
- 尚未支持完整 diff viewer、日志分页、配置 UI、项目记忆、commit/push 自动化
- `apply` 只采用保守策略，不做三方合并，不覆盖用户本地改动

## 常见问题

### 为什么运行 `mendcode` 提示 `command not found`？

通常是因为项目还没有被安装到当前 shell 环境中，或者安装到了某个虚拟环境，
但你当前终端没有激活这个虚拟环境。

本项目的命令行入口定义在 `pyproject.toml`：

```toml
[project.scripts]
mendcode = "app.cli.main:app"
```

只有执行过下面的安装命令后，`mendcode` 脚本才会被生成：

```bash
pip install -e ".[dev]"
```

如果你使用虚拟环境，还必须先激活它：

```bash
source .venv/bin/activate
mendcode health
```

如果没有激活虚拟环境，可以这样运行：

```bash
.venv/bin/mendcode health
```

在当前仓库开发时，也可以绕过 console script，直接运行模块：

```bash
python -m app.cli.main health
python -m app.cli.main
```

如果你的系统默认 `python` 是 3.8，请使用 Python 3.11+，例如：

```bash
uv run --isolated --python 3.12 --with-requirements requirements.txt --with-editable . mendcode health
```

### 为什么默认运行后没有真正修代码？

默认 `MENDCODE_PROVIDER` 是 `scripted`。它主要用于跑通基础链路，不具备真实 LLM
的代码理解和补丁生成能力。要让 MendCode 尝试自主修复，需要配置
`openai-compatible` 或 `minimax` provider。

### MendCode 会直接改我的主工作区吗？

不会。Agent 的补丁先进入 `.worktrees/` 下的隔离 worktree。只有你在 Review Actions
中明确输入 `apply`，并且主工作区 clean、patch 可干净应用时，MendCode 才会把改动
应用回主工作区。

## 开发验证

运行测试：

```bash
uv run --isolated --python 3.12 --with-requirements requirements.txt --with-editable . python -m pytest -q
```

运行 lint：

```bash
uv run --isolated --python 3.12 --with-requirements requirements.txt --with-editable . python -m ruff check .
```
