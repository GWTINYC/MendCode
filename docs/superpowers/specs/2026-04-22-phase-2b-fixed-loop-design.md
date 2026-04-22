# MendCode Phase 2B Fixed-Flow Loop Design

## 1. 背景

截至 2026-04-22，MendCode 已经具备三层基础能力：

- 运行骨架：`task run`、`RunState`、`TraceEvent`、CLI / API 基线
- 执行边界：command policy、executor、worktree manager、verification trace
- 基础工具：`read_file`、`search_code`、最小 `apply_patch`

但系统仍然没有形成真正的“最小修复 Agent”闭环。当前 `run_task_preview()` 只会：

1. 准备 worktree
2. 执行 verification
3. 输出 summary 和 trace

也就是说，工具层已经存在，但还没有进入 orchestrator 的执行流。项目当前最短路径不是继续扩工具能力，也不是先做更重的上下文平台，而是先把现有工具接入一条固定流程的最小 loop。

---

## 2. 目标

本轮只解决一个很窄的目标：

让 `task run` 从“只会跑 verification”升级为“能在固定流程中完成一次最小 `读 -> 搜 -> 改 -> 验`”。

完成后，MendCode 应至少能在一条窄范围 demo 任务上完成一次真实修复尝试。

---

## 3. 非目标

本轮明确不做：

- 不引入模型决策或 planner
- 不实现开放式工具调用循环
- 不先做 repo map / 日志蒸馏 / 文件选择平台
- 不扩 `apply_patch` 为通用 unified diff 引擎
- 不引入恢复策略、重试策略或多轮定位
- 不新增大量任务类型

本轮只做“固定流程版最小 loop”。

---

## 4. 方案选择

### 4.1 方案一：固定流程版 loop

做法：

- 用规则化固定步骤执行工具
- 不做运行时决策
- 只支持结构化输入完整给出的窄范围 demo 任务

优点：

- 最短路径接入现有工具层
- 最容易拿到第一条真实闭环
- 对当前 `runner` 侵入最小

缺点：

- 适用任务范围很窄
- 后续还需要继续补上下文能力

结论：

- 推荐，采用该方案

### 4.2 方案二：半固定流程，允许按中间结果跳步

做法：

- 仍保持固定步骤，但允许在执行中根据中间结果选择跳过某些工具

问题：

- 虽然看起来不复杂，但本质上已经开始引入局部决策
- 当前阶段会增加分支复杂度，却不一定更快拿到第一条真实闭环

结论：

- 当前不采用

### 4.3 方案三：最小规则 planner

做法：

- 引入一个轻量 action planner，根据状态决定下一步调用哪个工具

问题：

- 这会提前把“固定流程接线”升级成“决策系统设计”
- 当前阶段收益不足，复杂度上升明显

结论：

- 明确不采用

---

## 5. 设计结论

### 5.1 本轮采用固定主链

本轮执行流固定为：

1. `bootstrap`
2. `locate`
3. `inspect`
4. `patch`
5. `verify`
6. `summarize`

其中：

- `locate` 调 `search_code`
- `inspect` 调 `read_file`
- `patch` 调最小 `apply_patch`
- `verify` 复用现有 verification 主链

### 5.2 先支持“结构化输入完整给出”的 demo 任务

本轮不尝试从自然语言任务描述中推理修复方案。

相反，任务输入必须直接提供 runner 所需的最小结构化信息，让系统先证明“这条闭环能跑通”，而不是证明“它已经足够聪明”。

---

## 6. 输入约束

### 6.1 保持 `TaskSpec` 顶层结构不变

当前不改 `TaskSpec` 的顶层字段结构，继续通过 `entry_artifacts` 承载本轮固定流程所需的输入。

### 6.2 本轮约定的最小 `entry_artifacts`

建议约定以下字段：

- `search_query: str | None`
- `target_path_glob: str | None`
- `read_target_path: str | None`
- `read_start_line: int | None`
- `read_end_line: int | None`
- `old_text: str`
- `new_text: str`
- `expected_verification_hint: str | None`

### 6.3 字段使用规则

- `read_target_path` 和 `search_query` 至少要有一个
- 如果给了 `read_target_path`，则优先直接读取该文件，不依赖搜索结果选路
- 只有在未给 `read_target_path` 时，才要求 `search_query` 非空
- 若需要定位文件，则先用 `search_query` 和可选 `target_path_glob` 调 `search_code`
- 若搜索结果为 1 个候选文件，则继续进入 `inspect`
- 若搜索结果为 0 个或多个候选文件，则本轮直接失败
- `old_text` / `new_text` 直接传给 `apply_patch`

---

## 7. Runner 设计

### 7.1 继续复用 `run_task_preview()`

本轮不新建另一套 orchestrator 入口，而是在当前 `run_task_preview()` 基础上扩为固定流程执行器。

原因：

- 当前 runner 已经具备 worktree、trace、verification 和 summary 主链
- 本轮只是在这个骨架上加工具调用步骤
- 不值得为此再起一套并行入口

### 7.2 固定执行顺序

runner 采用线性固定流程，不做循环：

1. `bootstrap`
   - 准备 worktree
   - 初始化 trace
   - 读取任务输入

2. `locate`
   - 根据 `entry_artifacts` 决定直接读文件还是先搜索
   - 若需要搜索，则调用 `search_code`

3. `inspect`
   - 调 `read_file`
   - 读取候选文件的有限上下文

4. `patch`
   - 调 `apply_patch`
   - 只使用现有最小文本替换能力

5. `verify`
   - 复用现有 `verification_commands`

6. `summarize`
   - 汇总工具结果、verification 结果和最终状态

### 7.3 失败策略

本轮保持硬边界：

- `search_code` 0 个结果：直接失败
- `search_code` 多个结果：直接失败
- `read_file` rejected / failed：直接失败
- `apply_patch` rejected / failed：直接失败
- verification 失败：run 失败

本轮不做：

- 重试
- 二次搜索
- 回退补丁
- 恢复策略

---

## 8. Run State 设计

### 8.1 步骤枚举扩展

建议把当前 `RunState.current_step` 扩为：

- `bootstrap`
- `locate`
- `inspect`
- `patch`
- `verify`
- `summarize`

### 8.2 新增最小执行结果字段

建议补充：

```python
selected_files: list[str] = []
applied_patch: bool = False
tool_results: list[dict[str, Any]] = []
```

约束：

- `selected_files` 只存当前执行中实际选中的文件路径
- `applied_patch` 只表示本轮是否真的成功修改了文件
- `tool_results` 只存精简摘要，不承载大块文件内容

目的：

- 让 `RunState` 足以表达最小 loop 结果
- 避免所有信息都只能去 trace 里找
- 同时避免把 `RunState` 做成大 payload 容器

---

## 9. Trace 设计

### 9.1 事件类型

本轮只新增最小一组工具事件：

- `run.tool.started`
- `run.tool.completed`

### 9.2 统一记录字段

每次工具调用统一记录：

- `tool_name`
- `status`
- `summary`
- `workspace_path`
- 精简后的 `payload`
- 必要时的 `error_message`

### 9.3 设计原则

- trace 要能回放工具调用顺序
- 不要求在本轮就形成复杂 taxonomy
- 不在 trace 里塞完整文件内容
- 后续 eval 和失败诊断应直接复用这层事件格式

---

## 10. Demo 任务约束

本轮至少准备 1 条窄范围 demo 任务。

这条任务必须具备：

- 结构化 `entry_artifacts`
- 明确的 `read_target_path` 或 `search_query`
- 明确的 `old_text` / `new_text`
- 可复现的 verification command

本轮 demo 的目的不是证明系统“聪明”，而是证明系统“闭环已打通”。

---

## 11. 测试策略

### 11.1 Runner 单测

至少覆盖：

- 成功路径：`search_code -> read_file -> apply_patch -> verify`
- 搜索无结果：直接失败
- 搜索多结果：直接失败
- `read_file` 失败：直接失败
- `apply_patch` 失败：直接失败
- verification 失败：前序工具成功但 run 最终失败
- trace 顺序正确
- `RunState.current_step`、`selected_files`、`applied_patch`、`workspace_path` 与真实执行一致

### 11.2 工具接线测试

重点验证 runner 调工具时的参数契约：

- `search_code` 是否收到正确的 `workspace_path/query/glob`
- `read_file` 是否读取选中的目标文件
- `apply_patch` 是否使用 `old_text/new_text`
- verification 是否仍在 worktree 中执行

### 11.3 端到端 demo 测试

准备一个极小 repo fixture，验证：

- runner 能在 worktree 中修改真实文件
- verification 能基于修改后的文件通过
- trace 和 summary 与真实执行一致

---

## 12. 验收标准

本轮完成的标准是：

1. `task run` 不再只做 verification
2. 至少 1 条 demo 任务走通真实 `read -> search -> patch -> verify`
3. trace 可以回放工具调用过程
4. `RunState` 足以表达本轮固定流程的执行结果
5. 本轮没有引入 planner、恢复策略或重型上下文平台

---

## 13. 停手原则

这一刀的停手点必须非常明确：

- 第一条真实闭环跑通就停
- `apply_patch` 维持当前最小能力面，不继续扩引擎
- 不提前做 repo map / 日志蒸馏平台
- 不提前做开放式工具循环
- 不提前做“更聪明”的规划系统

换句话说：

本轮目标不是把 MendCode 变成完整 Agent，而是把它从“有工具的框架”推进成“会走通一条最小修复链路的系统”。

---

## 14. 后续顺序

本轮结束后，下一步顺序应为：

1. 用 demo 任务验证固定流程版 loop
2. 根据 demo 暴露的真实瓶颈，补最小上下文工程
3. 再进入 batch eval 和指标统计

不应在本轮结束后直接扩散到平台化能力。
