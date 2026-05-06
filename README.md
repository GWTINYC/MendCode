# MendCode

MendCode 是一个面向本地代码仓库的可进化 Code Agent Runtime。它以 Textual TUI 作为主要交互入口，让用户用自然语言完成代码查看、问题定位、修改修复、测试验证和任务复盘。

项目的核心目标是解决长链路代码任务中的三个关键问题：工具调用失控、上下文膨胀、经验难沉淀。MendCode 不让模型直接操控终端，也不允许模型凭空回答本地事实；所有本地能力都通过结构化工具、权限策略、路径边界和真实 observation 进入 Agent Loop。

```text
自然语言任务
-> 模型选择工具
-> 参数校验与权限控制
-> 本地执行
-> Observation 回传
-> 基于证据回答、修复或继续调用工具
-> Trace / Memory / Benchmark 复盘
```

## 项目定位

MendCode 面向的是本地代码仓库中的真实开发任务，而不是一次性的聊天问答。它强调：

- 可控工具调用：文件、搜索、Shell、Git、Patch、测试验证等能力统一由 ToolRegistry 注册，并经过 PermissionPolicy 管控。
- 可持续上下文：通过 Layered Memory、文件摘要、Observation 压缩和上下文管理，减少重复读文件和无效历史堆叠。
- 可复盘演进：记录 JSONL Trace，将失败任务、工具调用、修复过程和验证结果转化为可审查的规则、记忆和 Skill 候选。

目标成果包括：支持 20 多种本地工具、3 档权限模式，在固定本地代码任务评测集中持续提升工具链路通过率、高风险命令拦截率，并降低长任务中的上下文消耗。

## 核心架构

### Agent Runtime

MendCode 使用 OpenAI-compatible Tool Calling 作为模型接入方式。模型只能通过 provider-visible tool schema 请求本地能力，Runtime 负责执行工具调用、回传 observation、控制 step budget，并在最终回答前检查是否存在失败或缺失证据。

### ToolRegistry + PermissionPolicy

所有工具都通过 ToolRegistry 统一描述参数、风险等级、schema 和 executor。ToolPool 会根据当前权限和任务场景裁剪模型可见工具面；PermissionPolicy 则负责在工具执行前处理路径限制、Shell 风险、写入操作和用户确认。

权限模式收敛为三档：

- `read-only`：读取、搜索、状态查询等低风险能力。
- `workspace-write`：允许受控修改工作区，但危险操作仍需确认。
- `danger-full-access`：用于高风险场景，仍保留策略检查和路径边界。

### Layered Memory + Evolution

MendCode 将任务状态、文件摘要、项目事实、失败经验和运行 trace 分层保存。短期记忆服务当前任务，中期记忆减少重复读取，长期记忆沉淀经过审查的经验。

自进化机制以 JSONL Trace 为依据：失败归因先生成候选，再由用户在 TUI 中审查、编辑、接受或拒绝。被接受的规则和记忆才会影响后续 Agent 行为。

## 当前能力

当前版本已经具备：

- TUI 自然语言对话入口。
- OpenAI-compatible 原生 tool call 主链路。
- 文件读取、目录查看、代码搜索、Patch、Shell、Git、测试验证、进程、LSP、记忆和 trace 分析等工具。
- 低风险工具自动执行，高风险工具确认或拒绝。
- Conversation log、JSONL trace、session resume 和离线分析。
- Layered Memory 第一版和可审查的 evolution rule。
- PTY live 测试、scenario tests 和 benchmark gate。

后续重点会继续推进 tokenizer-aware context management、repo map、SKILL.md 流程沉淀、TUI 审查面板和 benchmark-driven evolution。

## 快速开始

运行基础验证：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

启动 TUI：

```bash
mendcode
```

配置 OpenAI-compatible provider：

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL="your-model"
export MENDCODE_BASE_URL="https://your-provider.example/v1"
export MENDCODE_API_KEY="your-api-key"
```

运行 benchmark gate：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt \
  python -m app.runtime.tui_scenario_audit \
  --benchmark-manifest tests/scenarios/benchmark_manifest.json \
  --benchmark-output data/benchmark-reports/latest.json \
  --analysis-report-dir data/analysis-reports
```

## 本地产物

`data/` 用于保存本地运行产物，包括 conversations、traces、memory、evolution rules、process logs、benchmark reports 和 analysis reports。这些内容默认不提交到仓库。

## 文档

- `MendCode_全局路线图.md`：项目长期方向和阶段规划。
- `MendCode_开发方案.md`：当前开发状态、模块边界和后续任务。
- `MendCode_问题记录.md`：关键问题、风险和工程约束记录。

MendCode 的开发原则是：本地事实必须来自工具 observation，高风险操作必须经过权限策略，修复结果必须有验证证据，长期记忆和 Skill 沉淀必须可审查、可追踪、可回滚。
