# MendCode Phase 0 Foundation Design

## 1. 背景

当前仓库仍处于初始化阶段，只有基础说明文档和依赖文件，尚未形成可运行的应用骨架。根据已确认的项目路线，Phase 0 的目标不是实现 Agent 主循环或修复能力，而是建立一个稳定、可测试、可扩展的工程基础，为后续 Phase 1 的任务执行主链提供明确边界。

本阶段采用以下已确认约束：

- worktree 位置使用项目内隐藏目录 `.worktrees/`
- Phase 0 完成度为“工程骨架 + 最小任务入口”
- 使用 `pyproject.toml` 作为主配置，同时保留 `requirements.txt` 兼容现有依赖方式
- 当前实现环境按 Python 3.11 对齐，而不是预期中的 3.12

## 2. 目标

Phase 0 目标是把仓库推进到“可以启动、可以校验任务文件、可以输出最小 trace、可以运行测试和健康检查”的状态。

完成后系统应具备以下能力：

- 提供稳定的 Python 包结构
- 提供 CLI 主入口
- 提供最小 FastAPI 服务入口
- 提供 `TaskSpec` 与 `TraceEvent` 等基础 schema
- 提供最小 JSONL trace 记录器
- 提供任务文件读取、校验、摘要展示能力
- 提供基础单元测试和集成测试

## 3. 非目标

本阶段明确不包含以下内容：

- orchestrator 主循环
- 工具系统正式实现
- workspace/worktree 管理实现
- repo map、日志蒸馏、记忆加载
- 自动补丁生成
- 验证命令执行
- 端到端修复任务闭环

这些内容属于后续阶段，不应提前引入空抽象或占位实现污染边界。

## 4. 设计原则

### 4.1 主线优先

Phase 0 只实现后续阶段一定会复用的稳定边界：配置、schema、CLI、trace、路径管理、健康检查。

### 4.2 抽象最小化

不为尚未落地的能力提前搭建复杂目录和接口。`orchestrator/`、`tools/`、`workspace/` 暂不进入代码实现范围，只在设计层预留未来位置。

### 4.3 可验证优先

每个新增能力都必须有最小可运行验证方式，例如 CLI 命令、API 健康检查、pytest 用例或 trace 文件输出。

### 4.4 后续兼容

虽然本阶段不实现任务执行，但 `TaskSpec`、路径约定和 trace 结构必须考虑后续 Phase 1 直接接入，避免下一阶段推倒重来。

### 4.5 工程配置去重复

基础工程配置应避免无意义重复和运行时污染。对于 `pyproject.toml`：

- 包版本应与应用元数据保持单一事实来源
- 测试与 lint 工具应放在开发依赖中，而不是运行时依赖中
- 运行时依赖应只保留 Phase 0 真正需要的应用依赖

## 5. 目录结构

Phase 0 完成后的建议目录如下：

```text
MendCode/
├─ app/
│  ├─ __init__.py
│  ├─ cli/
│  │  ├─ __init__.py
│  │  └─ main.py
│  ├─ api/
│  │  ├─ __init__.py
│  │  └─ server.py
│  ├─ schemas/
│  │  ├─ __init__.py
│  │  ├─ task.py
│  │  └─ trace.py
│  ├─ config/
│  │  ├─ __init__.py
│  │  └─ settings.py
│  ├─ tracing/
│  │  ├─ __init__.py
│  │  └─ recorder.py
│  └─ core/
│     ├─ __init__.py
│     └─ paths.py
├─ data/
│  ├─ tasks/
│  └─ traces/
├─ tests/
│  ├─ unit/
│  └─ integration/
├─ pyproject.toml
├─ requirements.txt
└─ README.md
```

## 6. 模块职责

### 6.1 `app/cli/main.py`

职责：

- 作为 CLI 主入口
- 对外暴露 Phase 0 所需命令

首批命令范围：

- `mendcode version`
- `mendcode health`
- `mendcode task validate <file>`
- `mendcode task show <file>`

设计要求：

- 使用 Typer 实现
- 输出对人类可读
- 校验失败时返回非零退出码
- 对任务文件缺失、JSON 非法、schema 非法等常见错误给出面向用户的简洁提示，而不是直接暴露原始异常
- 对目录路径、权限错误、不可读文件等一般 `OSError` 输入同样应返回简洁错误，而不是 traceback

### 6.2 `app/api/server.py`

职责：

- 提供最小 FastAPI 应用
- 仅实现健康检查接口 `/healthz`

返回内容至少包含：

- 应用名
- 版本号
- 时间戳
- 默认数据目录
- 状态字段

### 6.3 `app/schemas/task.py`

职责：

- 定义最小 `TaskSpec`
- 封装任务输入结构

建议字段：

- `task_id`
- `task_type`
- `title`
- `repo_path`
- `entry_artifacts`
- `verification_commands`
- `allowed_tools`
- `metadata`

约束：

- `task_type` 首阶段只允许 `ci_fix`、`test_regression_fix`、`pr_review`
- `entry_artifacts`、`verification_commands` 必须保留，为下一阶段直接复用
- schema 默认应拒绝未知字段，避免任务文件中的拼写错误被静默吞掉

### 6.4 `app/schemas/trace.py`

职责：

- 定义最小 `TraceEvent`
- 为 JSONL trace 提供结构化输出
- 对 trace 基础字段做严格校验，避免拼写错误被静默吞掉

建议字段：

- `run_id`
- `event_type`
- `message`
- `timestamp`
- `payload`

其中 `run_id` 需要满足可安全映射为单个文件名的约束，不能包含路径穿越或平台不兼容字符。
建议采用白名单约束，而不是只做黑名单过滤。

### 6.5 `app/config/settings.py`

职责：

- 统一环境变量读取
- 管理默认目录与运行时配置
- 保持纯解析职责，不在模块导入期执行隐藏副作用

至少统一这些配置：

- 项目根目录
- `data/tasks`
- `data/traces`
- 应用版本

应用版本在工程配置上应由 `app.__version__` 统一导出，以避免 `pyproject.toml` 和运行时代码形成双源维护。

当 `MENDCODE_PROJECT_ROOT` 未设置时，默认项目根目录应优先取当前工作目录，而不是包文件所在目录。这样在源码树运行和普通安装场景下都更符合 CLI / API 的使用直觉。

如果后续需要读取 `.env`，应在 CLI 或 API 入口层显式加载，而不是在 `settings.py` 导入时自动执行。

### 6.6 `app/core/paths.py`

职责：

- 提供路径解析与目录确保逻辑
- 避免路径拼接散落在 CLI、API 和 trace 模块中

### 6.7 `app/tracing/recorder.py`

职责：

- 提供最小 trace 记录器
- 以 JSONL 方式把 `TraceEvent` 写入 `data/traces/`

约束：

- 单次写入一个事件
- 自动创建 trace 目录
- 文件命名稳定，便于后续按 `run_id` 聚合
- 不应直接信任未校验的 `run_id` 去拼接路径

## 7. 任务文件格式

Phase 0 任务文件使用 JSON 格式，避免在项目初始化阶段引入 YAML 解析与额外格式讨论。

示例：

```json
{
  "task_id": "demo-ci-001",
  "task_type": "ci_fix",
  "title": "Fix failing unit test",
  "repo_path": "/abs/path/to/repo",
  "entry_artifacts": {
    "log": "pytest failed: test_xxx"
  },
  "verification_commands": [
    "pytest -q"
  ],
  "allowed_tools": [
    "read_file",
    "search_code"
  ],
  "metadata": {}
}
```

该格式只承担“被系统读取和校验”的职责，不承担执行语义。

仓库内提供的 demo 任务文件应被自动化测试直接加载，避免样例文件和 schema 随时间漂移。

## 8. Phase 0 数据流

### 8.1 `mendcode health`

流程：

- 加载 settings
- 确认默认目录存在或可创建
- 输出运行状态与关键路径摘要

用途：

- 作为本地安装与初始化检查命令

### 8.2 `mendcode task validate <file>`

流程：

- 读取 JSON 文件
- 反序列化为 `TaskSpec`
- 进行字段合法性校验
- 输出成功或错误摘要

用途：

- 作为后续任务接入的最小入口

### 8.3 `mendcode task show <file>`

流程：

- 先复用 `validate` 逻辑
- 以人类可读格式打印任务摘要
- 生成一个最小 `TraceEvent`
- 将 trace 写入 `data/traces/`

用途：

- 打通“输入 -> 校验 -> 留痕”的最短链路

### 8.4 `/healthz`

流程：

- 创建 FastAPI 应用
- 暴露健康检查接口
- 返回 JSON 状态对象

用途：

- 为后续 API 化预留最小入口

## 9. 测试策略

Phase 0 采用最小但完整的测试集合。

### 9.1 单元测试

覆盖以下能力：

- 合法 `TaskSpec` 能成功解析
- 缺少必填字段时报错
- 非法 `task_type` 被拒绝
- `TraceRecorder` 能输出 JSONL
- `Settings` 能返回默认路径

### 9.2 集成测试

覆盖以下能力：

- `mendcode task validate data/tasks/demo.json` 成功执行
- `mendcode task show data/tasks/demo.json` 成功执行并生成 trace 文件
- FastAPI `/healthz` 返回 200

### 9.3 本阶段不做的测试

- patch 执行链路测试
- shell 验证命令测试
- orchestrator 状态流测试
- worktree 测试
- 端到端修复任务测试

## 10. 验收标准

Phase 0 完成时必须满足以下条件：

- `pytest` 全部通过
- `ruff check` 通过
- `mendcode health` 可运行
- `mendcode task validate <demo-file>` 可运行
- `mendcode task show <demo-file>` 可运行并生成 trace 文件
- `uvicorn app.api.server:app` 可启动
- `/healthz` 返回 200
- `pyproject.toml` 成为主配置来源
- `requirements.txt` 继续保留
- `pyproject.toml` 中的版本定义与运行时元数据保持单一来源
- `pytest`、`pytest-asyncio`、`ruff` 不作为运行时依赖安装

## 11. 风险与控制

### 11.1 过早抽象

风险：

- 为尚未实现的 orchestrator 或 tool system 设计过多空壳

控制：

- 本阶段只实现确定会被复用的基础模块

### 11.2 入口失真

风险：

- CLI 看似存在，但不具备真实任务文件读取与验证能力

控制：

- 必须以真实 JSON 任务文件驱动 `validate` 和 `show`

### 11.3 留痕链路缺失

风险：

- 后续 Phase 1 再补 trace，导致接口回改

控制：

- Phase 0 即打通最小 trace 写入链路

## 12. 实施顺序

建议按以下顺序进入实现：

1. 建立 `pyproject.toml`
2. 创建包结构与 `__init__.py`
3. 实现 settings 与 path helpers
4. 实现 schema
5. 实现 trace recorder
6. 实现 CLI
7. 实现 FastAPI health endpoint
8. 添加 demo task
9. 补齐测试
10. 更新 README 最小用法

## 13. 结果定义

Phase 0 完成后，MendCode 应从“只有文档和依赖列表”演进为“具备统一工程配置、最小任务入口、最小 API 入口、最小 trace 能力和基础测试体系的 Python 应用骨架”。这意味着项目正式具备进入 Phase 1 的条件。
