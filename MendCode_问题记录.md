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

- CLI 集成测试优先使用可控、无外部依赖的 verification 命令
- 不把环境稳定性问题误当成 CLI 行为问题

## 问题 8：方案文档滞后于真实代码进度，容易围绕已完成目标反复打转

- 时间：2026-04-22
- 阶段：Phase 2 主线收口
- 状态：已解决

### 现象

根目录方案和路线图中仍保留“工具尚未真正接进 loop”“runner 还缺工具级 trace”等旧判断，但主干代码已经具备 fixed-flow 的 `search -> read -> patch -> verify` 闭环。

### 根因

- 文档更新节奏落后于代码合并节奏
- 前期阶段判断没有在每次主线推进后做一次统一校准

### 解决方案

- 重新按主干真实状态校准开发方案和全局路线图
- 把下一阶段重点从“继续接线”收口到“补安全契约、状态推进、demo 基线、最小 eval”

### 后续约束

- 每次主线能力合并后，都要检查根文档是否还在描述过期目标
- 任何“下一步计划”都先以主干真实代码为准，不以旧方案文字为准

## 问题 9：`allowed_tools` 已进入任务 schema，但尚未真正约束 runner

- 时间：2026-04-22
- 阶段：Phase 2 fixed-flow 收口
- 状态：待跟进

### 现象

任务文件已经可以声明 `allowed_tools`，测试 fixture 和 demo 也在写这个字段，但当前 runner 的 fixed-flow 执行并没有依据它决定工具是否可调用。

### 根因

- `allowed_tools` 目前只停留在 schema 和任务数据层
- 工具能力与任务授权之间还没有形成真正的执行期绑定

### 解决方案

- 在 runner 中为固定流工具调用增加显式授权检查
- 对未授权工具返回结构化 rejected 结果并写入 trace
- 用单测和 CLI 集成测试锁定该契约

### 后续约束

- 以后凡是任务 schema 中声明的安全边界，都必须尽快落到执行链
- 不保留“文档里声明了、代码里暂时不执行”的长期灰区

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

## 问题 20：`old_text/new_text` 让用户提前提供答案，削弱 Code Agent 价值

- 时间：2026-04-24
- 阶段：Agent MVP 路线重定向
- 状态：待跟进

### 现象

当前任务协议和 demo 仍以用户指定补丁为主，例如：

```json
{
  "old_text": "return a - b",
  "new_text": "return a + b"
}
```

这类输入要求用户已经知道错误代码和正确代码。对用户而言，MendCode 更像“安全补丁执行器”，而不是“描述问题后自动定位、修复、验证的本地 Code Agent”。

### 根因

- 早期阶段优先构建安全执行底座，先实现 worktree、tool policy、patch、verification、trace
- 为了快速打通 demo，任务协议选择了更容易验证的显式补丁格式
- quickstart 修复了“命令能跑”的问题，但没有解决“用户是否需要知道答案”的产品问题

### 解决方案

后续路线应把 `old_text/new_text` 降级为兼容字段，主入口改为问题描述：

```json
{
  "problem_statement": "pytest 中 test_add 失败，请定位并修复问题",
  "verification_commands": ["python -m pytest -q"],
  "max_attempts": 3
}
```

同时新增 CLI 主入口：

```bash
mendcode fix "pytest 失败了，请定位并修复" --test "python -m pytest -q"
```

实现上应补齐：

- 自动运行验证命令并捕获失败日志
- 从 pytest 日志中提取失败测试、异常、文件路径和函数名
- 用测试文件、import 和 `rg` 做最小代码检索
- 让 LLM 根据问题、日志和相关代码生成结构化 patch
- 由 MendCode 负责安全应用 patch、重新验证和 trace 记录
- 增加 `diff/apply/discard/trace <run_id>` 形成用户闭环

### 后续约束

- 用户主入口不应要求提供最终 patch
- 新 demo 应优先从失败描述和验证命令开始，而不是从 `old_text/new_text` 开始
- `old_text/new_text` 只保留给兼容旧任务、回归测试和少量执行层 fixture
- 如果某项工作不能减少用户提供答案的程度，就不要作为下一阶段优先级

---

## 问题 21：测试断言仍停留在“旧 demo 被删除”，与默认 quickstart 入口冲突

- 时间：2026-04-24
- 阶段：Agent MVP / Phase A+B 落地
- 状态：已解决

### 现象

在扩跑 `tests/unit/test_task_schema.py` 时，测试仍断言：

- `data/tasks/demos/success.json` 等 demo suite 文件存在
- `data/tasks/demo.json` 已被删除

但当前仓库实际保留的是默认 quickstart 文件：

```text
data/tasks/demo.json
```

这导致 schema 相关测试失败，与用户可复制 quickstart 的方向冲突。

### 根因

- 前一阶段曾经将 demo suite 作为主线，测试随之改成“旧单文件 demo 已删除”
- 后续用户可用 MVP 又恢复了 `data/tasks/demo.json`
- 测试没有跟随产品入口校准同步回到“默认 quickstart 必须存在”

### 解决方案

- 将测试改为断言 `data/tasks/demo.json` 存在
- 将 fixture 加载测试改回默认 quickstart demo
- 继续保留 fixed-flow 字段兼容测试，避免破坏旧执行层基线

### 后续约束

- 默认用户入口和测试断言必须保持一致
- 如果保留 `data/tasks/demo.json` 作为 quickstart，就不能再有测试断言它被删除
- 后续新增 Agent demo 时，应新增文件或命令，不应破坏默认 quickstart

---

## 问题 22：FastAPI TestClient 在当前依赖组合下卡住全量 pytest

- 时间：2026-04-24
- 阶段：Agent MVP / Phase A+B 最终验证
- 状态：已解决

### 现象

运行全量测试时，`python -m pytest -q` 长时间无输出。改用 `python -m pytest -vv` 后定位到卡点：

```text
tests/integration/test_api.py::test_healthz_returns_status_payload
```

单独运行该测试也会卡住。用 `faulthandler` 查看后，调用栈停在 Starlette `TestClient` 的 anyio portal 调度中。

### 根因

- 当前 FastAPI / Starlette / anyio / httpx 组合下，`TestClient(app).get("/healthz")` 在本地测试环境中会卡住
- 被测 API 逻辑本身很小，只是调用 `healthz()` 返回健康状态并关闭 docs/redoc/openapi
- 继续保留 TestClient 会让全量验证不可用，影响后续每轮收口

### 解决方案

- 将该测试从 `TestClient` 请求改为直接调用 `healthz()`
- 同时断言 `app.docs_url`、`app.redoc_url`、`app.openapi_url` 均为 `None`
- 保留对返回 payload 的核心契约断言

### 后续约束

- 如果后续要恢复真正 ASGI 请求级测试，应先升级或锁定兼容的测试依赖组合
- 不要让单个框架测试工具卡住全量 pytest
- API smoke 的优先级是稳定验证核心契约，而不是强行依赖某个客户端实现

---

## 问题 23：旧文档同时维护 CLI-first、fixed-flow 和 TUI 方向，造成路线冲突

- 时间：2026-04-24
- 阶段：TUI 产品形态校准
- 状态：已解决

### 现象

最新产品方案已经确定 MendCode 的最终入口是：

```bash
mendcode
```

也就是进入 TUI 后通过自然语言和 Agent 交互。但旧文档中仍保留大量过时表述：

- `mendcode fix --test` 被描述为主要用户入口
- fixed-flow demo 被描述为下一阶段主线
- batch eval / demo suite 被描述为近期优先级
- Web UI / 多 Agent 等旧暂缓项和 TUI 主线混杂

这些表述会让后续开发重新偏向 CLI 工具或 fixed-flow runner，而不是 TUI Code Agent。

### 根因

- 项目路线多次演进，文档采用追加方式，旧章节没有及时删除
- `mendcode fix --test` 是必要过渡切片，但被旧文档误写成主产品形态
- 缺少“所有产品判断以 TUI 产品方案为准”的文档层级约束

### 解决方案

- 重写 `MendCode_开发方案.md`
- 重写 `MendCode_全局路线图.md`
- 将 `MendCode_可演示可体验版本开发方案.md` 的有效内容并入 TUI 产品方案和开发方案后删除该独立文件
- 更新 README，将 CLI 命令明确标记为过渡能力和兼容能力
- 保留 `MendCode_TUI产品基调与交互方案.md` 作为最高优先级产品规格

### 后续约束

- 如果其它文档与 `MendCode_TUI产品基调与交互方案.md` 冲突，以 TUI 产品方案为准
- 不再把 `mendcode fix --test` 扩展成最终产品
- 不再把 `old_text/new_text` 或 fixed-flow demo 作为主线
- 后续每次路线变化都要删除过时内容，而不是只追加新章节

---

## 问题 24：独立“可演示可体验版本”文档与 TUI 产品方案重复，增加维护成本

- 时间：2026-04-24
- 阶段：文档体系简化
- 状态：已解决

### 现象

`MendCode_可演示可体验版本开发方案.md` 的内容已经基本被最新 TUI 产品方案覆盖，包括：

- TUI 演示剧本
- MVP 必须具备能力
- MVP 不做事项
- 验收标准
- 下一步开发顺序

继续保留该独立文件会让根目录文档变多，也会制造重复维护问题。

### 根因

- 该文档最初用于从 CLI fixed-flow 过渡到 Agent MVP
- 最新产品方案已经升级为 TUI 聊天式 Code Agent，并承担了产品规格职责
- 演示边界应属于 TUI 产品方案和开发方案的一部分，而不是单独成文档

### 解决方案

- 将演示剧本和验收标准并入 `MendCode_TUI产品基调与交互方案.md`
- 将 TUI MVP 验收要求补入 `MendCode_开发方案.md`
- 删除 `MendCode_可演示可体验版本开发方案.md`

### 后续约束

- 根目录只保留必要的长期文档
- 新增文档前先判断是否可以并入现有产品方案、开发方案、路线图或问题记录
- 避免多个文档描述同一条路线，导致后续更新遗漏

---

## 问题 25：如果不先定义统一 Action 协议，后续 Provider 和工具执行会耦合到厂商格式

- 时间：2026-04-24
- 阶段：TUI Agent / Phase A Action 协议
- 状态：已解决

### 现象

最新产品方案要求同时支持 OpenAI、Anthropic 和 OpenAI-compatible。不同 provider 的 tool calling / tool use / JSON 输出格式并不一致。如果业务层直接消费厂商格式，后续 Agent loop、Permission Gate 和 Tool Executor 都会被 provider 细节污染。

### 根因

- OpenAI 与 Anthropic 的工具调用协议不同
- OpenAI-compatible 国产模型不一定稳定支持原生 tool calling，可能只能用 JSON 文本协议
- 如果没有内部统一协议，就无法稳定实现权限判断、trace、降级和工具执行

### 解决方案

- 新增 `MendCodeAction` 统一动作协议
- 新增 `Observation` 统一观察结果协议
- 使用 discriminator 区分 `assistant_message`、`tool_call`、`patch_proposal`、`user_confirmation_request`、`final_response`
- 对工具名使用白名单类型，未知工具在 schema 层拒绝
- 提供 `build_invalid_action_observation` 将非法 action 转为 rejected observation
- 验证 action 和 observation 都能序列化进入 trace payload

### 后续约束

- Provider adapter 只能输出 MendCode Action，不应把厂商 tool calling 格式泄漏到业务层
- Permission Gate 只判断 MendCode Action
- Tool Executor 只消费已校验的 action
- 任何新增 action 类型都必须先补 schema 和测试

---

## 问题 26：权限模式如果只停留在产品文档，动态工具调用会缺少可执行安全边界

- 时间：2026-04-24
- 阶段：TUI Agent / Phase B Permission Gate
- 状态：已解决

### 现象

TUI 产品方案已经定义 Safe / Guided / Full / Custom，但如果代码中没有对应的 Permission Gate，后续 LLM Action loop 会直接执行模型请求的工具。这样模型一旦请求中高风险动作，系统无法稳定决定允许、拒绝还是请求用户确认。

### 根因

- 产品权限模式需要工程化成明确决策函数
- 工具调用必须先经过风险分级，再进入 Tool Executor
- 用户确认也应统一表达为 action，而不是散落在 TUI 层

### 解决方案

- 新增 `app/agent/permission.py`
- 定义 `PermissionMode` 与 `PermissionDecision`
- 建立首批工具风险等级
- 实现 `decide_permission`
- 实现 `build_confirmation_request`
- 用单测锁住 Safe / Guided / Full / Custom 的默认行为

### 后续约束

- Agent loop 执行工具前必须先调用 Permission Gate
- 新增工具时必须同步定义风险等级和权限测试
- TUI 只负责展示确认请求，不应自行判断权限
- 主工作区 apply、commit、push 等高风险动作必须单独建模，不能混入 worktree patch

---

## 问题 27：历史 worktree 分支落后于最新 TUI 主线，直接合并会覆盖当前产品方向

- 时间：2026-04-24
- 阶段：历史分支回收与主线校准
- 状态：部分解决

### 现象

检查 worktree 时发现 `phase-2c-tool-policy-state` 分支仍有多笔提交未并入 `main`，包括 fixed-flow 工具权限、batch eval、demo suite 等内容。但该分支基于较旧路线，直接比较显示它还会删除或覆盖当前最新 TUI 方向文档、pytest failure parser 和 Agent MVP 相关改动。

### 根因

- 分支开发期间产品路线已经从 CLI/fixed-flow 转向 TUI Code Agent
- 历史分支中既有仍然有价值的底座能力，也有已经降级的旧路线文档
- 当前环境的 `.git` 元数据不可写，无法在会话内执行真正的 `git merge` / `commit`

### 解决方案

- 不做盲目 `git merge`
- 按文件级别选择性迁入仍有价值的实现：
  - `data/evals/` 配置与 batch eval runner
  - eval schema 和单测
  - fixed-flow runner 的 `allowed_tools` 检查
  - 更精确的 runner `current_step`
  - demo task suite 和 Python unit-fix fixture
- 保留最新 TUI 产品方案、开发方案和路线图作为主线
- 将 eval/demo 明确降级为辅助回归能力，不重新提升为产品主线

### 后续约束

- 历史 worktree 合并前必须先判断它是否落后于最新产品路线
- 对“代码有价值但文档路线过期”的分支，优先选择性迁移代码，不直接合并整棵分支
- 如果 `.git` 元数据不可写，只能完成工作区级迁移和验证，最终 commit / branch cleanup 需要在本地可写 Git 环境中执行

---

## 问题 28：patch 后立即复跑 Python 验证可能命中旧 `__pycache__`，造成假失败

- 时间：2026-04-25
- 阶段：Provider prompt repair contract / fake repair chain
- 状态：已解决

### 现象

fake provider 修复链路中，第一次验证在 worktree 中导入 `calculator.py` 并失败。随后 Agent 应用 patch，把 `return a - b` 改为 `return a + b`，但立即复跑同一个 Python 验证命令时仍然失败。

直接检查 worktree 文件内容时，源码已经正确更新，但验证仍像在执行旧实现。

### 根因

- 第一次验证生成了 `__pycache__`
- patch 与第二次验证发生得很快，源码 mtime 与 pyc 缓存判断存在同秒级边界
- Python 可能复用旧字节码，导致验证没有加载 patched source
- 旧 final gate 只检查最后一个非 final observation，`show_diff` 成功会掩盖 patch 后验证失败

### 解决方案

- 在 `patch_proposal` 成功应用后，清理 worktree 内的 `__pycache__`
- 加强 final response gate：如果本轮存在 patch proposal，`completed` 必须要求 patch 之后至少有一次成功的 `run_command`
- 新增 fake repair-chain 集成测试，覆盖：
  - patch 后验证通过才能 completed
  - patch 后验证失败不能被后续 `show_diff` 掩盖

### 后续约束

- 任何 patch 后验证链路都不能只看最后一个 observation
- 涉及 Python 源码 patch 的验证链路要考虑字节码缓存影响
- 如果后续新增其它语言或构建系统的缓存副作用，应在 worktree patch 后或 verification 前建立对应清理策略

---

## 问题 29：真实 OpenAI-compatible 模型输出会偏离严格 JSON Action 合约

- 时间：2026-04-25
- 阶段：Minimax provider smoke / TUI single-turn entry
- 状态：已解决

### 现象

接入 Minimax 后，低层 chat-completions 请求可以成功返回内容，但 MendCode provider smoke 初次失败：

- 模型会在 JSON 前输出 `<think>...</think>`
- 模型把 action discriminator 写成 `action_type`
- no-argument TUI 初版只展示通用 review，没有像 `fix` 入口一样展示 pytest `failed_node` 和 location steps

### 根因

- 当前 OpenAI-compatible adapter 只接受整段内容就是 JSON object 或单个 fenced JSON
- provider prompt 虽然说“valid MendCodeAction”，但没有给出最小合法字段示例，真实模型容易套用自创字段名
- TUI-shaped 入口复用了 `AgentSession.run_turn()` 后，遗漏了过渡 `fix` 入口中已经沉淀的 failure insight 和失败位置定位展示

### 解决方案

- 将 `minimax` 作为 `openai-compatible` 的显式 provider alias
- 在 JSON 提取失败时，从响应文本中提取第一个可解析 JSON object，兼容 reasoning preamble
- 在 provider prompt contract 中加入 `"type"` discriminator 示例，并明确不要使用 `action_type`
- 新增 `AgentSession.run_turn()` 与 `session.turns`，作为 TUI-facing 业务边界
- no-argument `mendcode` 入口补充 Tool Summary、Review、Failure Insight 和 location steps 展示
- `Tool Summary` 只展示 `tool_call`，避免把 `final_response` 混入工具摘要

### 后续约束

- 真实 provider smoke 要区分“接口不可用”和“接口可用但输出不符合 MendCode Action schema”
- OpenAI-compatible provider 不应为每个厂商写业务逻辑，优先通过 alias、prompt contract 和通用 JSON 提取增强兼容性
- TUI 入口必须复用 session 层和已有 failure insight 能力，不应重新绕过业务层直接解释 loop steps
- 文档中的 API 示例必须随 `AgentSession` 实际接口同步更新

---

## 问题 30：普通 shell 查询如果复用 verification executor，会破坏验证命令语义

- 时间：2026-04-26
- 阶段：TUI 自然语言 shell 工具调用
- 状态：已解决

### 现象

TUI 需要支持用户直接输入：

```text
ls
列一下当前目录
git status
```

这类请求应在聊天流中展示命令结果，而不是进入修复流程。但如果直接复用现有 `run_command` / verification executor，就会产生两个问题：

- 普通诊断命令和“证明修复结果”的验证命令混在一起
- Agent loop 里模型可能绕过声明的 verification command，随意调用 `run_command`

实现过程中还暴露出一个意图优先级问题：`pytest 失败了，帮我修复` 这类以命令名开头的自然语言修复请求，容易被误判成普通 shell。

### 根因

- verification executor 的核心语义是“只允许已声明的验证命令”，不适合承载通用 shell
- 普通 shell 需要自己的风险分级、确认状态和输出截断规则
- shell intent 如果优先于 fix intent，会把“命令名 + 修复描述”的中文请求误路由

### 解决方案

- 新增独立 `app/workspace/shell_policy.py`
- 新增独立 `app/workspace/shell_executor.py`
- TUI intent 从 `chat/fix` 扩展为 `chat/fix/shell`
- 规则层先判断 fix intent，再判断 shell intent，避免 `pytest 失败了` 被误判
- TUI 新增 `pending_shell` 状态：
  - 低风险查询自动执行
  - 写入、安装、联网、Git commit/push 等命令先确认
  - 明确破坏性命令保守拒绝
- Agent loop 新增 `run_shell_command`
- `run_command` 收敛为只执行 `verification_commands` 中声明过的命令

### 后续约束

- 不要把普通 shell 能力继续塞回 verification executor
- 新增 shell 允许项时，必须同时补 shell policy 单测和 TUI 行为测试
- 新增 Agent 工具时，必须同步更新 action schema、permission risk、prompt contract 和 loop 测试
- fix intent 应优先于 direct shell intent，避免“pytest 失败”“git status 报错”等修复请求被误判成 shell 查询

---

## 问题 31：TUI 对话如果不落盘，真实模型问题很难复盘

- 时间：2026-04-26
- 阶段：TUI 对话日志与自然语言工具调用调试
- 状态：已解决

### 现象

用户在 TUI 中发现 MendCode 没有按预期自主调用工具，而是在普通聊天里编造目录内容。最初只能依赖终端画面和用户描述判断，无法稳定还原：

- 用户原始输入
- intent 分类结果
- 是否进入 AgentLoop
- 工具调用步骤
- provider 最终返回内容
- TUI 展示给用户的实际文本

### 根因

- TUI 之前只把对话展示在界面里，没有按轮次写入本地持久化文件
- Agent trace 只覆盖 AgentLoop 内部，不能完整覆盖 intent、chat responder、shell responder 和用户消息
- 当问题发生在“进入 AgentLoop 之前”时，只有 trace 不够定位根因

### 解决方案

- 新增 `app/tui/conversation_log.py`
- 每次 TUI 会话写入 `data/conversations/` 下的 Markdown 和 JSONL
- 记录用户消息、系统消息、intent event、chat_result、tool_result、shell_result 等关键事件
- 将 `data/` 加入 `.gitignore`，避免本地对话和 trace 污染 Git 工作树
- 用单测覆盖 conversation log 的 Markdown / JSONL 输出和 TUI 写入行为

### 后续约束

- 后续排查 TUI 真实模型行为时，优先查看 `data/conversations/*.md` 和对应 trace
- 用户可见的“编造事实”“未调用工具”“工具结果丢失”都应先从日志确认实际路径
- 新增 TUI 分支路径时，必须同步写 conversation event，否则后续无法复盘

---

## 问题 32：OpenAI-compatible intent 分类会覆盖规则识别出的工具请求，导致模型编造本地事实

- 时间：2026-04-26
- 阶段：TUI 自然语言工具请求
- 状态：已解决

### 现象

用户输入：

```text
请查看当前文件夹下有哪些文件
```

MendCode 没有调用工具，而是进入普通 chat responder，并编造了类似 `.bashrc`、`.profile`、`project` 等并不存在于当前仓库根目录的内容。

对话日志显示该轮事件是：

```text
kind: chat
source: model
```

没有 `tool_result`，说明问题不是工具执行失败，而是请求被路由到了无工具聊天路径。

### 根因

- `RuleBasedIntentRouter` 已经能把“查看当前文件夹下有哪些文件”识别为 `tool`
- 但 `OpenAICompatibleIntentRouter` 当时只短路保留 `fix` 和 `shell`
- 规则识别出的 `tool` 会继续交给模型做 intent 分类
- 模型一旦返回 `chat`，TUI 就进入没有工具绑定的普通聊天 responder
- chat prompt 虽然要求“不要声称运行工具”，但真实模型仍可能忽略约束并编造本地结果

### 解决方案

- `OpenAICompatibleIntentRouter` 对规则识别出的 `tool` 也直接返回，不再让模型覆盖
- 增加回归测试：`请查看当前文件夹下有哪些文件` 必须保持 `tool`，且不调用模型分类
- 后续又扩展规则：文档内容类问题也进入 `tool`，例如 `mendcode开发方案的第一句话是什么`

### 后续约束

- 对本地文件、目录、代码、Git 状态相关请求，规则层一旦能确定是工具请求，就不应再交给模型改判为 chat
- 普通 chat responder 不能被用来回答需要本地事实的问题
- 新增自然语言工具入口时，要同时补 rule router 和 OpenAI-compatible router 的覆盖测试

---

## 问题 33：native tool 调用失败后，如果 final gate 只看最后状态，可能错误标记 completed

- 时间：2026-04-26
- 阶段：AgentLoop native tool calling / final response gate
- 状态：已解决

### 现象

AgentLoop 支持 OpenAI native tool call 后，模型可以连续发起 `read_file`、`list_dir`、`search_code` 等工具调用。但如果前面某个 native tool observation 已经失败或被拒绝，模型后续仍可能返回：

```json
{"type": "final_response", "status": "completed", "summary": "done"}
```

如果 final gate 不检查完整 observation 序列，就可能把包含失败工具调用的回合错误标记为 completed。

### 根因

- JSON action 路径和 native tool call 路径进入 AgentLoop 的方式不同
- 早期 final gate 对 native tool observation 的失败传播覆盖不足
- 一些工具注册和 action schema 处于过渡期，`search_code` 等工具需要同时兼容 JSON action 与 native tool invocation

### 解决方案

- 加强 AgentLoop final response gate：`completed` 前检查本轮 meaningful observations
- native tool 的 failed / rejected observation 会阻止 completed final response
- 补充 native tool invocation 相关测试：
  - native search_code 可执行
  - 多个 native tool invocation 可顺序执行
  - unknown native tool 会 rejected
  - native failed observation 会阻止 completed
  - patch 之后的 verification gate 不会被后续成功步骤掩盖
- 同步工具注册，保证 `search_code` 等工具在 registry 中可被 native tool path 找到

### 后续约束

- AgentLoop 的完成状态必须由 observation 证据决定，不能只信任模型的 final_response
- native tool call 与 JSON action 进入同一权限、执行、trace 和 final gate 体系
- 新增工具时，要同时覆盖 JSON action path 和 native tool path

---

## 问题 34：工具已经拿到有效结果后，模型重复调用工具并用普通文本收尾，会导致 TUI 显示失败或继续编造

- 时间：2026-04-26
- 阶段：TUI 自然语言工具请求 / OpenAI-compatible native tool calling
- 状态：已解决

### 现象

用户输入：

```text
帮我查看当前文件夹内有哪些文件
```

日志显示 MendCode 已经成功进入 `tool` 路径，并拿到了有效目录结果，但模型连续请求了多次等价工具：

- `list_dir {"path": "."}`
- `list_dir {"path": ".", "max_entries": 50}`
- `list_dir {"path": ".", "max_entries": 100}`
- `run_shell_command {"command": "ls -la"}`

最后模型没有返回合法 MendCode `final_response` JSON，provider 报：

```text
Provider returned invalid MendCode action
```

同一轮后续用户又问：

```text
mendcode开发方案的第一句话是什么
```

该请求被分到普通 `chat`，模型没有读取文件，却编造了 `docs/mendcode-dev-plan.md` 和不存在的正文内容。

### 根因

- `list_dir` 的真实 observation 中 `truncated=false`，但传回模型的 prompt context 仍只保留前 8 条 entries
- 模型看到的上下文像是“目录可能没列完”，于是重复扩大 `max_entries`
- prompt contract 没有明确告诉模型：`truncated=false` 代表当前 entries 已完整，不要重复 list_dir
- OpenAI-compatible provider 对“工具调用之后的普通文本回答”过于严格，只接受合法 JSON Action
- 文件内容类问题没有规则路由到 `tool`，导致普通 chat responder 直接回答本地事实问题

### 解决方案

- prompt context 在 `list_dir` 返回 `truncated=false` 时保留完整 entries
- system prompt 明确要求：
  - `truncated=false` 时不要重复对同一路径调用 `list_dir`
  - observation 足够回答用户时返回 `final_response`
- OpenAI-compatible provider 在已有 observation 后，如果模型返回普通文本，会包装成 `final_response`
- 新增 `looks_like_file_content_request`，让文档内容类自然语言问题进入 `tool`
- 增加回归测试覆盖：
  - 未截断目录 entries 完整传给模型
  - 工具 observation 后普通文本可安全收尾
  - 文档第一句话类问题进入 `tool`

### 后续约束

- 工具 observation 传给模型时，不能丢失会影响模型决策的完整性信号
- 对工具后收尾要兼容真实模型的普通文本输出，但不能在没有 observation 时放宽 JSON Action 合约
- 文件内容、目录内容、代码内容、Git 状态等本地事实问题必须走工具路径
- 后续如果仍出现重复工具调用，应考虑在 AgentLoop 层增加“等价只读工具调用去重”保护，而不只依赖 prompt

---

## 问题 35：工具表面过宽和权限风险表漂移，会让只读请求暴露写入能力

- 时间：2026-04-26
- 阶段：OpenAI-compatible scoped tools / Permission Gate
- 状态：已解决

### 现象

自然语言工具请求已经能进入 AgentLoop，但 provider 默认会收到完整 ToolRegistry schema。对于“帮我查看当前文件夹里的文件”这类只读请求，模型理论上仍能看到 `apply_patch`、`run_shell_command`、`run_command` 等不需要的工具。

同时，权限风险等级曾在 `app/agent/permission.py` 中单独维护一份硬编码表，而 ToolRegistry 中也有 `risk_level`。新增或调整工具时，两处定义容易不一致。

### 根因

- ToolRegistry 只有“全部 tools schema”输出，没有按场景裁剪的 `allowed_tools`
- OpenAI-compatible provider 没有把当前场景工具集传给 tools schema
- AgentLoop 没有在执行 native tool invocation 前二次检查当前工具是否被允许
- Permission Gate 的风险来源没有复用 ToolRegistry

### 解决方案

- ToolRegistry 增加 `allowed_tools` 过滤和常用别名归一，例如 `read`、`glob`、`grep`
- `AgentLoopInput` / `AgentProviderStepInput` 增加 `allowed_tools`
- OpenAI-compatible provider 按 `allowed_tools` 发送裁剪后的 tools schema，并拒绝模型返回的越权工具
- AgentLoop 在执行 native tool invocation 前再次检查 `allowed_tools`
- TUI 自然语言工具请求默认只开放只读工具：`list_dir` / `read_file` / `glob_file_search` / `rg` / `search_code` / `git`
- Permission Gate 改为从 ToolRegistry 派生风险等级，`run_shell_command` 等 restricted shell 工具在 Safe 模式下按中风险确认

### 后续约束

- 任何面向模型暴露的工具集都必须经过场景级 `allowed_tools` 裁剪
- AgentLoop 不能只信任 provider；执行前仍要做工具允许检查
- 新增工具时优先在 ToolRegistry 定义风险等级，再由 Permission Gate 派生
- 只读自然语言请求不得暴露写入、验证、安装、网络或任意 shell 工具
