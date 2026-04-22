# MendCode 开发方案

## 1. 文档目的

本文档基于 [`rawplan.md`](/home/wxh/MendCode/rawplan.md) 进行收敛和工程化重构，目标是把“面向企业本地代码仓的维护型 Agent”从概念草案整理为一份可以直接执行的开发方案。文档同时结合当前仓库现状进行约束：仓库已经完成 Phase 0 的基础工程骨架，因此当前方案的重点不再是“如何从零开始”，而是“如何在不扩散范围的前提下持续打通 Phase 1 最小闭环”。

本文档关注四件事：

- 明确首版要解决什么问题，不解决什么问题
- 给出可实现的系统架构和模块拆分
- 规划分阶段开发路径、验收标准和评测方式
- 为后续编码提供统一的技术边界和交付节奏

---

## 2. 现状判断

### 2.1 当前仓库状态

- Phase 0 已完成并合并回 `main`
- 当前已实现的代码骨架包括：
  - `pyproject.toml`
  - `app/cli/main.py`
  - `app/api/server.py`
  - `app/config/settings.py`
  - `app/core/paths.py`
  - `app/schemas/task.py`
  - `app/schemas/trace.py`
  - `app/tracing/recorder.py`
  - 对应的单元测试与集成测试
- Python 技术栈已明确：FastAPI、Typer、Pydantic、GitPython、tree-sitter、OpenAI SDK、pytest、ruff
- 当前最关键的工作已经从“收敛方向”切换为“推进 Phase 1A 的最小运行骨架”

### 2.2 当前实现进展

截至当前，项目已经完成以下工作：

- 完成 Python 包结构初始化与 `pyproject.toml` 主配置接管
- 建立 `app.__version__` 作为包版本单一来源
- 将 `pytest`、`pytest-asyncio`、`ruff` 收敛为开发依赖，而非运行时依赖
- 建立无副作用的 `settings` / `paths` 基础模块
- 建立严格的 `TaskSpec` schema
  - 拒绝未知字段
  - 覆盖显式字段、默认字段、非法枚举、fixture 直读等测试
- 建立严格的 `TraceEvent` schema 与 JSONL recorder
  - 拒绝未知字段
  - 校验 `run_id`，避免危险文件名
  - 覆盖序列化与 JSON round-trip 测试
- 建立 CLI 主入口
  - `version`
  - `health`
  - `task validate`
  - `task show`
- 建立 FastAPI 最小 `/healthz` 健康检查接口
- 更新 README，补齐 Phase 0 安装和运行说明
- 所有以上能力都已通过对应单元测试与代码审查流程

当前阶段的重点已经切换为：

- 更新根方案文档，使其与仓库真实状态对齐
- 在已完成 Phase 1A 的基础上，继续推进 Phase 1B 的真实执行链
- Phase 1B 第一刀 `run_verification` 已基本打通：schema、runner、CLI 摘要与 trace 都已连通
- 当前收尾重点变成整体验证、文档同步，以及为下一步 command policy / workspace 隔离做边界收敛

### 2.3 当前大局判断

截至 2026-04-22，项目已经跨过“基础骨架是否能跑”的阶段，进入“如何最短路径做出最小修复 Agent”的阶段。

当前真正已经打通的能力是：

- 任务 schema、run state、trace 和 verification 结果结构
- `task run`、受控 verification、workspace / worktree 隔离
- 工具层的最小 `read_file` / `search_code` / `apply_patch`
- 基于结构化 `entry_artifacts` 的固定流工具闭环：
  - `search_code -> read_file -> apply_patch -> verify`
  - tool-level trace：`run.tool.started` / `run.tool.completed`
  - runner 已能沉淀 `selected_files`、`applied_patch`、`tool_results`

当前真正还没有闭环的能力是：

- 当前 loop 仍是固定流，不具备 planner / model 驱动的动态决策
- demo 任务、CLI 展示和 README 还没有全部切到新的 fixed-flow 闭环
- eval 还没有把策略演进变成可比较结果

因此，接下来的大方向不应该是先做更重的上下文平台，也不应该继续扩工具细节，而应该优先把“工具层接入最小 loop”打通，再根据真实 demo 暴露的问题补上下文工程。

### 2.4 对初稿的评价

`rawplan.md` 的方向基本正确，尤其是以下判断值得保留：

- 首版聚焦本地代码仓维护任务，而不是做通用聊天助手
- 优先采用单主循环，而不是一开始引入复杂多 Agent
- 强调 repo map、日志蒸馏、trace、eval、workspace 隔离
- 强调工具要少而准、接口稳定、具备安全闸门

但初稿仍有三个明显问题：

1. 产品定义较强，工程拆解不足  
   方案讲清楚了“为什么这样做”，但没有把首版拆成可直接开工的模块与迭代顺序。

2. 范围有收敛倾向，但还不够硬  
   例如 PR review、依赖升级、MCP 接入、Web 面板、Docker 隔离都被提到，但对于首版来说，容易稀释主线。

3. 缺少以“当前仓库为空”为前提的启动方案  
   现在最关键的是先搭出一个能跑通的 Agent 骨架，而不是同时设计完整平台。

这个问题在当前阶段已经被部分解决：仓库不再是“只有想法和依赖文件”，而是已经具备可演进的 Phase 0 骨架。后续文档重点也因此从“如何开工”转向“如何把已开工部分稳定推进到 Phase 1”。

---

## 3. 项目定义

### 3.1 项目一句话定义

MendCode 是一个面向企业本地代码仓的维护型 Agent，接收结构化维护任务，在受控工作区内完成问题定位、上下文选择、补丁生成或风险审查、命令验证与结果沉淀。

### 3.2 首版目标

首版只追求一个最小可验证闭环：

`任务输入 -> 问题定位 -> 选择上下文 -> 生成最小修改 -> 执行验证 -> 输出摘要与 trace`

这个闭环跑通后，项目才具备继续扩展的价值。首版不以“自动修复所有问题”为目标，而以“可重复、可观察、可评测”作为第一优先级。

### 3.3 目标用户

- 在本地或内网代码仓中处理 CI / 测试问题的工程师
- 需要审查小型 PR 风险的研发团队
- 想为内部仓库建立维护自动化能力的 Infra / DevEx 团队

### 3.4 首版任务范围

首版建议只正式支持两类任务，另外保留一类只读模式：

- `ci_fix`：根据失败日志和验证命令修复问题
- `test_regression_fix`：根据失败测试回归进行最小补丁修复
- `pr_review`：只读输出风险审查报告，不自动改代码

### 3.5 暂不纳入首版

- 浏览器自动化
- 多仓联动
- 自动 merge / 自动发版
- 真正的多 Agent 调度
- 向量数据库与复杂 RAG
- SaaS 化权限系统
- 自动联网检索和依赖安装决策
- 复杂依赖升级修复

结论很明确：首版必须是“本地仓、单仓、受控工具、强验证”的工程产品，而不是泛化智能体平台。

---

## 4. 首版核心原则

### 4.1 单主循环优先

首版采用单 Agent 主循环，不引入多 Agent 编排。主循环负责：

- 维护运行状态
- 基于当前状态决定下一步动作
- 调用工具
- 处理工具结果
- 判断任务完成、失败或需要人工中止

### 4.2 工具驱动，不靠纯提示词

Agent 的能力必须建立在稳定工具之上，而不是建立在“模型可能会自己想对”的假设上。首版优先把工具接口打磨清楚，再做 prompt 细化。

### 4.3 默认最小修改

对于修复类任务，默认策略是：

- 优先最小补丁
- 优先修复当前验证失败
- 不主动做重构
- 不顺手修改无关文件

### 4.4 验证先于总结

只要任务涉及代码变更，必须先执行验证命令，再输出最终结论。没有验证结果，就不能宣称修复完成。

### 4.5 全程留痕

首版从 Day 1 开始保留 trace。因为没有 trace，就无法复盘失败、比较策略、做稳定评测。

---

## 5. 系统边界与总体架构

### 5.1 系统边界

MendCode 首版运行在本地开发机或内网服务器上，处理单个本地 Git 仓库。它不直接托管源代码平台，而是通过本地目录、Git worktree、shell 命令和模型接口完成维护闭环。

### 5.2 总体架构

建议采用六层结构：

1. Interface Layer  
   提供 CLI 入口，后续可扩展轻量 Web trace 查看器

2. Orchestrator Layer  
   维护单主循环、状态推进、策略控制、停止条件

3. Context Layer  
   负责日志蒸馏、代码检索、repo map、记忆加载、上下文裁剪

4. Tool Layer  
   提供文件读写、代码搜索、补丁应用、命令执行、验证、差异输出等工具

5. Workspace Layer  
   负责本地仓与 worktree 隔离、运行目录准备、安全策略

6. Trace & Eval Layer  
   记录全过程 trace，支持离线回放和批量评测

### 5.3 首版关键选择

- 首版入口优先 CLI，不做复杂前端
- 首版工作区优先 Git worktree，不优先 Docker
- 首版模型交互优先单模型 + 明确工具调用
- 首版上下文优先 repo map + 检索 + 规则记忆，不引入向量库
- 实际工程环境按 Python 3.11 对齐
- 工程配置优先保持单一事实来源与开发/运行依赖分离

---

## 6. 任务模型与运行主链

### 6.1 任务输入模型

建议定义统一的 `TaskSpec`：

```python
class TaskSpec(BaseModel):
    task_id: str
    task_type: Literal["ci_fix", "test_regression_fix", "pr_review"]
    title: str
    repo_path: str
    base_ref: str | None = None
    entry_artifacts: dict[str, Any]
    verification_commands: list[str]
    constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

`entry_artifacts` 根据任务类型承载原始输入，例如：

- CI 日志
- 测试失败输出
- PR diff
- issue 文本

### 6.2 运行状态模型

建议定义 `RunState`：

```python
class RunState(BaseModel):
    run_id: str
    task: TaskSpec
    status: Literal["pending", "running", "blocked", "failed", "completed"]
    step: Literal["triage", "locate", "patch_or_review", "verify", "summarize"]
    selected_files: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    planned_actions: list[str] = Field(default_factory=list)
    patch_summary: str | None = None
    verification: dict[str, Any] | None = None
    output_artifacts: dict[str, str] = Field(default_factory=dict)
```

### 6.3 首版主链

主链固定为五步：

1. `triage`  
   对日志、失败测试、PR diff 进行裁剪和归纳，提取第一层错误和候选根因

2. `locate`  
   基于错误关键词、测试名、路径、repo map 和代码搜索定位候选文件

3. `patch_or_review`  
   修复类任务生成最小补丁，只读类任务生成结构化风险报告

4. `verify`  
   执行验证命令，收集退出码、stdout、stderr、耗时和结果摘要

5. `summarize`  
   输出根因、修改摘要、验证结果、剩余风险和 trace 路径

这条主链要写死在首版设计中，不允许一开始就演化成开放式规划器。

---

## 7. 模块拆分与职责

结合当前 `requirements.txt`，建议采用 Python 单体应用结构：

```text
MendCode/
├─ app/
│  ├─ cli/
│  ├─ api/
│  ├─ orchestrator/
│  ├─ context/
│  ├─ tools/
│  ├─ workspace/
│  ├─ tracing/
│  ├─ eval/
│  ├─ models/
│  └─ schemas/
├─ data/
│  ├─ tasks/
│  ├─ traces/
│  ├─ evals/
│  └─ memories/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ e2e/
├─ scripts/
└─ README.md
```

### 7.1 `app/schemas`

职责：

- 放 `TaskSpec`、`RunState`、`TraceEvent`、`ToolResult` 等 Pydantic 模型
- 统一整个项目的数据边界
- 对任务与 trace 基础结构优先采用严格 schema，避免静默吞字段

### 7.2 `app/orchestrator`

职责：

- 实现主循环
- 管理状态转换
- 决定调用哪个工具
- 控制停止条件、重试次数、失败出口

核心文件建议：

- `runner.py`：执行完整 run
- `state_machine.py`：定义步骤推进逻辑
- `policies.py`：安全策略、工具准入策略、重试策略
- `prompts.py`：主循环所需 prompt 模板

### 7.3 `app/context`

职责：

- 日志蒸馏
- repo map 生成与缓存
- 文件选择
- 记忆加载

核心文件建议：

- `log_distill.py`
- `repo_map.py`
- `selector.py`
- `memory.py`

### 7.4 `app/tools`

首版工具严格限制为以下 8 个：

- `read_file`
- `search_code`
- `get_repo_map`
- `apply_patch`
- `run_command`
- `run_verification`
- `show_diff`
- `write_report`

说明：

- `run_verification` 是 `run_command` 的受限包装，只接受预声明验证命令
- `write_report` 负责统一写出修复摘要或审查报告
- 首版不拆太多工具，避免接口膨胀

### 7.5 `app/workspace`

职责：

- 创建和清理 worktree
- 维护运行目录
- 约束修改范围
- 提供 Git 差异和回滚辅助

核心文件建议：

- `manager.py`
- `worktree.py`
- `git_ops.py`

### 7.6 `app/tracing`

职责：

- 记录状态变化
- 记录模型调用摘要
- 记录工具调用与结果
- 导出 JSON trace

当前已落地：

- `app/schemas/trace.py`
- `app/tracing/recorder.py`
- JSONL 追加写入
- 安全 `run_id` 校验

核心文件建议：

- `schema.py`
- `recorder.py`
- `exporter.py`

### 7.7 `app/eval`

职责：

- 定义任务集格式
- 批量运行任务
- 根据结果计算指标
- 输出结果报表

核心文件建议：

- `dataset.py`
- `runner.py`
- `scorers.py`

### 7.8 `app/cli` 与 `app/api`

职责：

- CLI 是首版主入口
- API 仅保留轻量封装，供后续 Web 面板或内部服务调用

首版建议先完成 CLI，再补 API。

当前状态：

- CLI 已落地，当前已支持：
  - `mendcode version`
  - `mendcode health`
  - `mendcode task validate`
  - `mendcode task show`
- API 已落地，当前已提供最小 `/healthz`
- 下一步应补 `task run` 与最小 runner，建立真正的运行态骨架

---

## 8. 首版工具设计

### 8.1 工具设计原则

- 输入输出必须结构化
- 工具职责必须单一
- 错误必须标准化返回
- 每个工具都要能被 trace 记录
- 高风险动作必须通过策略层拦截

### 8.2 工具返回结构建议

```python
class ToolResult(BaseModel):
    ok: bool
    tool_name: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
```

### 8.3 高风险动作

以下动作首版默认禁止或需要显式开关：

- 删除文件
- 修改 `.github/workflows/`
- 批量替换超过阈值
- 执行非白名单 shell
- 网络访问

这部分不要交给模型临场判断，必须写进 `policies.py`。

---

## 9. 上下文工程设计

上下文工程是首版成败关键，但必须克制实现。

### 9.1 四层上下文

L0 原始证据：

- CI 日志
- 测试失败输出
- PR diff
- issue 文本

L1 局部代码：

- 候选文件片段
- 相邻函数或类定义

L2 仓库结构：

- repo map
- 目录结构摘要
- 符号索引

L3 长期记忆：

- 常用验证命令
- 构建规则
- 团队约定
- 已知故障模式

### 9.2 首版具体实现

- 使用 `tree-sitter` 生成基础 repo map
- 使用 `rg` 做关键词和路径检索
- 使用规则裁剪日志，只保留错误核心段和相关上下文
- 使用简单 Markdown / JSON 文件承载长期记忆

当前阶段尚未开始上下文工程主体实现。现阶段已优先完成任务 schema、trace schema、settings、基础路径和测试基建，这是合理的，因为这些是后续上下文层与入口层的依赖前置项。

### 9.3 首版明确不做

- 向量数据库
- 长短期记忆自动学习
- 跨仓库知识融合
- 自动生成复杂调用图

---

## 10. Workspace 与安全策略

### 10.1 工作区模式

首版只实现一种正式模式：

- `git worktree` 隔离执行

原因：

- 足够满足本地仓维护需求
- 调试体验好
- 比 Docker 成本低
- 后续容易升级到容器模式

### 10.2 首版运行约束

- 每个任务创建独立 worktree
- 所有代码修改都发生在 worktree 中
- 验证命令在 worktree 中执行
- 任务结束后保留 worktree 或根据参数清理

### 10.3 安全策略

- 只允许白名单工具
- 只允许白名单验证命令
- 默认禁止联网
- 默认禁止越过仓库根目录读写
- 默认禁止修改隐藏目录与 CI 配置

---

## 11. Trace 与评测体系

### 11.1 Trace 记录要求

每一步至少记录：

- `run_id`
- 当前阶段
- 模型输入摘要
- 模型输出摘要
- 工具名
- 工具参数摘要
- 工具结果摘要
- 时间戳
- token / cost

首版优先记录摘要而不是完整原文，避免 trace 体积快速膨胀。

### 11.2 首版评测任务集

建议首版构建 12 到 20 条自建任务：

- 6 到 8 条 `ci_fix`
- 4 到 6 条 `test_regression_fix`
- 2 到 4 条 `pr_review`

所有任务都应具备：

- 固定输入
- 固定仓库版本
- 固定验证命令
- 可比对的预期结果

### 11.3 首版核心指标

- `verification_pass_rate`
- `first_pass_fix_rate`
- `localization_accuracy`
- `avg_steps_per_task`
- `tool_success_rate`
- `dangerous_action_block_rate`

### 11.4 指标达标建议

在内部演示版上，建议把以下阈值作为首轮目标：

- `tool_success_rate >= 95%`
- `dangerous_action_block_rate = 100%`
- `verification_pass_rate >= 60%`
- `pr_review` 报告具备可读证据链

这里不追求一次就把修复率做得很高，先保证系统稳定和可复盘。

---

## 12. 分阶段开发计划

### Phase 0：项目骨架与工程基建

目标：把仓库从“只有依赖列表”推进到“可启动、可测试、可扩展”的基础骨架。

交付：

- 创建 `app/`、`tests/`、`data/`、`scripts/` 目录
- 配置 `pyproject.toml` 或保留 `requirements.txt` 并补测试与 lint 入口
- 建立 Pydantic schema、日志组件、配置加载、CLI 主入口
- 建立基础测试框架

验收：

- `pytest` 可运行
- `ruff check` 可运行
- `python -m app.cli.main --help` 可运行

当前进度：

- Phase 0 已完成并合并回 `main`
- 已具备 schema、settings、paths、trace recorder、CLI、API 与测试基线
- Phase 1A 已完成：`RunState`、最小 runner、`task run`、开始/结束 trace 已落地
- Phase 1B 第一切片已完成主要实现：
  - 新增 verification schema 与结果汇总结构
  - `RunState` 已可携带 verification 摘要
  - runner 已顺序执行 `verification_commands`
  - trace 已覆盖 `run.verification.started` 与 `run.verification.command.completed`
  - CLI `task run` 已展示 `passed_count` / `failed_count`，失败时可打印首条失败命令
- Phase 1B 下一阶段方向已确认：
  - 先收口 command policy
  - 再接 worktree manager
  - runner 逐步退回到编排职责，不继续堆策略与工作区副作用
- 开始下一阶段开发前，已先完成当前 worktree 的基线清理：
  - 修复 CLI 汇总输出与 integration test 契约不一致的问题
  - 将环境敏感的 `pytest -q` 测试命令收敛为可控命令
  - 清理 `tests/unit/test_runner.py` 的既有 lint 问题
  - 当前基线重新恢复为 `pytest -q` / `ruff check .` 全绿

### Phase 1：打通最小修复闭环

目标：只支持 `ci_fix` / `test_regression_fix` 两类任务，跑通完整主链。

当前推荐拆分为两个层次：

- Phase 1A：最小运行骨架
  - `RunState`
  - 最小 runner
  - `task run`
  - `run.started` / `run.completed` trace
- Phase 1B：真实执行链
  - `run_verification`
  - workspace / worktree
  - 基础工具
  - 更完整的 orchestrator 状态推进

交付：

- `TaskSpec` / `RunState`
- 单主循环 runner
- 4 个核心工具：`read_file`、`search_code`、`apply_patch`、`run_verification`
- worktree 管理
- JSON trace 记录
- 2 条 demo 任务

验收：

- 能载入任务文件并执行
- 能在 worktree 中读写代码
- 能执行验证命令
- 能输出修复摘要和 trace 文件

进入 Phase 1 的前置条件已经更清晰：

- Phase 0 前置条件已经满足
- Phase 1A 已完成，说明系统已经具备最小运行态骨架
- Phase 1B 第一切片的 `run_verification` 已落地，说明系统已经具备真实验证执行能力
- 下一步应优先收敛 command policy、workspace / worktree 与基础工具，而不是继续堆叠 CLI 表面能力
- 在 workspace / worktree 未落地前，不应过早进入自动补丁修改链路
- 当前推荐实现顺序已经固定：
  1. `app/workspace/command_policy.py`
  2. `app/workspace/executor.py`
  3. `app/workspace/worktree.py`
  4. runner 接线与 trace 扩展
  5. 再进入 `read_file` / `search_code` / `apply_patch`
- 当前已完成下一阶段的第一个落地任务：
  - Task 1 已完成 schema / settings 底座扩展
  - `TaskSpec` 已支持 `base_ref`
  - `RunState` 已支持 `workspace_path`
  - `VerificationCommandResult` 已支持 `timed_out` / `rejected` / `cwd`，且状态约束已收紧
  - `Settings` / `ensure_data_directories()` 已支持 `workspace_root` 与基础执行配置
- 当前已完成下一阶段的第二个落地任务：
  - Task 2 已完成 `app/workspace/command_policy.py`
  - Task 2 已完成 `app/workspace/executor.py`
  - 命令 allowlist、`cwd` 边界、timeout、rejected、launch failure 都已具备结构化结果
  - richer verification schema 已真正接到单命令执行结果上
- 当前已完成下一阶段的第三个落地任务：
  - Task 3 已完成 `app/workspace/worktree.py`
  - worktree 准备、detached checkout、`base_ref` 和 cleanup 结果都已有稳定接口
  - cleanup 成功 / 失败路径都已有真实 git 场景测试覆盖
- 当前已完成下一阶段的第四个落地任务：
  - Task 4 已将 runner 从“直接在 repo_path 执行”切换为“先准备 workspace，再经 executor 执行”
  - `workspace_path`、cleanup 结果和 richer verification 事件已经真正写入 trace / CLI 汇总
  - `task run` 已首次跑通完整的 workspace-aware 执行链
  - workspace setup 失败与 cleanup 失败都已具备更可操作的 summary 暴露
- 当前下一优先级已切换到 Task 5：
  - 同步 README / 根方案文档 / 问题记录
  - 跑完整验证集
  - 确认当前 worktree 分支已经达到可收尾状态
- Task 5 现已完成：
  - README、开发方案、问题记录已与 command policy / worktree 实现保持同步
  - 已完成完整验证：`python -m pytest -q`、`ruff check .` 均通过
  - 当前 `phase-1b-command-policy-worktree` 已达到本地合并回 `main` 的收尾条件
- 当前收尾原则也已固定：
  - 先把 Phase 1B command policy / worktree 切片合回 `main`
  - 合并后再进入下一阶段基础工具能力，不在本分支继续堆新功能
- 合并回 `main` 后已补做一次全量排查与 hygiene 收口：
  - 新增 `tests/unit/test_repo_hygiene.py`，约束 `.gitignore` 与仓库跟踪文件状态
  - `.gitignore` 已补齐 `data/traces/`、`.pytest_cache/`、`.ruff_cache/`、`__pycache__/`、`*.py[cod]`
  - 仓库中被误纳入版本管理的 Python 字节码文件已清理
  - README 的重复 capability 描述已去重，避免合并后文案继续漂移
- 当前下一开发切片已收敛为基础工具第一刀：
  - 先做 `read_file` 与 `search_code`
  - 再补最小 `apply_patch`
  - 暂不接 orchestrator 自动调用
  - 先冻结工具层结果契约、路径边界和测试基线，再进入下一刀
- 当前这一步已经完成实现与验证：
  - `app/tools/schemas.py` 已统一 `ToolResult` 契约，明确 `passed / failed / rejected` 语义和 `workspace_path`
  - `app/tools/guard.py` 已完成 workspace 路径边界校验，拒绝越界、缺失路径和目录路径
  - `app/tools/read_only.py` 已完成 `read_file` 与 `search_code`
  - `app/tools/patch.py` 已完成最小 `apply_patch`
  - `read_file` 已支持行范围、字符截断、空文件返回和越界参数拒绝
  - `search_code` 已固定为字面量搜索，支持 `glob` 过滤、结果裁剪、0 匹配成功返回和非法参数拒绝
  - `apply_patch` 当前只支持 `workspace_path` 内单文件的精确文本替换，不做通用 unified diff 解析
  - 默认只允许单处命中替换；多处命中必须显式 `replace_all=True`
  - 当前工具层仍然保持“不接 orchestrator 自动链路”的收敛边界
- 当前切片的最新验证结果：
  - `python -m pytest tests/unit/test_tool_schemas.py tests/unit/test_tool_guard.py tests/unit/test_read_only_tools.py tests/unit/test_patch_tools.py -v` 通过
  - 当前 `apply_patch` 的核心行为已补齐单测：单次替换、空 `old_text` 拒绝、目标缺失拒绝、多处命中默认拒绝、`replace_all=True` 全量替换
- 因此下一步顺序应继续保持简单：
  - 先把 `apply_patch` 保持在当前最小面，不继续扩成通用 diff 引擎
  - 再决定是否把工具层接入 orchestrator 的最小调用闭环
  - 暂不提前扩散到 repo map、日志蒸馏或多工具编排

补充当前收敛状态：

- command policy 已落地：验证命令必须经过受控 executor，具备 timeout、rejected、timed_out 语义
- worktree manager 已落地：`task run` 默认在 `.worktrees/preview-<id>/` 中执行 verification
- runner 已从“直接执行命令”收敛为“编排 workspace、executor、trace 和 cleanup”
- 当前 worktree 内的权威验证 / 运行方式已明确：
  - 测试优先使用 `python -m pytest`
  - CLI smoke 优先使用 `python -m app.cli.main ...`
  - 嵌套 worktree 场景下，不再把外层 editable install 的 `pytest` / `mendcode` 入口当作收尾依据

### Phase 2：打通最小 Agent loop

目标：让系统从“有工具、能验证”升级成“能围绕任务完成一轮最小读搜改验”。

当前进度：

- Phase 2A 工具层已完成并通过验证：
  - `ToolResult` 契约已统一
  - `read_file` / `search_code` / `apply_patch` 已落地
  - workspace 路径边界已通过 `guard` 收口
- Phase 2B 当前已完成中段实现：
  - 已补 `docs/superpowers/specs/2026-04-22-phase-2b-fixed-loop-design.md`
  - 已补 `docs/superpowers/plans/2026-04-22-phase-2b-fixed-loop.md`
  - Task 1 和 Task 2 已合并收口：
    - `app/orchestrator/fixed_flow.py` 已支持结构化 artifacts 解析与校验
    - `RunState` 已扩展 `current_step`、`selected_files`、`applied_patch`、`tool_results`
  - Task 3 和 Task 4 已合并收口：
    - `run_task_preview()` 已能串起 `search_code` / `read_file` / `apply_patch`
    - 已记录 `run.tool.started` / `run.tool.completed`
    - 已对“搜索结果不唯一”与“inspected slice 不包含 old_text”做 fail-closed
  - 当前收口验证结果：
    - `python -m pytest tests/unit/test_run_state.py tests/unit/test_runner.py -v` 通过，`34 passed`
    - `ruff check app/orchestrator/runner.py tests/unit/test_runner.py` 通过
- Task 5 现已完成：
  - `data/tasks/demo.json` 已切换为真实 fixed-flow repair demo
  - `app/cli/main.py` 已展示 `selected_files` 与 `applied_patch`
  - `tests/integration/test_cli.py` 已改为覆盖 fixed-flow CLI 输出与 trace 顺序
  - README 已同步说明 `task run` 的 fixed-flow demo 能力
  - 已完成真实 demo 验证：`python -m app.cli.main task run data/tasks/demo.json` 本地通过
- 当前最新 focused 验证结果：
  - `python -m pytest tests/unit/test_run_state.py tests/unit/test_runner.py tests/integration/test_cli.py -v` 通过，`43 passed`
  - `ruff check app/cli/main.py tests/integration/test_cli.py` 通过
- Task 6 现已完成：
  - `python -m pytest -v` 通过，`130 passed`
  - `ruff check .` 通过
  - 真实 demo `python -m app.cli.main task run data/tasks/demo.json` 已跑通
- 当前下一优先级已经切换到本切片收尾：
  - 做一次最终 review / commit 整理
  - 准备把 `phase-2a-readonly-tools` 这条线收口
  - 不在当前切片继续横向扩 planner、上下文平台或更多工具面

交付：

- 工具调用输入 / 输出在 runner 中落地
- 工具级 trace 事件
- 更完整的 run state 步骤推进
- 固定 action budget 的最小 loop
- 至少 1 条真实 demo 任务走通 `read -> search -> patch -> verify`

验收：

- `task run` 不再只做 verification，还能在固定流程中调用工具
- trace 可以回放每一步工具调用与结果
- 至少在窄范围 demo 任务上完成一次真实修复尝试

### Phase 3：补最小上下文工程

目标：只围绕真实闭环暴露的瓶颈补上下文能力，而不是先搭一个大平台。

交付：

- 日志蒸馏器
- 最小文件选择策略
- repo map 最小版
- 必要的上下文裁剪约束

验收：

- 同一 demo 任务下无效读文件明显减少
- 平均步骤数下降或定位稳定性提升
- 不引入重型索引或过早缓存体系

### Phase 4：补评测闭环

目标：把系统从“能跑 demo”提升到“每次改动都可比较”。

交付：

- 任务集格式
- 批量评测 runner
- 指标统计
- trace 聚合导出
- Markdown / JSON 报表

验收：

- 可一键跑完整任务集
- 能输出每条任务的结果和总体指标
- 能回溯失败任务的 trace

### Phase 5：补只读审查能力与轻量服务化

目标：在不破坏主线的前提下，扩展 `pr_review` 与服务接口。

交付：

- `pr_review` 模式
- 结构化 review 报告
- FastAPI 封装
- 轻量 trace 查询接口

验收：

- 输入 PR diff 后能输出结构化风险报告
- 能通过 API 触发任务并查询执行结果

### Phase 6：企业化增强

目标：在核心功能稳定后，再扩展部署与连接能力。

交付候选：

- Docker 隔离工作区
- MCP 风格连接器
- 权限与审批策略
- 更多任务类型

这一阶段不应进入首版承诺，只作为后续路线图。

---

## 13. 里程碑与建议节奏

如果以单人或小团队推进，建议按 6 周节奏规划：

- 第 1 周：完成 Phase 0
- 第 2 到 3 周：完成 Phase 1
- 第 4 周：完成 Phase 2
- 第 5 周：完成 Phase 3 到 Phase 4 的最小子集
- 第 6 周：完成 Phase 5 的最小子集

如果资源更紧，至少也要保证：

- 第一个“真实读搜改验”演示版本必须尽快出现
- 第一个可批量评测版本必须在可演示版本之后尽快出现

否则项目很容易停留在“设计讨论”而不是“系统演进”。

---

## 14. 开发纪律与执行要求

### 14.1 模块建设顺序

建议严格按以下顺序编码：

1. schema
2. CLI 入口
3. tracing
4. orchestrator 最小运行骨架
5. workspace
6. 基础工具
7. 工具接入最小 loop
8. context
9. eval
10. API

### 14.2 每轮开发要求

- 每次只新增一个明确能力
- 先定义接口，再写实现
- 每增加一个能力，必须补最小测试
- 每完成一个阶段，必须跑验收命令

### 14.3 测试分层

- 单元测试：工具、状态机、日志裁剪、repo map
- 集成测试：worktree + 工具调用 + orchestrator
- 端到端测试：固定任务输入到最终结果

### 14.4 Prompt 管理要求

- prompt 模板必须版本化
- 不允许把业务规则散落在多个字符串常量中
- 系统规则应尽量前置到策略层和工具层，而不是只写在 prompt 中

---

## 15. 主要风险与应对

### 风险 1：范围膨胀

表现：还没跑通修复闭环，就开始做 Web 面板、MCP、Docker、多 Agent。

应对：以 `ci_fix` / `test_regression_fix` 为绝对主线，未通过 Phase 1 与 Phase 2 验收前，不开启旁支开发。

### 风险 2：模型上下文失控

表现：读入文件太多，日志太长，结果不稳定。

应对：优先做日志蒸馏、repo map、文件选择器，并对单次上下文设置硬阈值。

### 风险 3：工具接口不稳定

表现：同一工具返回格式飘忽，导致 orchestrator 和 prompt 频繁修改。

应对：先冻结 `ToolResult` 和错误码格式，再扩展工具。

### 风险 4：没有评测，优化全靠感觉

表现：不断改 prompt，但不知道系统是否真正变好。

应对：在 Phase 3 前至少准备 demo 任务和 trace，对每次策略变更保留前后对比。

### 风险 5：安全边界不清

表现：Agent 能执行危险命令或修改关键配置。

应对：白名单命令、白名单目录、worktree 隔离、高风险动作硬阻断。

---

## 16. 首版验收标准

首版完成的标准不是“功能看起来很多”，而是满足以下条件：

- 可以通过 CLI 提交 `ci_fix` 或 `test_regression_fix` 任务
- 能在独立 worktree 中完成一次完整执行
- 能成功调用核心工具并留下标准化 trace
- 能基于固定验证命令给出“通过 / 未通过”结论
- 能输出可读的修复摘要
- 能跑一组小型任务集并生成指标
- 对高风险操作具备明确拦截能力

只要这些标准没有满足，就不应宣称进入“平台化阶段”。

---

## 17. 建议的首批交付清单

建议把首批实际开发任务压缩为以下 10 项：

1. 初始化项目目录与配置文件
2. 定义核心 Pydantic schema
3. 建立 CLI 命令入口
4. 实现 trace recorder
5. 实现最小 orchestrator runner
6. 实现 `run_verification`
7. 实现 worktree manager
8. 实现 `read_file` / `search_code` / `apply_patch`
9. 准备 2 条 demo 任务
10. 补齐单元测试与一条端到端测试

这 10 项完成后，MendCode 才算从“概念方案”进入“系统原型”。

截至当前的完成情况：

- 已完成：1、2、3、4、9 的基础子集，以及对应单元测试框架
- 已完成：5，也就是最小 orchestrator runner 与 `task run`
- 已完成：6，也就是 `run_verification`
- 已完成：7，也就是 worktree manager / workspace 隔离
- 已完成：8 的当前最小工具闭环，也就是 `read_file` / `search_code` / 最小 `apply_patch`
- 当前阶段未完成的主线收口为：
  - 工具层与 orchestrator 的最小集成
  - demo 任务与端到端链路继续补强
  - 工具调用 trace 与更完整的 run state 推进
- 当前已经完成的工程收敛：
  - 采用“小而清晰的执行边界拆分”
  - 不把 command policy 和 worktree 继续堆进 runner
  - 在 `app/workspace/` 下落 `command_policy.py`、`executor.py`、`worktree.py`
  - 先完成受控执行，再切换到 worktree 执行
  - 工具层统一围绕 `workspace_path` 收口结果契约和安全边界
  - `apply_patch` 先固定为“单文件精确文本替换”而不是通用 diff 引擎
- 之后依次推进：
  - 先把最小工具调用闭环接进 runner
  - 再用真实 demo 暴露的瓶颈倒逼上下文工程
  - 最后再补评测闭环，而不是先做大而全的 context 平台

当前对 `run_verification` 的收敛策略：

- 只执行 `TaskSpec.verification_commands`
- 顺序执行，不并行
- 记录退出码、耗时、输出摘要
- 失败视为业务结果而不是 CLI 崩溃
- 当前 CLI 已显示 verification 汇总结果，并在失败时暴露首条失败命令
- command policy、timeout 语义和 worktree 隔离已落地，不再属于待设计项
- 当前下一阶段的重点已经转为“工具层最小闭环”：
  - 当前 `read_file` / `search_code` / 最小 `apply_patch` 已经落地
  - 继续保持 `ToolResult` / workspace 边界不漂移
  - 下一刀直接把 orchestrator 接到最小工具调用链
  - 上下文工程只围绕这个闭环的真实瓶颈补，不提前整包展开

---

## 18. 最终结论

这份初稿最有价值的地方，是方向选择基本正确：本地代码仓、维护场景、单主循环、上下文工程、trace 与 eval 优先，都是可落地的路线。真正需要修正的，是开发节奏和承诺边界。

MendCode 的正确起步方式，不是追求“大而全 Agent 平台”，而是先做出一个受控、可验证、可复盘的仓库维护 Agent 原型。对当前仓库来说，最现实的路径是：

- 先完成工程骨架
- 再打通修复闭环
- 然后补上下文工程和评测
- 最后再扩展审查能力与企业化接口

如果执行上保持这个顺序，项目有较高概率在较短周期内产出一个真实可演示、可继续迭代的版本。

截至当前，这个判断已经被进一步验证：项目不再只停留在 Phase 0/1 的运行骨架，workspace 隔离、受控 verification 和只读工具第一刀都已落地。接下来的关键，不是继续扩散能力面，而是按顺序补完 `apply_patch` 与最小工具调用闭环，让仓库从“能受控执行”升级为“能在受控工作区内完成最小读写闭环”。
