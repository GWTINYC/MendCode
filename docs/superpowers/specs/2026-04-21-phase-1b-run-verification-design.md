# MendCode Phase 1B Run Verification Design

## 1. 背景

Phase 1A 已经完成最小运行骨架，当前仓库已经具备以下稳定能力：

- `TaskSpec`、`TraceEvent`、`RunState` 等基础 schema
- `TraceRecorder` 与 JSONL trace 输出
- `run_task_preview()` 最小 runner
- `task run` CLI 入口
- 对应的单元测试与集成测试

当前系统已经能完成：

`读取任务文件 -> 创建 RunState -> 记录开始/结束 trace -> 输出摘要`

但这条链路还没有真正执行任务中的 `verification_commands`，因此仍然属于“运行骨架”，而不是“真实执行链”。

Phase 1B 的第一刀应优先补上验证执行能力，而不是提前进入 worktree、补丁生成或复杂工具系统。原因很简单：只有先把验证命令真实跑起来，系统才算从“能演示状态流转”进入“能执行受控任务”的阶段。

## 2. 目标

本设计只交付一个最小 `run_verification` 闭环：

`读取任务文件 -> 启动 run -> 顺序执行 verification_commands -> 汇总结果 -> 写 trace -> 输出摘要`

完成后系统应具备以下能力：

- `task run` 会真实执行 `TaskSpec.verification_commands`
- runner 会按顺序收集每条命令的结果
- CLI 会展示整体验证结论与最小摘要
- trace 中会留下验证开始、单条命令结果、整体完成等事件

## 3. 非目标

本阶段明确不做：

- 不创建或切换 Git worktree
- 不读取或修改目标仓库代码
- 不接入 `read_file`、`search_code`、`apply_patch`
- 不做命令白名单系统
- 不做复杂超时、并行执行、沙箱或流式输出
- 不引入完整工具层抽象

这些都属于后续 Phase 1B 扩展项。当前只解决“真实执行 verification_commands”这一件事。

## 4. 设计原则

### 4.1 先打通真实执行链，再收紧执行壳

当前最缺的不是安全策略数量，而是让 runner 真正执行验证命令并产生可观察结果。先跑通，再逐步加白名单、超时和工作区隔离。

### 4.2 在现有 runner 上做最小演进

本阶段不引入独立工具层。验证命令执行逻辑直接放在 `app/orchestrator/runner.py` 内部，复用现有 runner 和 CLI 入口，避免把小问题过度工程化。

### 4.3 结果结构要小，但要能表达失败

验证结果 schema 只保留当前必需字段：命令、退出码、状态、耗时、输出摘要。先把“可观察”建立起来，再决定后续是否扩展原始输出存档。

### 4.4 失败是业务结果，不是程序崩溃

验证命令返回非零退出码是正常业务失败，runner 应记录并汇总，而不是让 CLI 直接崩溃退出。

### 4.5 输出先裁剪，避免 trace 膨胀

当前阶段只记录 `stdout` / `stderr` 摘要，不记录完整原始输出，避免 trace 快速失控。

## 5. 模块设计

### 5.1 `app/schemas/verification.py`

职责：

- 定义最小验证结果结构

建议新增两个 schema：

- `VerificationCommandResult`
- `VerificationResult`

建议字段：

`VerificationCommandResult`

- `command`
- `exit_code`
- `status`
- `duration_ms`
- `stdout_excerpt`
- `stderr_excerpt`

`VerificationResult`

- `status`
- `command_results`
- `passed_count`
- `failed_count`

约束：

- `VerificationCommandResult.status` 当前只需要 `passed`、`failed`
- `VerificationResult.status` 当前只需要 `passed`、`failed`

### 5.2 `app/schemas/run_state.py`

职责扩展：

- 继续作为 runner 对外输出的统一状态对象
- 增加最小验证结果挂载

建议新增字段：

- `verification: VerificationResult | None = None`

建议调整 `current_step` 允许值：

- `bootstrap`
- `verify`
- `summarize`

### 5.3 `app/orchestrator/runner.py`

职责演进：

- 从 preview runner 演进为最小真实执行 runner

仍保留现有对外函数名：

`run_task_preview(task: TaskSpec, traces_dir: Path) -> RunState`

这里函数名暂不调整，避免在本阶段引入额外改名成本。等后续 runner 稳定后，再评估是否统一命名为更准确的 `run_task`。

执行流建议为：

1. 生成 `run_id`
2. 写 `run.started`
3. 写 `run.verification.started`
4. 顺序执行 `task.verification_commands`
5. 每条命令执行后写一条结果事件
6. 汇总 `VerificationResult`
7. 构造最终 `RunState`
8. 写 `run.completed`
9. 返回 `RunState`

命令执行建议使用标准库：

```python
subprocess.run(..., capture_output=True, text=True)
```

当前不引入独立 shell 工具层。

### 5.4 `app/cli/main.py`

职责保持不变：

- 继续只做任务加载、调用 runner、打印摘要

输出建议扩展为：

- `run_id`
- `task_id`
- `task_type`
- `status`
- `current_step`
- `summary`
- `passed_count`
- `failed_count`
- `trace_path`

如果存在失败命令，可额外打印第一条失败命令及其退出码。

## 6. 数据流

`task run` 的完整数据流如下：

1. CLI 读取任务文件
2. CLI 读取 `settings` 并确保 trace 目录存在
3. CLI 调用 runner
4. runner 写 `run.started`
5. runner 写 `run.verification.started`
6. runner 顺序执行每条 `verification_commands`
7. runner 对每条命令记录结果事件
8. runner 汇总生成 `VerificationResult`
9. runner 写 `run.completed`
10. CLI 渲染最终摘要

这里保持同步执行，不做后台任务和异步模型。

## 7. Trace 事件设计

当前建议记录四类事件：

- `run.started`
- `run.verification.started`
- `run.verification.command.completed`
- `run.completed`

其中 `run.verification.command.completed` 每条命令写一条。

建议 payload 结构：

`run.verification.started`

- `task_id`
- `task_type`
- `command_count`

`run.verification.command.completed`

- `command`
- `exit_code`
- `status`
- `duration_ms`
- `stdout_excerpt`
- `stderr_excerpt`

`run.completed`

- `task_id`
- `task_type`
- `status`
- `summary`
- `passed_count`
- `failed_count`

## 8. 错误处理

### 8.1 空验证命令

如果 `verification_commands` 为空：

- runner 不应假装成功
- 直接返回 `failed`
- `summary` 写明 `no verification commands provided`
- 写入失败态 `run.completed`

### 8.2 命令执行失败

如果某条命令退出码非零：

- 记为该命令 `failed`
- 不视为程序异常
- 继续执行剩余命令
- 最终整体 `VerificationResult.status` 为 `failed`

### 8.3 运行期异常

如果 `subprocess.run(...)` 抛出 `OSError`：

- 将该命令结果记为 `failed`
- `exit_code` 可记为 `-1`
- 在 `stderr_excerpt` 中写入异常信息
- 继续汇总整体结果

CLI 只在更基础的 trace 写入失败这类问题上退出非零；验证失败本身不应变成 CLI 崩溃。

## 9. 输出裁剪

为避免 trace 膨胀，当前阶段采用固定裁剪规则：

- `stdout_excerpt` 最多保留前 `2000` 个字符
- `stderr_excerpt` 最多保留前 `2000` 个字符

当前不额外落盘完整原始输出。

## 10. 测试策略

### 10.1 单元测试

新增：

- `tests/unit/test_verification_schema.py`

覆盖：

- 验证结果 schema 的基本序列化
- 无效状态值拒绝

扩展：

- `tests/unit/test_runner.py`

覆盖：

- 全部命令通过时整体 `passed`
- 存在失败命令时整体 `failed`
- 空 `verification_commands` 时整体 `failed`
- 输出会被裁剪
- `OSError` 会被转成失败结果而不是直接崩溃

### 10.2 集成测试

扩展：

- `tests/integration/test_cli.py`

覆盖：

- `task run` 会真实执行验证命令
- 全部成功时输出通过摘要
- 存在失败时输出失败摘要
- trace 中包含验证相关事件

## 11. 验收标准

这一刀完成的标准是：

- `task run` 会真实执行 `verification_commands`
- 所有命令成功时，CLI 输出整体通过
- 任一命令失败时，CLI 输出整体失败
- trace 中能看到：
  - `run.started`
  - `run.verification.started`
  - 每条命令结果事件
  - `run.completed`
- 全量测试继续通过

## 12. 后续衔接

这一刀完成后，下一步优先顺序建议为：

1. 为 `run_verification` 加白名单与基础超时控制
2. 引入 workspace / worktree 管理
3. 再接入 `read_file`、`search_code`、`apply_patch`

这样可以继续保持“小步打通真实链路”的节奏，不在同一轮里同时解决执行、安全、隔离和补丁生成四类问题。
