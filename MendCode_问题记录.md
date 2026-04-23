# MendCode 问题记录

## 1. 文档目的

本文档用于持续记录 MendCode 开发过程中遇到的典型问题、根因判断、解决方案和后续约束，避免同类问题反复出现。

这份文档不是临时备忘录，而是工程复盘材料。后续每当出现值得保留的问题时，都应按统一格式追加。

---

## 2. 记录规则

- 只记录真实遇到且对开发效率、代码质量、验证稳定性有影响的问题
- 每条记录尽量写清楚“现象、根因、解决方案、后续约束”
- 能明确关闭的问题标记为“已解决”
- 暂时只能缓解、还没有彻底消除的问题标记为“部分解决”或“待跟进”
- 优先记录工程问题，不优先记录纯讨论分歧

---

## 3. 记录模板

后续新增问题时，按以下模板追加：

```markdown
## 问题 N：标题

- 时间：
- 阶段：
- 状态：已解决 / 部分解决 / 待跟进

### 现象

### 根因

### 解决方案

### 后续约束
```

---

## 4. 已记录问题

## 问题 1：主工作区有未提交改动时，本地合并容易被阻塞

- 时间：Phase 0 收尾阶段
- 阶段：分支合并与工作树清理
- 状态：已解决

### 现象

在将 `phase-0-foundation` 合并回 `main` 时，主工作区存在未提交改动，直接合并会带来覆盖风险，也不适合粗暴清理。

### 根因

- 主工作区里已经有部分 Phase 0 结果，但并不完全等同于功能分支最终状态
- 如果直接 merge，Git 会因为脏工作树阻塞，或者把本地未提交内容和分支结果混在一起，增加判断成本

### 解决方案

- 先用 `git stash push -u` 暂存主工作区未提交内容
- 再执行本地 merge
- merge 后重新验证测试
- 最后核对 `stash` 中的内容是否已经被分支最终结果完全覆盖；若已覆盖，则删除 `stash`

### 后续约束

- 以后合并 worktree 分支回 `main` 前，优先先检查主工作区是否干净
- 不在脏工作区上直接做“边比对边 merge”的高风险操作

---

## 问题 2：`task_type` 在多个 schema 中重复定义，存在漂移风险

- 时间：Phase 1A / Task 1
- 阶段：`RunState` schema 落地
- 状态：已解决

### 现象

`RunState` 和 `TaskSpec` 都定义了相同的 `task_type` 枚举字面量集合，初期看起来没问题，但后续一旦新增任务类型，很容易只改一个地方。

### 根因

- 任务类型属于共享领域约束
- 如果在多个 schema 中复制 `Literal[...]`，维护时会产生隐性分叉

### 解决方案

- 在 [app/schemas/task.py](/home/wxh/MendCode/app/schemas/task.py) 中抽出共享的 `TaskType`
- `TaskSpec` 和 `RunState` 都统一复用这个类型别名

### 后续约束

- 以后遇到跨 schema 共用的枚举或关键约束，优先抽共享类型
- 不重复书写同一组领域常量

---

## 问题 3：runner 自己拼接 `trace_path`，和 recorder 的真实输出存在耦合

- 时间：Phase 1A / Task 2
- 阶段：最小 runner 落地
- 状态：已解决

### 现象

最初的 `run_task_preview()` 根据命名约定自己拼出 `trace_path`，而不是直接使用 `TraceRecorder.record()` 返回的路径。

### 根因

- runner 假设 recorder 的文件命名和落盘路径永远不变
- 一旦 recorder 后续引入分片、目录分层或命名调整，`RunState.trace_path` 就可能和真实落盘文件不一致

### 解决方案

- 改为以 `TraceRecorder.record(...)` 的返回值作为唯一可信的 trace 路径来源
- 补测试验证 runner 确实使用 recorder 返回的路径

### 后续约束

- 调用下层组件时，优先信任下层真实返回值，而不是在上层复制一份路径或状态推导逻辑

---

## 问题 4：CLI 集成测试过弱，容易出现“命令存在但行为退化”仍然通过的情况

- 时间：Phase 1A / Task 3
- 阶段：`task run` CLI 接线
- 状态：已解决

### 现象

初版集成测试只验证：

- 命令退出码为 0
- 输出中出现少量关键词
- 目录里有一个 trace 文件

这种断言只能证明命令“差不多跑了”，但不能证明它真的把 runner 的关键结果正确暴露出来。

### 根因

- 测试只覆盖了表面存在性，没有锁住核心契约
- CLI 是输出层，容易因为字段缺失、路径错误、trace 内容偏移而发生静默退化

### 解决方案

- 补充对 `current_step` 实际值的断言
- 补充对真实 `trace_path` 的断言
- 校验 trace 文件中的事件顺序
- 校验 `run.started` / `run.completed` 的关键 payload 字段，如 `task_type`、`summary`
- 调整断言顺序，先确认文件数量，再索引文件，避免测试失败时只得到无意义的 `IndexError`

### 后续约束

- 对 CLI 的集成测试，优先断言“关键契约”而不是“关键词存在”
- 优先验证实际输出值，而不是仅验证字段名

---

## 问题 5：README 容易落后于真实能力边界

- 时间：Phase 1A / Task 4
- 阶段：README 更新与最终验证
- 状态：已解决

### 现象

README 一开始仍使用 `Phase 0 Capabilities` 标题，但仓库已经具备 `task run` 这一 Phase 1A 能力，文档表述和实际能力出现错位。

### 根因

- README 在功能推进后只补了命令示例，没有同步修正能力说明
- 文档结构的旧阶段命名继续保留，导致读者容易误判当前仓库状态

### 解决方案

- 将 README 的能力段落改为 `Current Capabilities`
- 同步补充最小 `task run` preview 和对应 trace 输出描述

### 后续约束

- 每次新增用户可见入口时，都要同步检查 README 是否仍然准确
- 文档更新不能只加命令，不改上下文说明

---

## 问题 6：测试和 CLI 验证会反复生成 `__pycache__` 与临时 trace，容易污染工作树

- 时间：Phase 0 收尾到 Phase 1A 全过程
- 阶段：验证与收尾
- 状态：部分解决

### 现象

- 运行 `pytest` 后会生成多个 `__pycache__/`
- 运行 CLI smoke check 后会在 `data/traces/` 下生成临时 trace 文件
- 如果不清理，`git status` 会一直脏，影响收尾、审查和合并判断

### 根因

- Python 默认会生成字节码缓存
- CLI smoke check 本身就是带副作用的验证，会产生真实 trace 文件
- 当前仓库没有把这类临时产物全部纳入忽略或自动清理流程

### 解决方案

- 当前阶段采用“验证后显式清理”的方式处理
- 在任务收尾和最终验证前，统一清理 `__pycache__/` 和临时 trace 文件，再看 `git status`

### 后续约束

- 在进入收尾、合并、发布前，先做一次生成文件清理
- 后续如果这类问题继续频繁出现，可以评估是否要把相关临时产物纳入 `.gitignore` 或补一个统一的清理脚本

---

## 问题 7：CLI 集成测试若复用真实项目命令，容易引入环境耦合和伪失败

- 时间：Phase 1B / Task 4
- 阶段：CLI verification 集成测试收敛
- 状态：已解决

### 现象

最初的 CLI 集成测试把 `verification_commands` 写成 `pytest -q`。在临时目录里执行 `task run` 时，这个命令会依赖外部测试环境和当前工作目录，导致测试失败原因并不一定来自 CLI 行为本身。

### 根因

- 集成测试复用了“像真实命令”的验证方式，而不是“可控命令”
- `pytest -q` 对执行目录、测试发现结果和环境状态都敏感
- 这会把本应验证 CLI 输出契约的测试，变成混合了环境依赖的脆弱测试

### 解决方案

- 把 CLI 集成测试中的验证命令收敛为可控的 `python -c ...` 命令
- 成功路径和失败路径都用可预测的单条命令表达
- 让测试红灯聚焦在 CLI 汇总输出和退出码语义，而不是外部环境

### 后续约束

- 后续凡是验证 CLI / runner 汇总语义的集成测试，优先使用可控命令，不直接复用真实项目级命令
- 只有在专门做端到端或 smoke 场景时，才引入 `pytest` 这类环境敏感命令

---

## 问题 8：若继续把 command policy 和 workspace 副作用堆进 runner，后续工具链会快速失控

- 时间：Phase 1B 下一阶段设计收敛
- 阶段：command policy / worktree 方案确定
- 状态：部分解决

### 现象

在 Phase 1B 第一切片完成后，runner 已经同时承担运行编排、命令执行、trace 汇总三类职责。如果下一步继续把白名单、超时、worktree 创建和 cleanup 也直接加进 `app/orchestrator/runner.py`，这个文件会很快同时负责策略层、执行层和 workspace 层。

### 根因

- 当前仓库还处在“最小执行链刚刚跑通”的阶段，短期上容易继续采用“哪里能塞就塞哪里”的方式推进
- runner 处在主链中心，天然容易被当成所有逻辑的承载点
- 如果此时不先划清边界，后续接 `read_file` / `search_code` / `apply_patch` 时会进一步放大耦合

### 解决方案

- 在设计上先收敛为“小而清晰的执行边界拆分”
- 新增 `app/workspace/command_policy.py`、`app/workspace/executor.py`、`app/workspace/worktree.py`
- 让 runner 回到“编排 + 汇总 + trace”职责，不直接承担全部策略判断与工作区副作用
- 开发顺序固定为“先 command policy，再 worktree manager”

### 后续约束

- 后续新增执行边界或工作区相关能力时，优先放在 `app/workspace/`，不要继续堆进 runner
- 如果某个能力同时涉及策略判断和命令执行，默认拆成 policy 与 executor 两层，而不是写成一个大函数

## 问题 9：新建 worktree 若只基于最近提交，可能缺失主工作区未提交但已确认的收敛改动，导致基线再次变脏

- 时间：Phase 1B 开发前基线清理
- 阶段：隔离 worktree 启动与基线恢复
- 状态：已解决

### 现象

为执行 Phase 1B 计划新建隔离 worktree 后，`pytest -q` 和 `ruff check .` 立刻暴露出基线问题：

- CLI 仍停留在较早版本，没有展示 verification 汇总字段
- `tests/integration/test_cli.py` 仍包含环境敏感的 `pytest -q` 命令和旧 trace 契约
- `tests/unit/test_runner.py` 仍有既有 lint 问题

这说明新 worktree 虽然基于最新提交，但没有包含主工作区里尚未提交、却已经确认过的收敛改动。

### 根因

- `git worktree add` 只基于已提交历史创建工作区，不会自动带入主工作区的未提交改动
- 当前阶段上一轮收敛结果还没有全部进入提交历史
- 因此新 worktree 的“提交基线”与主工作区的“真实开发基线”发生了偏差

### 解决方案

- 先停止 Phase 1B 新功能开发，优先恢复新 worktree 基线
- 将 CLI 汇总输出与对应测试收敛到当前 runner 契约
- 将环境敏感的集成测试命令改为可控命令
- 修复既有 lint 问题，并重新验证 `pytest -q` 与 `ruff check .`

### 后续约束

- 以后从主工作区切新 worktree 前，先确认关键收敛改动是否已经提交，避免把“未提交共识”丢在旧工作区
- 如果必须从一个仍有未提交收敛改动的主工作区切新 worktree，进入开发前先做一次基线校准，不要直接开始新功能任务

---

## 问题 10：嵌套 worktree 下直接调用 `pytest`，可能命中外层主工作区的 editable install，导致测试加载到旧代码

- 时间：Phase 1B / Task 1
- 阶段：schema / settings 底座落地与验证
- 状态：部分解决

### 现象

在 `/home/wxh/MendCode/.worktrees/...` 这样的嵌套 worktree 中执行：

- `python -m pytest ...` 会加载当前 worktree 中的代码，测试通过
- `pytest ...` 则可能加载外层主工作区 `/home/wxh/MendCode` 的 editable install，表现为测试仍然看到旧版 schema，形成“代码已改、测试仍像没改”的假象

### 根因

- 当前 Python 环境里存在指向外层主工作区的 editable install
- `pytest` console entrypoint 与 `python -m pytest` 的导入路径优先级不同
- 当 worktree 嵌套在主工作区目录下时，这个差异会被放大

### 解决方案

- 当前阶段先以 `python -m pytest ...` 作为 worktree 内的权威验证方式
- 在 review 中显式区分“代码问题”和“入口脚本加载路径问题”，避免误判实现未生效
- Task 2 的 implement / review / 修正阶段都已按这一策略执行，当前实践证明这条规避方式有效
- Task 3 的 git worktree 单测同样延续该策略，当前没有再出现“实现已更新但测试命中旧包”的误判
- Task 4 的 runner / CLI 接线验证继续沿用该方式，已经可以稳定支撑更大范围的 focused test 与整套 `pytest -q`

### 后续约束

- 后续在该 worktree 内执行 Python 测试时，优先使用 `python -m pytest`
- 进入更大范围的实现前，可以评估是否要清理或重装 editable install，避免 `pytest` / `python -m pytest` 行为继续分叉

---

## 问题 11：没有 workspace 隔离时，verification 命令会直接对仓库工作目录产生副作用

- 时间：Phase 1B command policy / worktree 落地
- 阶段：runner 执行边界治理
- 状态：已解决

### 现象

verification 命令原先直接在 `task.repo_path` 下执行，后续一旦引入补丁修改能力，真实仓库会直接暴露给任务运行副作用。

### 根因

- 初版 runner 只追求跑通验证链路，没有 workspace 抽象
- 命令执行边界和 repo 工作目录耦合在一起

### 解决方案

- 为每次 run 创建独立 `.worktrees/preview-<id>/`
- verification 默认在 worktree 中执行
- trace 记录 `workspace_path` 与 cleanup 结果

### 后续约束

- 后续 `read_file` / `search_code` / `apply_patch` 都应优先围绕 `workspace_path`，而不是直接操作 `task.repo_path`

---

## 问题 12：嵌套 worktree 下直接调用 `mendcode`，可能命中外层主工作区的 editable install，导致 CLI 验证对错代码

- 时间：Phase 1B / Task 5 收尾
- 阶段：README 与 smoke 验证收敛
- 状态：已解决

### 现象

在 `/home/wxh/MendCode/.worktrees/...` 这样的嵌套 worktree 中：

- `python -m app.cli.main task run ...` 会加载当前 worktree 中的代码
- 直接调用 `mendcode task run ...` 可能命中外层主工作区安装出来的 console script
- 结果是 CLI 看似可运行，但验证的并不是当前分支代码

### 根因

- `mendcode` console script 来自已有 editable install
- 嵌套 worktree 开发时，console script 的导入目标不一定指向当前 worktree
- 因此“命令跑通”不等于“当前分支实现已被验证”

### 解决方案

- 在当前阶段把 `python -m app.cli.main ...` 作为 worktree 内 CLI 验证的权威入口
- README 明确区分：
  - 正常安装使用场景可继续使用 `mendcode ...`
  - 嵌套 worktree 开发和收尾场景优先使用 `python -m app.cli.main ...`
- smoke 用例同步收敛到当前 worktree 可控入口

### 后续约束

- 后续在嵌套 worktree 中做 CLI 验证、回归测试和收尾判断时，优先使用 `python -m app.cli.main ...`
- 如果未来需要统一开发体验，应考虑在工程层面解决 editable install 与 worktree 的入口漂移，而不是继续人工记忆规避

---

## 问题 13：运行测试与 CLI 后，仓库会被 `trace`、缓存文件和已跟踪 `.pyc` 污染，导致收尾判断失真

- 时间：Phase 1B 合并回 `main` 后的全面排查
- 阶段：合并后稳定性检查与仓库 hygiene 收口
- 状态：已解决

### 现象

在 `main` 上完成合并后执行：

- `python -m pytest -q`
- `python -m app.cli.main task run data/tasks/demo.json`

随后 `git status` 会立刻变脏，表现为：

- `data/traces/`、`.pytest_cache/`、`.ruff_cache/`、各级 `__pycache__/` 持续生成
- 仓库里还跟踪着一批 `.pyc` 文件，导致每次运行后都会出现已修改的字节码文件
- 这样会干扰“合并是否干净”“当前分支是否可收尾”的判断

### 根因

- `.gitignore` 之前只忽略了 `.worktrees/`，没有覆盖常见运行产物
- 历史提交曾把 Python 字节码文件纳入版本控制
- 因此只要跑过测试或 CLI，就会把运行时副作用直接反映到仓库状态上

### 解决方案

- 新增 `tests/unit/test_repo_hygiene.py`
- 用测试约束：
  - `.gitignore` 必须覆盖常见运行产物
  - 仓库不能继续跟踪 `.pyc` / `__pycache__`
- `.gitignore` 补齐：
  - `data/traces/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `__pycache__/`
  - `*.py[cod]`
- 将仓库里历史遗留的 `.pyc` 文件从版本控制中移除

### 后续约束

- 后续每次新增新的运行产物目录或缓存文件时，要同步补 `.gitignore` 与对应校验
- 进入收尾、合并或发布判断前，先确认 `git status` 只反映真实源码变更，而不是运行时垃圾文件

---

## 问题 14：subagent 若未先校验 cwd 与分支，可能把改动写进主工作区而不是目标 worktree

- 时间：Phase 2A 只读工具开发
- 阶段：subagent 协同与 worktree 隔离执行
- 状态：部分解决

### 现象

在 `phase-2a-readonly-tools` 开发过程中，早期有 subagent 产出的提交没有落在目标 worktree，而是直接写到了主工作区 `main`。这会导致：

- 当前功能分支看起来没有拿到预期改动
- 主工作区意外出现本不该属于 `main` 的本地提交
- 后续不得不靠人工比对和 `cherry-pick` 补救，增加收尾成本

### 根因

- 只在提示词里写“去某个 worktree 工作”并不能保证 agent 真在那个目录执行
- subagent 默认执行上下文可能仍然继承主工作区
- 如果开始前不显式核对 `pwd` 与 `git branch --show-current`，错误会在提交后才暴露

### 解决方案

- 后续所有 subagent 开工前，先打印并校验：
  - `pwd`
  - `git branch --show-current`
- 只有确认当前目录和分支都指向目标 worktree 后，才允许开始编辑和提交
- 对已经误落在主工作区的提交，不做危险回滚，改为人工审查后 `cherry-pick` 到目标分支

### 后续约束

- 以后只要任务依赖 worktree 隔离，就把“cwd / branch 先验校验”当作硬前置步骤
- subagent 返回结果时，优先核对它的实际工作目录和提交所属分支，再决定是否集成
- 如果发现 agent 落错工作区，先停下来处理隔离边界，不要带着脏上下文继续推进功能

---

## 问题 15：阶段性 spec 的“非目标”在后续路线里变成“下一刀目标”时，若没有显式补充边界说明，执行阶段容易出现范围歧义

- 时间：Phase 2A 工具层继续推进
- 阶段：从只读工具切到最小 `apply_patch`
- 状态：已解决

### 现象

当前仓库里存在两份都成立的文档信息：

- Phase 2A 只读工具 spec 明确写了“本轮不实现 `apply_patch`”
- 根开发方案在后续推进中又把“先补 `apply_patch`”收敛成了下一步

如果直接按其中一份文档单独执行，就会出现“到底该不该现在做 `apply_patch`、做到多宽”为代表的范围歧义。

### 根因

- 阶段性 spec 解决的是“上一刀的边界”，不是“后续所有切片的永久约束”
- 随着路线推进，开发方案已经更新，但没有同步补一个面向下一刀的最小边界说明
- 因此执行者需要自己推断“现在该按旧 spec 还是按新路线走”

### 解决方案

- 在真正开工前，先把这次实现范围收敛成明确假设：
  - 只做最小 `apply_patch`
  - 只支持 `workspace_path` 内单文件精确文本替换
  - 不做通用 unified diff 引擎
  - 不接 orchestrator 自动链路
- 同步把这个收敛结果更新回开发方案，避免后续继续被旧表述误导

### 后续约束

- 当某个功能从“上一轮 spec 的非目标”变成“当前路线的下一刀目标”时，进入编码前先补一条显式边界说明
- 优先把“这次到底做到哪里”写回开发方案，再开始实现，避免执行阶段靠个人解释补空白
- 如果新切片只是旧 spec 的自然延伸，也要明确写出这次新增的最小能力面，不要默认所有人都会同样理解

---

## 问题 16：如果全局路线图只存在于主工作区而不在当前功能分支同步，后续规划容易出现跨 worktree 漂移

- 时间：Phase 2A 路线校准
- 阶段：开发方案与全局路线图对齐
- 状态：已解决

### 现象

在当前 `phase-2a-readonly-tools` worktree 内继续做路线分析时，分支里只有 `MendCode_开发方案.md` 和 `MendCode_问题记录.md`，而全局路线图只存在于主工作区。结果是：

- 当前分支的策略判断需要去对照另一个 worktree 里的文档
- 很容易出现“当前分支已经推进到新阶段，但参考路线仍停留在别处分支”的认知偏差
- 文档更新后也不容易保证同一条开发线上的自洽性

### 根因

- 全局路线图最初是在主工作区单独维护的
- 后续进入 feature worktree 开发后，没有同步保留 branch-local 副本
- 因此“当前实现状态”和“当前主线判断”被拆到了不同工作区

### 解决方案

- 在当前功能分支内补齐 `MendCode_全局路线图.md`
- 后续涉及阶段收敛、主线调整和优先级重排时，优先更新当前 worktree 内的路线图和开发方案
- 让“当前能力状态、当前主线判断、当前问题记录”在同一条分支里一起演进

### 后续约束

- 以后只要在独立 worktree 中连续推进某条开发线，就同步维护该分支内的开发方案和全局路线图
- 不把“当前实现”和“当前路线”长期拆在不同工作区维护
- 如果主工作区也需要保留路线文档，应在合并后再统一回写，不在中途依赖跨 worktree 对照作为主要信息源

---

## 问题 17：subagent review 在额度或会话中断时不可作为唯一收口前提，否则会卡住主线推进

- 时间：2026-04-22
- 阶段：Phase 2B fixed-flow runner 收口
- 状态：部分解决

### 现象

在对 Phase 2B 的 Task 3-4 合并切片做最终 code-quality review 时，reviewer subagent 在重新拉取结论阶段触发额度限制，导致没有拿到结构化审查结果。如果把“必须等 subagent 最终回包”当作唯一收口条件，开发会在已经具备本地验证证据的情况下被迫停住。

### 根因

- subagent review 是高价值质量闸门，但它依赖额度和会话可用性，不是永远稳定的基础设施
- 当前流程里对“reviewer 不可用时的降级路径”约束还不够明确
- 如果控制器不及时切换到本地 scoped review，就会把流程问题误当成代码问题

### 解决方案

- 立即切换为 controller 本地 scoped review：
  - 限定 review 范围到当前切片实际改动文件
  - 结合 focused test 与 `ruff` 重新给出收口结论
- 本次具体采取了：
  - 本地重跑 `python -m pytest tests/unit/test_run_state.py tests/unit/test_runner.py -v`
  - 本地补做 `ruff check app/orchestrator/runner.py tests/unit/test_runner.py`
  - 先清理 lint 基线，再进入下一任务

### 后续约束

- 后续继续使用 subagent review，但不能把它当作唯一收口机制
- 如果 reviewer 因额度、环境或会话中断不可用，优先执行：
  - scoped local review
  - focused tests
  - touched-files lint
- 文档和进度判断应基于“代码状态 + 验证证据”，而不是单一依赖某个 agent 是否成功回包

---

## 问题 18：如果 demo task 直接依赖 README 中某段文案，README 的产品文案更新会反向破坏 demo 可修复性

- 时间：2026-04-22
- 阶段：Phase 2B / Task 5 demo task 收口
- 状态：已解决

### 现象

当前 fixed-flow demo 选择通过修改 `README.md` 中一条已存在的文案来证明 `search -> read -> patch -> verify` 闭环成立。这类 demo 很轻量，但也带来一个耦合：如果在同步 README 能力说明时，顺手把 demo 依赖的原始文本一并改掉，那么 `data/tasks/demo.json` 里的 `old_text` 就会在仓库基线中消失，demo 立即失效。

### 根因

- demo task 需要一个稳定、可搜索、可补丁的目标文本
- 当前选择的目标文本恰好位于 README，而 README 又是频繁更新的说明文档
- 如果没有显式约束，就很容易在“更新 README 描述能力”和“保留 demo 修复锚点”之间互相踩踏

### 解决方案

- 保留 demo task 依赖的原始 README 文案作为仓库基线
- README 的 fixed-flow 能力说明改写到其他位置，不直接吃掉 demo 依赖的 `old_text`
- 用 `python -m app.cli.main task run data/tasks/demo.json` 做一次真实跑通，确认 demo 仍然有效

### 后续约束

- 后续如果 demo task 依赖仓库内真实文件内容，必须把“演示锚点文本”当作受保护输入看待
- 更新 README、fixture 或示例文件时，先检查是否被 `data/tasks/*.json` 当作 `search_query` / `old_text` 使用
- 如果后续文档改动频繁到影响 demo 稳定性，应把 demo 目标迁移到专门的 fixture 文件，而不是继续绑定 README

---

## 问题 19：当 demo fixture 从“verification-only”升级为“fixed-flow”后，如果其他测试仍把它当旧 fixture 使用，会在全量验证阶段暴露延迟断言漂移

- 时间：2026-04-22
- 阶段：Phase 2B / Task 6 全量验证
- 状态：已解决

### 现象

在 `data/tasks/demo.json` 切换为 fixed-flow demo 后，focused CLI 和 runner 测试都已通过，但全量 `python -m pytest -v` 仍然在 `tests/unit/test_task_schema.py` 失败。原因不是 schema 本身出错，而是该测试还在按旧 fixture 断言：

- `allowed_tools == ["read_file", "search_code"]`
- `entry_artifacts["log"] == "pytest failed: test_example"`

而当前 demo fixture 已经变成：

- `allowed_tools` 包含 `apply_patch`
- `entry_artifacts` 改为 `search_query / old_text / new_text`

### 根因

- `data/tasks/demo.json` 被多个测试当作共享 fixture 使用
- focused 验证只覆盖了本轮直接触达的 CLI / runner 路径，没有覆盖到所有引用该 fixture 的单测
- fixture 语义升级后，如果不同时扫一遍引用点，漂移会在最后的全量阶段才暴露

### 解决方案

- 更新 `tests/unit/test_task_schema.py` 中对 demo fixture 的断言，使之匹配当前 fixed-flow 结构
- 在切换共享 fixture 语义后，补做一次全量 `pytest -v`，确保没有遗漏的旧断言

### 后续约束

- 以后只要改动 `data/tasks/*.json` 这类共享 fixture，必须默认认为会影响：
  - schema fixture 测试
  - CLI 集成测试
  - demo 文档说明
- focused tests 通过后，不把阶段判定为完成，必须继续跑一次全量验证来兜底 fixture 漂移

## 5. 下一步维护建议

- 后续进入 Phase 1B 时，继续按这份文档追加真实问题，不要等到阶段结束再回忆补录
- 对“已经复发两次以上”的问题，优先考虑从工程机制层解决，而不是继续人工规避
- 如果某个问题已经沉淀成明确规则，可以同步回写到开发方案或 README，而不是只留在问题记录里

---

## 问题 20：`allowed_tools` 只存在于 schema 中而不进入 runner，会把安全边界停留在“声明层”而不是“执行层”

- 时间：2026-04-22
- 阶段：Phase 2C / runner 执行契约收口
- 状态：已解决

### 现象

任务文件和 schema 已经支持 `allowed_tools`，但 fixed-flow runner 在执行 `search_code`、`read_file`、`apply_patch` 时并不会依据这个字段做真正的授权判断。

### 根因

- 前一阶段重点是先把固定流跑通
- 因此安全字段先落在 schema，执行期绑定被延后

### 解决方案

- 在 runner 中为 fixed-flow 工具调用增加统一授权检查
- 未授权工具不再真正执行，而是返回结构化 `ToolResult(status="rejected")`
- 保持现有 tool trace 语义，让 rejected 结果同样可回放

### 后续约束

- 以后所有进入任务 schema 的安全字段，都必须尽快落到执行链
- 不长期保留“声明了但不执行”的灰区能力

## 问题 21：如果失败路径一律把 `current_step` 写成 `summarize`，CLI 和 run state 会丢失真正的卡点

- 时间：2026-04-22
- 阶段：Phase 2C / runner 状态表达收口
- 状态：已解决

### 现象

在 fixed-flow 输入非法、search 歧义、inspect 失败、verification 失败等场景下，`RunState.current_step` 之前几乎都会落成 `summarize`。这意味着最终状态虽然有 `failed`，但看不到实际失败发生在 `bootstrap`、`locate`、`inspect` 还是 `verify`。

### 根因

- 初版 `RunState` 更偏向“输出摘要状态”，不是“表达执行进度”
- runner 在构建最终状态时统一写死了 `summarize`

### 解决方案

- 在 runner 内维护真实阶段推进
- 失败时保留失败发生的阶段
- 只有成功完成后才把最终状态推进到 `summarize`

### 后续约束

- 以后如果扩展 planner 或更多工具，必须继续沿用“失败保留卡点、成功进入 summarize”的规则
- 任何 run-state 字段只要用于 CLI 或 eval，就不能只做展示字段，必须与执行真实状态一致

## 问题 22：repo-native demo 测试如果不固定 `cwd` 和 `MENDCODE_PROJECT_ROOT`，会在不同启动目录下命中不同仓库

- 时间：2026-04-22
- 阶段：Phase 2C / demo task suite CLI 覆盖
- 状态：已解决

### 现象

新加的 demo CLI 测试在 worktree 根目录运行时通过，但如果从外层主工作区启动 pytest，再指向 worktree 下的测试文件，测试会出现：

- `repo_path='.'` 指向错误仓库
- trace 写到错误的 `data/traces/`
- worktree 建到错误的 `.worktrees/`
- success / ambiguous / unauthorized / verification-fail 的断言集体漂移

### 根因

- demo task fixture 使用的是相对 `repo_path='.'`
- 测试最初没有固定 `cwd`
- 也没有固定 `MENDCODE_PROJECT_ROOT`
- 因此同一条测试会跟随 pytest 的启动目录改变运行目标

### 解决方案

- 在 `tests/integration/test_cli.py` 中增加 repo-native demo 测试的统一环境配置
- 对这些测试统一：
  - `monkeypatch.chdir(repo_root)`
  - `monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(repo_root))`
  - 固定 `console.width`
- 同时补断言，校验 `trace_path` / `workspace_path` 确实落在当前 worktree 根下

### 后续约束

- 以后凡是 task fixture 使用相对 `repo_path`，测试必须显式固定运行根目录
- 对 repo-native demo 测试，不能只断言状态文字，还要断言 trace / workspace 的根路径

## 问题 23：README 回归测试如果只校验“路径出现”，无法真正锁住命令契约

- 时间：2026-04-22
- 阶段：Phase 2C / README 与 demo suite 对齐
- 状态：已解决

### 现象

README 初版回归测试只校验四个 demo 路径存在、旧路径不存在。这样即使 README 以后删掉命令块，只留下几行文件路径或一句说明，测试仍然会通过。

### 根因

- 测试只锁住了“素材存在”，没有锁住“用户实际如何调用”
- README 的真正契约并不是 demo 文件名本身，而是两组可执行命令：
  - `mendcode ...`
  - `python -m app.cli.main ...`

### 解决方案

- 将 README 测试收紧为断言具体命令行
- 同时覆盖：
  - installed usage 的 `mendcode task ...`
  - worktree 开发态的 `python -m app.cli.main task ...`
- 继续保留旧路径 `data/tasks/demo.json` 不得出现的负向断言

### 后续约束

- 以后凡是 README 承载“命令合同”的地方，测试优先校验完整命令，而不是只校验关键词或路径
- 文档测试要尽量锁住“用户真的会复制运行的东西”，而不是锁住弱语义片段

## 问题 24：`pytest` 控制台入口可能导入旧安装包，导致新源码测试出现伪失败

- 时间：2026-04-23
- 阶段：Phase 2C / batch eval 审查
- 状态：已解决

### 现象

Task 2 规格审查时，单独运行 `pytest tests/unit/test_batch_eval.py` 出现 `ModuleNotFoundError: No module named 'app.eval'`。但在仓库根目录运行 `python -m pytest tests/unit/test_batch_eval.py` 可以通过。

进一步排查发现，`pytest` 控制台入口会在当前环境中导入旧的已安装 `app` 包；同样问题也会影响既有 `tests/unit/test_settings.py`，不是 batch eval 新代码独有问题。

### 根因

- 当前开发环境中存在旧安装包或 console-script 路径优先级问题
- `pytest` 入口和 `python -m pytest` 的 `sys.path` 行为不同
- 活跃实施计划已经切换到 `python -m pytest`，但审查时混用了 console-script 入口

### 解决方案

- 将本轮验证口径统一为 `python -m pytest ...`
- 对审查反馈进行复核，确认 Task 2 实现本身符合规格
- 后续计划和验证命令继续优先写 `python -m pytest`

### 后续约束

- 在嵌套 worktree 或 editable install 不稳定的环境里，优先使用 `python -m pytest`
- 如果 reviewer 报导入错误，先区分是源码问题还是测试启动入口问题
- 不因为环境伪失败盲目改业务代码

## 问题 25：故意失败的 demo pytest 文件如果可被根目录收集，会污染项目级测试

- 时间：2026-04-23
- 阶段：Phase 2C / Python unit-fix demo
- 状态：已解决

### 现象

`python-unit-fix` demo 初版把故意失败的检查文件放在 `data/demo-fixtures/python-unit-fix/tests/test_buggy_math.py`。默认 `python -m pytest` 因为 `testpaths = ["tests"]` 不会收集它，但显式运行 `python -m pytest .` 会把这个文件收集进来，并在 demo 修复前失败。

### 根因

- demo 需要一个“修复前失败、修复后通过”的 pytest 检查
- 但如果检查文件使用常规 `tests/test_*.py` 命名，它就可能被项目级 pytest 发现
- demo fixture 的失败语义和项目自身测试的通过语义被混在了一起

### 解决方案

- 将检查文件移动到 `data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py`
- 更新 `python-unit-fix.json` 的 verification command，继续显式运行该文件
- 验证 `python -m pytest . --collect-only` 不再收集 demo check
- 保留显式运行该 check 时“修复前失败”的 demo 语义

### 后续约束

- 以后 demo fixture 中如果需要故意失败的测试，不要放在会被项目级 pytest 自动发现的位置
- demo verification 可以显式指定文件路径，但文件命名应避免 `test_*.py` 自动收集模式
- 批量 demo 要证明目标修复失败，不应让仓库自身测试因此变红

## 问题 26：batch eval 只统计 runner 状态，会把“预期失败 demo”误读成评测失败

- 时间：2026-04-23
- 阶段：Phase 2C / MVP eval 基线复盘
- 状态：待跟进

### 现象

当前 5 条 demo 中，`unauthorized-tool.json`、`ambiguous-search.json`、`verification-fail.json` 本来就是用来证明失败路径表达是否正确的任务。运行 batch eval 后，summary 会显示类似：

- `task_count = 5`
- `completed_count = 2`
- `failed_count = 3`

从 runner 机械状态看这是正确的，但从 eval 语义看，3 条 failed demo 可能恰恰是“按预期失败”。如果后续只看 `failed_count`，就会误以为 baseline 有 3 个回归。

### 根因

- 当前 `BatchEvalSummary` 只复用 `RunState.status`
- demo task 还没有声明 expected outcome
- eval 层没有区分“任务运行失败”和“评测不符合预期”

### 解决方案

下一阶段应补最小 expected-outcome 语义，不做复杂平台：

- 在 demo metadata 或独立 eval manifest 中声明：
  - expected status
  - expected current_step
  - expected tool status / verification count
- batch eval 继续保留 raw runner status
- 同时新增 `matched_expectation` 或类似字段，表达“该 demo 是否符合预期”

### 后续约束

- eval 报表不能只展示 completed / failed，否则会误导策略判断
- 失败路径 demo 必须被当作一等公民，不要为了让 completed_count 好看而删除
- 下一步优先补 eval 语义，不要急着扩更多 demo

## 问题 27：反复运行 demo / batch eval 会保留大量 preview worktree，长期可能造成磁盘和排查噪声

- 时间：2026-04-23
- 阶段：Phase 2C / MVP eval 基线复盘
- 状态：待跟进

### 现象

当前 `task run` 会为每次运行创建 `.worktrees/preview-<id>/`。这对调试和 trace 回放有价值，但在 batch eval 和反复验证中会快速产生大量 preview worktree。它们被 Git 忽略，不会污染 `git status`，但会增加磁盘占用和人工排查噪声。

### 根因

- 当前默认策略更偏向可复盘：成功工作区也会保留
- batch eval 会一次触发多条 task run
- 还没有专门的 eval cleanup 策略或保留上限

### 解决方案

短期不急着实现自动清理，避免影响调试；但下一阶段需要设计最小策略：

- 保持单任务调试默认可保留 worktree
- batch eval 可提供显式 cleanup 开关或只保留失败/不符合预期的工作区
- README 或问题记录中明确 `.worktrees/preview-*` 属于运行产物

### 后续约束

- 不要在还没稳定 eval 语义前做复杂生命周期管理
- 但一旦开始频繁跑 batch eval，就必须有清理策略
- 清理策略必须优先保护失败样本的可复盘性

## 问题 28：删除默认 `data/tasks/demo.json` 会让最自然的用户 quickstart 命令失败

- 时间：2026-04-23
- 阶段：User-facing MVP / Quickstart 收口
- 状态：已解决

### 现象

从内部开发视角看，repo-native demo suite 已经替代旧的单文件 demo；但从用户视角看，最自然会尝试的命令仍然是：

- `mendcode task validate data/tasks/demo.json`
- `mendcode task show data/tasks/demo.json`
- `mendcode task run data/tasks/demo.json`

此前 `data/tasks/demo.json` 已被移除，导致这三条命令直接返回 `Task file not found`。

### 根因

- 开发过程优先收口 demo suite，忽略了“默认入口”的用户心智
- README 虽然提供了新 demo suite 路径，但缺少最短 quickstart
- 测试曾经锁住“旧 demo 被移除”，这与用户可用 MVP 的目标冲突

### 解决方案

- 恢复 `data/tasks/demo.json`，作为默认 quickstart 成功任务
- README 增加 5 条最短命令
- 测试改为锁住默认 demo 可加载、可预览、可运行

### 后续约束

- demo suite 可以扩展，但必须保留一个稳定默认 demo
- 用户文档第一屏必须有最短可复制命令
- 删除旧入口前必须先确认它不是用户 quickstart 入口
