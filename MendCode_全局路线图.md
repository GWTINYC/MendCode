# MendCode 全局路线图

## 1. 文档目的

这份文档只负责一件事：

- 持续提醒当前开发应该优先服务哪条主线
- 避免因为局部实现、临时 bug 或某个子模块细节而钻牛角尖
- 让每一轮工作都朝“更接近最小可用修复 Agent”推进

如果某项工作看起来合理，但不能明显推进主线闭环，就不应抢优先级。

---

## 2. 当前全局判断

截至 2026-04-22，MendCode 已经完成了三个关键基础层：

- 运行骨架：CLI、API、schema、trace、`task run`
- 执行边界：command policy、executor、worktree manager
- 基础工具：`read_file`、`search_code`、最小 `apply_patch`

这说明项目已经不再处于“有没有框架”的阶段，而是进入了：

`如何把现有框架收口成最小修复闭环`

当前真正还缺的不是更多外围能力，而是核心链路中的三段：

- 工具还没有接入 orchestrator 的真实执行流
- demo 任务还没有跑通“读、搜、改、验”闭环
- 评测体系还不能比较不同策略版本

因此，后续路线必须继续收口到：

`先让系统能稳定完成一次最小修复尝试，再按真实瓶颈补上下文与评测`

---

## 3. 项目主线

MendCode 的主线不是“功能越来越多”，而是下面这条链越来越完整、越来越稳定：

`任务输入 -> 任务裁剪 -> 文件读取/检索 -> 最小修改 -> 验证执行 -> trace 沉淀 -> 结果可比较`

只要这条链没有打通，就不要被以下方向带偏：

- 复杂 Web UI
- 多 Agent 编排
- Docker 隔离强化
- GitHub / MCP 深集成
- 更多任务类型
- 企业权限系统
- 更通用的 patch 引擎

这些都不是当前主线。

---

## 4. 后续阶段路线

### 阶段 A：把工具层接进最小 loop

目标：

- 让系统从“有工具”升级成“会用工具”

优先顺序：

1. 工具调用输入 / 输出在 runner 中落地
2. 工具级 trace 事件
3. 更完整的 run state 步骤推进
4. 固定 action budget 的最小 loop

停手点：

- 至少 1 条 demo 任务走通 `read -> search -> patch -> verify`
- trace 能回放工具调用过程
- 不追求自治 Agent，只追求固定流程可跑通

不应做的事：

- 不先扩 `apply_patch` 成通用 diff 引擎
- 不先做复杂 planner
- 不先做 registry 大抽象

### 阶段 B：只补最小上下文工程

目标：

- 只围绕真实 demo 暴露的问题补上下文能力

优先顺序：

1. 日志蒸馏
2. 文件选择策略
3. repo map 最小版

停手点：

- 无效读文件明显减少
- 平均步骤数下降或定位稳定性提升
- 不引入重型索引和复杂缓存体系

不应做的事：

- 不先做完整 repo intelligence 平台
- 不先做跨仓或重型索引
- 不先追求“一次选中文件最优”

### 阶段 C：打通 demo 任务闭环

目标：

- 让系统在窄范围任务上完成真实修复尝试

优先顺序：

1. 固定 demo 任务集
2. `ci_fix` / `test_regression_fix` 的最小支持
3. 端到端 trace 与 summary

停手点：

- 能在少量固定 demo 仓库上跑通真实修复尝试
- 失败路径也有可解释输出
- 不追求广泛任务覆盖

### 阶段 D：补评测闭环

目标：

- 让系统演进不再靠感觉，而是靠任务集和指标

阶段产物：

- 任务集格式
- batch runner
- 指标统计
- trace 聚合
- Markdown / JSON 报表

停手点：

- 每次策略变动后都可以量化比较
- 能回溯失败任务而不是靠记忆分析

### 阶段 E：轻量服务化与只读审查

目标：

- 在主线稳定后补 API 和 `pr_review`

候选内容：

- `pr_review`
- 结构化 review 输出
- API 触发任务
- trace 查询接口

说明：

- 这是“让核心能力更容易接入”，不是替代核心能力

### 阶段 F：企业化增强

目标：

- 只在主线成熟后再考虑企业级扩展

候选内容：

- Docker 隔离
- 审批 / 权限策略
- MCP 风格连接器
- 更多任务类型
- 多仓 / 多源接入

说明：

- 这一阶段不是首版承诺
- 任何企业化增强都不应反向拖慢核心 Agent 主线

---

## 5. 接下来一段时间的实际优先级

按照当前进展，后续最合理的连续推进顺序是：

1. 把工具层接进 runner 的最小固定流程
2. 为工具调用补 trace 事件和更完整的 run state
3. 准备 1 到 2 条真实 demo 任务，验证“读、搜、改、验”闭环
4. 只围绕 demo 暴露的问题补日志蒸馏与文件选择
5. 再补 batch eval 和指标统计

一句话概括：

先把“会用工具修一次”做出来，再把“更稳定位、可持续比较”补上。

---

## 6. 当前最不该做的事

以下方向当前都不应抢优先级：

- 提前做复杂 Web UI
- 提前做多 Agent 调度
- 提前做 Docker 隔离升级
- 提前做 GitHub / MCP 深集成
- 提前做大量任务类型扩展
- 提前把 `apply_patch` 做成通用引擎
- 提前做大而全的 prompt / context 平台

判断标准很简单：

如果它不能明显提升“最小修复闭环”能力，就不要先做。

---

## 7. 每轮开发前的判断清单

每次开始下一轮工作前，都先问自己：

1. 这项工作是否直接推动“读、搜、改、验、评测”主线？
2. 它是在补当前最短板，还是只是看起来顺手？
3. 如果现在不做它，主线真的会被卡住吗？
4. 这项工作完成后，是否能带来新的验收结果？
5. 它会不会把系统从“最小闭环”重新带回“平台化分心”？

如果以上问题里有 2 个以上回答不清楚，就先不要做。

---

## 8. 每个阶段的停手原则

- 工具阶段：够用、稳定、可测就停，不追求一次做到最强
- loop 阶段：固定 demo 能跑通就停，不追求通用自治
- 上下文阶段：能显著减少无效读取就停，不追求最优检索系统
- eval 阶段：能比较版本优劣就停，不追求复杂平台
- 服务化阶段：能触发和查询就停，不追求完整产品化

简单说：

每个阶段先拿到“能明显推进主线的最小结果”，不要在局部打磨到过度。

---

## 9. 文档使用方式

这份文档不是摆设，而是后续每次继续开发前都要先对照一遍的约束。

- 每次开始下一阶段前，先对照一遍
- 每次遇到范围膨胀时，回到这份文档重新排序优先级
- 如果后续路线真的发生变化，应先更新这份文档，再继续开发

它的职责不是替代详细实施计划，而是始终提醒：

`MendCode 当前最重要的事，是尽快成为一个能在本地代码仓内稳定完成最小修复闭环的 Agent。`

---

## 10. 2026-04-22 最新推进

第一优先级中的第一刀已经完成：

- `allowed_tools` 已绑定到 runner
- unauthorized tool 会被结构化拒绝并写入 trace
- `current_step` 已能反映真实失败阶段

第二刀也已经完成：

- 已固化多类 demo：
  - success
  - unauthorized-tool
  - ambiguous-search
  - verification-fail
- README 和任务样例已切换到 repo-native demo suite
- CLI / schema / README 已形成一套统一的 demo 合同

因此，接下来不要继续围绕 runner 内部小修小补打转。下一轮应直接推进：

1. 补最小 batch eval
2. 让 demo suite 的结果能批量对比
3. 再补最小 trace 聚合 / 报表，而不是先扩 planner 或 UI

当前的主线提醒可以再收紧成一句话：

`demo 已经够用了，下一步要让 demo 的结果可批量比较。`

---

## 11. 2026-04-23 路线更新：MVP eval 已落地

上一节的“补最小 batch eval”已经完成。当前路线要从“先补 batch eval”更新为“使用 batch eval 建立可比较基线”。

当前已经具备：

- 5 条 repo-native demo：
  - success
  - unauthorized-tool
  - ambiguous-search
  - verification-fail
  - python-unit-fix
- `eval run` 批量入口
- `summary.json` / `summary.md` 结果产物
- 一条真实 Python 源码修复 demo

下一步不要继续扩散成 eval 平台，也不要回到 runner 局部打磨。更合理的推进顺序是：

1. 固定当前 5 条 demo 为 MVP baseline
2. 用 batch eval 跑出第一版可比较结果
3. 只补影响判断的最小指标，例如失败阶段、工具结果和验证计数
4. 如果指标显示现有 demo 不够区分策略，再少量扩 demo
5. 最后再考虑更动态的 planner / model loop

当前路线一句话：

`批量入口已经有了，下一步要让每次策略变化都能被同一组 demo 衡量。`

---

## 12. 2026-04-23 全局路线更新：从“能跑”转向“能判断”

当前项目已经具备 MVP-0 基线，不应再把注意力放在“再补一个入口”或“再加几个 demo”上。现在最关键的问题变成：

`batch eval 跑出来的结果，是否能准确告诉我们系统有没有变好。`

### 12.1 当前所在阶段

当前主线链路已经推进到：

`任务输入 -> worktree 隔离 -> 工具调用 -> 最小 patch -> verification -> trace -> batch summary`

这说明“能跑一次”和“能批量跑”都已经初步成立。后续阶段应进入：

`结果解释 -> 指标聚合 -> baseline 对比`

### 12.2 下一阶段唯一主线

下一阶段建议命名为：

`Phase 2D：Eval Semantics and Baseline`

核心目标只有一个：

让当前 5 条 demo 不只是批量运行，而是能判断每条 demo 是否符合预期。

最小交付可以控制在三件事：

1. 定义 demo expected outcome
2. 在 batch summary 中输出 matched / mismatched
3. 聚合最小指标：失败阶段、工具状态、verification 计数

### 12.3 明确暂缓的方向

下面这些都可以做，但现在不应抢主线：

- 新增更多 demo，除非现有 5 条无法区分某个策略变化
- 做 Web 报表，除非 Markdown / JSON 已经不够用
- 做动态 planner，除非固定流的瓶颈已经被 eval 明确证明
- 做复杂 cleanup 生命周期，除非 preview worktree 已经明显影响迭代

### 12.4 当前行动口径

后续每轮开发前先看这个判断：

`如果这项工作不能让 batch eval 更准确地判断结果，就先不要做。`

---

## 13. 2026-04-23 用户入口校准：先保证 5 条命令能跑

从用户使用角度看，路线图需要补一个更靠前的判断：

`在继续优化 eval 语义前，必须先保证用户有一个最短、稳定、可复制的 quickstart。`

当前 quickstart 基线定义为 5 条命令：

```bash
mendcode version
mendcode health
mendcode task validate data/tasks/demo.json
mendcode task show data/tasks/demo.json
mendcode task run data/tasks/demo.json
```

这组命令是用户第一次接触 MendCode 时最重要的验收面。只要它们不稳定，后面的 batch eval、trace 聚合、expected outcome 都会显得偏内部工程。

### 13.1 当前路线微调

短期路线顺序调整为：

1. 先保住默认 `data/tasks/demo.json` quickstart
2. 再补 README 中“如何改 demo 做自己的简单实验”
3. 然后回到 `Phase 2D: Eval Semantics and Baseline`

### 13.2 停手原则

这一步不是要做完整用户产品，不做 UI、不做向导、不做复杂模板系统。

只要用户能复制 5 条命令完成一次修复实验，就停止 quickstart 打磨，回到 eval 语义主线。
