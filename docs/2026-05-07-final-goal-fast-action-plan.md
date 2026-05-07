# MendCode 总目标快速开发方案

本文档把 MendCode 的最终目标拆成可快速执行的开发路线。判断基于当前 `develop` 进度：工具注册、权限模式、TUI 自然语言主链路、conversation/trace、Layered Memory 第一版、analysis report ingestion、review queue 和 benchmark 骨架已经落地；主要差距集中在上下文硬预算、自进化生效闭环、TUI 审查体验和指标证明。

## 1. 总体目标

目标：面向本地代码仓构建可进化 Code Agent，重点解决长链路任务中的工具调用失控、上下文膨胀、经验难沉淀。

当前进展：

- TUI-first 方向已经确定，用户自然语言请求会进入 schema tool-call AgentLoop。
- ToolRegistry / ToolPool / PermissionPolicy 已经形成主链路。
- JSONL Trace、conversation log、benchmark manifest、analysis report 和 review queue 已有基础。
- EvolutionRuntime 已能把失败、重复读取、权限拒绝、benchmark analysis 转成候选。

核心差距：

- 工具调用已经可控，但写入 preview、权限恢复、provider request/response 证据还不够完整。
- 上下文已经会 compact，但还不是 tokenizer-aware，也没有稳定 repo map。
- 经验已经能生成候选，但候选接受后对 runtime 的真实影响和 benchmark proof 还没有闭环。

最快路线：

```text
自进化候选生效闭环
-> Context Budget V2
-> TUI Review / Trace / Provider Doctor
-> Benchmark Proof 固化指标
```

优先级理由：工具数量已经超过目标，继续堆工具的收益低；最应该补的是“失败如何变成可审查改进，并证明下一轮更好”。

## 2. 技术栈落地方案

目标技术栈：Agent Harness、Textual TUI、Tool Calling、Layered Memory、Context Management。

### 2.1 Agent Harness

当前进展：

- `app/runtime/agent_loop.py` 已经是 provider-native tool-call 主路径。
- `RuntimeTurnInput`、`RuntimeTurnResult`、step budget、final response gate 和 trace recorder 已落地。
- 仍有少量 legacy helper 和 scripted action path 服务兼容测试。

快速开发项：

1. 把 provider request / response 安全摘要写入 trace。
2. 将 runtime 依赖的 legacy helper 迁入 `app/runtime/*`。
3. 给 deterministic mock provider 增加权限确认恢复、tool retry、重复 tool-call、写工具失败场景。

验收：

- TUI 自然语言主路径不经过规则旁路获取本地事实。
- trace 能看到模型请求了哪些 tool schema、返回了哪些 tool call、哪些被权限拦截。
- 非 e2e pytest 覆盖 provider roundtrip、final response gate 和 permission resume。

### 2.2 Textual TUI

当前进展：

- 聊天主视图、状态栏、slash commands、pending confirmation、conversation log、补全候选已有基础。
- 工具结果已做 compact 展示，trace path 不再直接刷屏。

快速开发项：

1. 增加 Review 面板或聊天内 review flow，统一展示 memory / rule / prompt_rule / tool_schema_hint / skill candidates。
2. 增加 trace viewer：聊天流只显示摘要，用户输入“查看详情/展开工具结果”时读取 trace。
3. 增加 provider doctor：检查 env、base URL、model、tool-call roundtrip。

验收：

- 用户能用自然语言完成“有哪些失败可以沉淀？查看第一个。接受这个。拒绝那个。”。
- 长工具结果默认折叠，聊天流不显示原始 JSON。
- provider 环境缺失时，TUI 给出明确诊断，而不是让 PTY 测试呈现模糊失败。

### 2.3 Tool Calling

当前进展：

- 当前 ToolRegistry 已超过 20 个工具，覆盖文件、搜索、Patch、Shell、Git、验证、进程、LSP、memory、trace、evolution。
- Provider-visible tools 由 ToolPool 裁剪。

快速开发项：

1. 增加 schema snapshot 测试，防止工具描述变化破坏模型调用。
2. 为写工具统一增加 diff preview 摘要。
3. 补齐只读元信息工具：`stat`、受限 `tree`。

验收：

- 工具 schema 变更必须经过 snapshot review。
- 写入类工具在确认前提供 path、risk、diff/stat 摘要。
- `read-only` 模式下只能读取、搜索、查看状态，不能写 memory、patch 或启动危险进程。

### 2.4 Layered Memory

当前进展：

- `MemoryStore`、`MemoryRuntime`、file summary、review queue、memory recall 已落地。
- 记忆类型覆盖 project_fact、task_state、file_summary、failure_lesson、trace_insight。

快速开发项：

1. 明确短期记忆：当前任务目标、最近工具 observation、pending confirmation、验证状态。
2. 明确中期记忆：文件摘要、测试反馈、常用命令、repo map。
3. 明确长期记忆：项目事实、用户确认规则、失败经验、accepted skill/rule。
4. `memory_write` 改为候选写入，接受后才进入长期 memory。

验收：

- 长期记忆必须有 source trace/report 和 review 状态。
- 记忆召回有数量、字符数、命中分数和是否截断指标。
- 重复 memory 不会污染长期库。

### 2.5 Context Management

当前进展：

- ContextManager 已注入 memory recall、evolution rules、compact observations 和 metrics。
- 当前预算主要按字符控制，benchmark 中已有 token-ish / context-ish 指标。

快速开发项：

1. 增加 tokenizer-aware adapter，优先用真实 tokenizer，缺失时 fallback 到 char/token 估算。
2. 设置分层预算：base context、memory、evolution rules、observations、file summaries。
3. 增加 repo map，优先提供目录/入口/测试命令摘要，减少重复 `list_dir/read_file`。
4. 对重复读取同一文件增加 reuse hint，优先使用已有 observation 或 file summary。

验收：

- benchmark report 能稳定输出 baseline / actual context tokens。
- repeated_file_reads 指标下降。
- 大文件问题不会把全文塞进 provider context、TUI 或 conversation log。

## 3. 工作内容逐条方案

### 3.1 工具系统

目标：设计本地工具注册与权限机制，支持代码搜索、文件读写、Patch、Shell、Git 等工具，并通过参数校验、目录限制和规则限制控制高风险操作。

当前进展：

- 工具数量已经达标。
- ToolRegistry、ToolPool、PermissionPolicy、ShellPolicy 已经是可用主链路。
- 高风险操作已经能 pending confirmation 或 reject。

差距：

- 写操作 preview 不够统一。
- 部分 legacy helper 仍未完全收敛。
- provider-visible schema 缺少 snapshot 防回归。

快速开发方案：

1. 工具 schema 稳定性
   - 新增 `tests/unit/test_tool_schema_snapshots.py`。
   - 固定核心工具字段：name、description、required args、risk level。
   - 每次 schema 变更必须显式更新 snapshot。

2. 写工具 preview
   - 为 `apply_patch/write_file/edit_file` observation 增加 `preview` 字段。
   - preview 只包含路径、行数变化、diff stat、风险说明。
   - TUI pending confirmation 展示 preview，不展示完整 patch。

3. 安全只读补齐
   - 增加 `stat` 工具，返回 size、mtime、file type、line count。
   - 增加受限 `tree` 工具，默认 max_depth=2、排除 `.git/.worktrees/data`。
   - 所有路径必须 repo-relative 并通过边界校验。

最快验收：

- `pytest tests/unit/test_tool_registry.py tests/unit/test_permission_policy.py -q`
- 新增 scenario 覆盖：危险写入需要确认、path escape 被拒绝、`tree` 不遍历 data。

### 3.2 多层记忆系统

目标：短期维护当前任务状态和最近工具结果，中期保存文件摘要和测试反馈，长期沉淀项目结构和历史修复经验，按需取用。

当前进展：

- Memory store 和 review queue 已经可用。
- file summary 和 memory recall 已接入 AgentLoop。
- Context metrics 已能记录 memory recall 和 repeated read。

差距：

- 短/中/长期边界还停留在实现隐含规则。
- repo map 还没稳定形成。
- 记忆写入仍缺敏感信息过滤、合并和 review-first 约束。

快速开发方案：

1. Memory lifecycle model
   - 新增 `MemoryLayer = short | medium | long`。
   - 为每类 memory 定义默认 TTL、是否可持久化、是否需要 review。
   - `memory_search` 支持按 layer/kind 查询。

2. Repo map V1
   - 新增 `repo_map_refresh` 和 `repo_map_read`。
   - 保存目录结构、入口文件、测试命令、核心模块摘要。
   - 默认进入中期记忆，带 sha/mtime 校验。

3. Review-first memory write
   - `memory_write` 默认写 review candidate。
   - accept 后才写长期 memory。
   - 增加近似去重和敏感字段过滤。

最快验收：

- 用户问“这个项目怎么跑测试？”时优先使用 repo map / memory，而不是重复扫全仓。
- repeated_file_reads 下降。
- 长期 memory 都能追溯到 candidate、trace 或 analysis report。

### 3.3 自进化机制

目标：记录 JSONL Trace，复盘工具调用、代码修改和测试结果，将 Debug/Test-Fix/Review 流程沉淀为 SKILL，并优化 memory、prompt rule、tool schema、context compaction。

当前进展：

- JSONL Trace 和 offline analysis 已有基础。
- analysis report 已能生成 memory / rule / prompt_rule / tool_schema_hint / skill 候选。
- review queue 和 evolution rule accept/reject 已可用。

差距：

- prompt_rule、tool_schema_hint、skill 接受后还没有专用 store 和 runtime recall。
- SKILL.md-compatible system 尚未落地。
- 接受候选后没有 benchmark proof。

快速开发方案：

1. Candidate stores
   - `data/evolution/prompt_rules.jsonl`
   - `data/evolution/tool_schema_hints.jsonl`
   - `data/skills/<skill-name>/SKILL.md`
   - 都记录 candidate_id、source_report、source_trace、accepted_at、status。

2. Runtime recall
   - prompt rules 按用户问题相关性注入 provider context。
   - tool schema hints 用于增强 `tool_search` 或 ToolPool 提示，不直接改 schema。
   - skill 按任务类型召回：debug、test-fix、review、repo-map。

3. SKILL.md V1
   - 固定四个 skill：Debug、Test-Fix、Review、Repo-Map。
   - 每个 skill 包含适用场景、推荐工具、验证要求、输出约束。
   - skill candidate accept 后写入本地 `data/skills`，不提交仓库。

4. Benchmark proof
   - 新增 `evolution_candidate_prove` 工具或 CLI。
   - 对 candidate 来源 case 跑 targeted benchmark。
   - 生成 before/after proof，写入 `data/evolution/proofs/`。

最快验收：

- 用户说“把最近 benchmark 失败沉淀一下”，模型能列出候选、请求确认、接受后写入对应 store。
- 下一轮相似问题能召回 accepted rule/skill。
- proof 记录工具链路通过率、危险命令拦截、输出长度、context token 变化。

## 4. 成果指标落地方案

目标成果：20 多种本地工具、3 档权限、多组本地代码任务测试集，工具链路通过率 95%，高风险命令拦截率 97%，Token 消耗降低 27%。

当前进展：

- 工具数量和 3 档权限已经基本达标。
- benchmark manifest 和 report model 已经存在。
- 指标还没有成为每轮开发必跑的稳定 gate。

快速开发方案：

1. 固定 benchmark gate
   - 一条命令生成 `data/benchmark-reports/latest.json` 和 `latest.md`。
   - 缺 provider env 时，明确标记 provider-gated cases，不混入代码失败。

2. 指标阈值分阶段
   - 阶段 1：工具链路通过率 >= 85%，危险命令拦截率 >= 95%，token-ish 降低可观测。
   - 阶段 2：工具链路通过率 >= 90%，危险命令拦截率 >= 97%，重复读文件下降 35%。
   - 阶段 3：工具链路通过率 >= 95%，危险命令拦截率 >= 97%，真实/估算 token 降低 27%。

3. 报告进入自进化
   - benchmark failure 自动写 analysis report。
   - analysis report ingestion 自动生成候选。
   - accepted candidate 必须有 proof。

最快验收：

- 每次开发后至少运行：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt \
  python -m app.runtime.tui_scenario_audit \
  --benchmark-manifest tests/scenarios/benchmark_manifest.json \
  --benchmark-output data/benchmark-reports/latest.json \
  --analysis-report-dir data/analysis-reports
```

## 5. 最快开发顺序

### 第一轮：自进化候选生效

目标：让 prompt_rule、tool_schema_hint、skill 不只停留在 review queue。

开发项：

- 新增 prompt rule store。
- 新增 tool schema hint store。
- 新增 skill store / loader。
- review_queue_accept 根据 target_kind 分发到对应 store。
- AgentLoop context recall accepted prompt rules / skills。

验收：

- 接受一个 skill candidate 后，相似任务 provider context 能看到该 skill 摘要。
- pending/rejected candidate 不影响 runtime。

### 第二轮：TUI Review Loop

目标：让用户自然语言完成候选审查。

开发项：

- 优化 `analysis_report_list`、`review_queue_list`、`review_queue_view` 的摘要格式。
- TUI 增加 review detail 展示。
- pending confirmation 明确显示 target_kind、source、risk、effect。

验收：

- 用户可以说“查看第一个候选”“接受这个 skill”“拒绝这个规则”。
- 聊天流不输出完整 JSON 或 trace payload。

### 第三轮：Context Budget V2

目标：把 token 降低从 token-ish 变成稳定指标。

开发项：

- tokenizer adapter。
- repo map。
- 分层 context budget。
- repeated read reuse hint。

验收：

- benchmark latest.md 展示 token/context 降低。
- 大文件与文件末句场景仍简洁正确。

### 第四轮：Benchmark Proof

目标：把自进化收益跑成证据。

开发项：

- accepted candidate -> targeted benchmark rerun。
- proof JSONL/Markdown。
- analysis report -> candidate -> proof 的追踪链。

验收：

- 每个 accepted candidate 都能看到是否带来收益。
- 没收益的候选可禁用或回滚。

## 6. 开发约束

- 后续开发从 `develop` 创建 feature worktree，不直接在 `main` 开发。
- 本地事实必须来自工具 observation。
- Provider-visible 工具必须来自 ToolRegistry / ToolPool。
- 工具执行必须经过 PermissionPolicy 和路径边界检查。
- 写入、Patch、Shell、Git mutate、memory/evolution/skill 写入必须确认或被策略拒绝。
- 长期 memory、rule、skill 必须可审查、可追踪、可回滚。
- `data/` 下运行产物不得提交。
- 每个用户暴露的问题都应补 scenario、PTY 或 benchmark case。
