# MendCode 最终目标差距分析与最快开发方案

## 1. 当前判断

MendCode 当前已经具备 Code Agent Runtime 的主体骨架，整体距离目标约 **60% - 65%**。

已经比较扎实的部分是工具系统和权限系统：当前 `ToolRegistry` 已注册 32 个本地工具，覆盖代码搜索、文件读写、Patch、Shell、Git、验证、Memory、Trace、Review Queue、Process 和基础 LSP；三档权限模式、`ToolPool` 裁剪、`PermissionPolicy`、Shell 风险分类、危险操作确认和路径边界也已经落地。

主要差距不在“工具数量”，而在三件事：

- 指标还没有完全跑成固定报告：已有 benchmark manifest、coverage check 和 evidence 口径，但还缺自动聚合到 `data/benchmark-reports/` 的稳定产物。
- 记忆系统还没有成为长链路任务的默认上下文策略：已有 JSONL memory、file summary、review queue、context metrics，但短/中/长期记忆生命周期和 token-aware budget 还不够硬。
- 自进化还停留在候选生成和人工审查前半段：已有 `EvolutionRuntime`、trace lesson candidate、review queue，但还没有 SKILL.md-compatible 的流程加载、采纳和回归验证闭环。

## 2. 分模块差距

### 工具系统：约 80%

已完成：

- 32 个本地工具进入 `ToolRegistry`。
- Provider-visible schema 来自 `ToolPool`。
- 权限模式覆盖 `read-only`、`workspace-write`、`danger-full-access`。
- `run_command` 和 `run_shell_command` 已区分验证命令和普通 shell。
- `apply_patch_to_worktree` legacy 工具名已移除，Patch 统一走 `apply_patch`。
- 7 类 benchmark case 已接入同一 evidence 口径。

剩余：

- `app.runtime.agent_loop` 仍依赖 `app.agent.loop` 的 helper。
- `loop_input.actions` 兼容路径仍存在。
- CLI repair 仍有过渡兼容层。
- 写入类工具缺少统一 diff preview 和更细的确认摘要。

### 多层记忆系统：约 50%

已完成：

- JSONL memory store。
- `memory_search` / `memory_write`。
- `file_summary_read` / `file_summary_refresh`。
- `ContextManager` 自动 recall 少量相关 memory。
- prompt context 记录 observation、memory recall、read_file、重复 read_file 指标。
- review queue 支持候选 list / view / accept / reject。

剩余：

- 短期任务状态、中期文件摘要、长期经验之间的写入规则还不够明确。
- Context compaction 还是字符预算，未接入 tokenizer-aware budget。
- 大文件读取还没有强制优先走摘要或片段读取。
- 失败经验从 review queue 采纳后，还没有自动进入 Skill / prompt rule / tool schema 改进流程。

### 自进化机制：约 35%

已完成：

- JSONL trace 已记录 AgentLoop 过程。
- `trace_analyze` 可生成失败经验候选。
- `EvolutionRuntime` 可基于失败、rejected tool、重复读取和验证恢复生成 lesson candidate。
- review queue 保持人工审查和可追踪。
- Story Runner 已支持 story plan 的 next / status / mark-passed / append-progress。

剩余：

- 没有 SKILL.md-compatible loader。
- 没有 Debug / Test-Fix / Review / Repo-Map 等可复用 Skill。
- lesson candidate 不能生成 skill / memory / prompt rule 的具体变更建议。
- benchmark report 尚未反向参与“改动是否收益”的判断。

### 指标与测试：约 55%

已完成：

- `BenchmarkManifest` 固定 7 类目标任务。
- `BenchmarkCaseResult` 记录 expected / observed / missing tools、危险命令拦截、可见输出长度、context-ish 指标和 repeated reads。
- `mendcode benchmark status` / `benchmark check` 已存在。
- TUI scenario audit 可映射 BenchmarkReport JSON。
- 7 类 case 已有 scenario / integration 测试接入 evidence 口径。

剩余：

- 还不能一条命令稳定生成 `latest.json` 和 Markdown 报告。
- token 仍是 token-ish / context chars，没有 tokenizer-aware 统计。
- 95% / 97% / 27% 还只是目标，不是已验证结果。

## 3. 头脑风暴：三条推进路线

### 路线 A：评测先行

先把 benchmark report 自动生成、覆盖校验、指标报告和 CI-like 命令补齐。

优点：

- 最快把目标指标变成可度量事实。
- 每轮开发都能知道是否接近 95% / 97% / 27%。
- 能约束 TUI 体验，不再凭感觉判断“好不好用”。

缺点：

- 不会立刻增强 Agent 智能。
- 需要接受第一版指标比较粗糙。

### 路线 B：记忆优先

先做 tokenizer-aware context budget、文件摘要替代全文读取、短中长期记忆写入规则。

优点：

- 直接解决上下文膨胀和重复读文件。
- 对长链路任务收益明显。

缺点：

- 没有稳定 benchmark 前，Token 降低很难证明。
- 容易陷入策略细节。

### 路线 C：自进化优先

先做 SKILL.md loader、Debug/Test-Fix/Review/Repo-Map Skill、review queue 到 skill candidate 的沉淀。

优点：

- 最贴近“可进化 Code Agent”的叙事。
- 能形成差异化能力。

缺点：

- 如果工具闭环和 benchmark 还不硬，Skill 很容易变成 prompt 堆叠。
- 失败收益不容易验证。

## 4. 推荐路线

推荐选择 **A -> B -> C**。

也就是：

```text
先把 benchmark 和 evidence 跑成固定产物
-> 再用指标驱动 Context / Memory 压缩
-> 最后把高频流程沉淀为 SKILL 并用 benchmark 回归验证收益
```

原因很直接：当前工具数量已经够，权限基础也有，最缺的是“证明能力”和“用证明结果指导下一步”。如果先做 Memory 或 Skill，很容易继续增加复杂度，但不知道是否真的降低 Token、减少重复读文件或提升工具链路通过率。

## 5. 最快开发方案

### Phase 1：Benchmark 产物闭环

目标：让固定任务集能一条命令生成可比较的报告。

开发项：

- 新增 `mendcode benchmark run-scenarios` 或独立 runtime command。
- 运行 `tests/scenarios` 和可选 `tests/e2e`。
- 生成 `data/benchmark-reports/latest.json`。
- 同时生成 `data/benchmark-reports/latest.md`。
- 报告包含：
  - case pass rate
  - tool chain pass rate
  - dangerous command block rate
  - token/context reduction rate
  - repeated file reads
  - missing tools
  - visible output over-limit cases

验收：

- `mendcode benchmark status tests/scenarios/benchmark_manifest.json` 显示 no missing categories。
- `mendcode benchmark check tests/scenarios/benchmark_manifest.json data/benchmark-reports/latest.json` 显示 complete=true。
- `latest.md` 能直接作为阶段成果引用。

### Phase 2：Context Budget 硬化

目标：把上下文控制从“记录指标”推进到“强制预算”。

开发项：

- 增加 tokenizer-aware 或 tokenizer-like budget adapter。
- 给 provider context 设置总预算、memory 预算、observation 预算、file excerpt 预算。
- read_file 大文件默认只进入 compact observation。
- 对“最后一句 / 前几行 / 某行附近”类问题强制鼓励行范围读取。
- 当重复读取同一文件时，优先使用已有 observation 或 file summary。

验收：

- benchmark report 中 repeated_file_reads 明显下降。
- context_actual 小于 context_baseline。
- 大文件读取场景不把全文塞入 TUI 或 conversation log。

### Phase 3：Memory 生命周期规则

目标：让短/中/长期记忆有明确边界。

开发项：

- 短期记忆：当前任务目标、最近工具结果、pending confirmation、验证状态。
- 中期记忆：文件摘要、测试反馈、常用命令、当前 story progress。
- 长期记忆：项目事实、稳定经验、失败 lesson、用户确认过的约束。
- 为 `memory_write` 增加敏感内容过滤、近似去重、来源 trace 指针。
- TUI 增加 review queue 的轻量查看和 accept / reject 入口。

验收：

- Memory 写入必须有来源和 kind。
- 重复 memory 不会污染长期库。
- 记忆召回 scenario 能证明模型使用 `memory_search` 而不是编造。

### Phase 4：SKILL.md 最小闭环

目标：把高频流程沉淀为可审查 Skill。

开发项：

- 新增 repo-local skill loader。
- 支持 `skills/debug/SKILL.md`、`skills/test-fix/SKILL.md`、`skills/review/SKILL.md`、`skills/repo-map/SKILL.md`。
- Skill 只定义：
  - 适用场景
  - 推荐工具池
  - 上下文召回规则
  - 验证要求
  - 输出约束
- `EvolutionRuntime` 生成 skill candidate，不直接写入。
- review queue accept 后才写入 skill candidate 或长期 memory。

验收：

- Debug / Test-Fix / Review / Repo-Map 至少 4 个 Skill 可被加载。
- Skill 的启用记录进入 trace。
- benchmark 能对比启用 Skill 前后的工具链路和上下文指标。

### Phase 5：Runtime legacy 收口

目标：让产品主路径完全是 schema tool call runtime。

开发项：

- 把 `app.agent.loop` 中仍被 runtime 依赖的 helper 移入 runtime 内部模块。
- 将 `loop_input.actions` 限制为测试 / scripted compatibility，不进入 TUI 主路径。
- CLI repair 迁移到 provider-native tool-call flow。
- Provider request / response 摘要写入 trace，但不记录 API key。

验收：

- TUI 自然语言请求只走 OpenAI-compatible native tool calls。
- legacy JSON action 不会被 provider 主路径接受。
- Tool schema snapshot 覆盖 provider-visible 工具面。

## 6. 最快里程碑

### 1 周内

- 完成 benchmark report 自动生成。
- 将 7 类 case 的 evidence 聚合到 `latest.json`。
- 输出第一份 `latest.md`。

### 2 周内

- ContextBudget 变成强制预算。
- 大文件 / 重复读文件场景进入 benchmark。
- report 中出现 context/token-ish 降低数据。

### 3 周内

- Memory 生命周期规则落地。
- review queue 在 TUI 中可审查。
- memory accept/reject 有 trace 指针和回滚边界。

### 4 周内

- SKILL.md loader 第一版。
- 4 个核心 Skill。
- Evolution candidate 可进入 Skill / Memory 审查流程。

## 7. 当前距离目标的结论

当前 MendCode 已经具备“本地工具可控调用”的主体能力，距离目标最近的是工具系统；距离最远的是自进化闭环和可量化收益证明。

如果按推荐路线推进，最快可以这样判断成熟度：

- 当前：约 60% - 65%。
- Benchmark 产物闭环完成后：约 70%。
- Context / Memory 强制预算完成后：约 80%。
- SKILL.md + review queue + benchmark 回归闭环完成后：约 90%。

最后 10% 主要来自真实 provider / PTY 长任务稳定性、指标持续达标和大量失败案例沉淀。
