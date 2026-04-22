# MendCode Phase 1B Command Policy And Worktree Design

## 1. 背景

截至 2026-04-22，MendCode 已完成 Phase 1B 第一切片：

- `task run` 会真实执行 `TaskSpec.verification_commands`
- runner 会顺序汇总验证结果
- CLI 会展示 `passed_count` / `failed_count`
- trace 已覆盖 `run.started`、`run.verification.started`、`run.verification.command.completed`、`run.completed`

这说明系统已经从“只会演示状态流转”进入“可以真实执行验证命令”的阶段。但当前执行链仍有两个明显缺口：

1. 命令执行边界还不够清晰  
   现在的 runner 直接 `subprocess.run(...)`，虽然只执行任务文件里声明的命令，但还没有把“允许执行什么、在哪执行、失败如何分类、超时如何处理”沉淀成明确的策略层。

2. 工作区隔离还没有落地  
   当前验证命令直接在 `task.repo_path` 下执行。后续一旦接入 `read_file`、`apply_patch` 等会修改代码的能力，如果没有独立 worktree，真实仓库就会暴露给运行期副作用。

因此，Phase 1B 的下一阶段不能继续堆 CLI 表面能力，也不应该马上进入补丁生成链路，而应先把执行边界和工作区隔离补齐。

---

## 2. 目标

本设计只解决两个按顺序推进的目标：

### 2.1 第一段：收口 command policy

把当前“能执行命令”收敛为“在明确策略下受控执行命令”：

- 只允许执行 `TaskSpec.verification_commands`
- 执行目录必须是目标 repo 或其派生 worktree
- 单条命令具备基础超时
- 被策略拒绝、超时、普通非零退出码要能区分记录
- runner 不再直接负责命令策略判断

### 2.2 第二段：接入 worktree manager

把当前“直接在 repo 上执行”收敛为“在独立工作区执行”：

- 为单次 run 准备独立 worktree
- verification 命令在 worktree 路径下执行
- trace 和最终状态能暴露 `workspace_path`
- run 结束时记录 cleanup 结果

这两个目标完成后，MendCode 才具备继续接 `read_file`、`search_code`、`apply_patch` 的基础工程边界。

---

## 3. 非目标

本阶段明确不做：

- 不接入模型推理主循环扩展
- 不实现自动补丁生成
- 不做 Docker / 容器沙箱
- 不做复杂命令白名单 DSL
- 不做 worktree 池化或复用缓存
- 不做并行命令执行
- 不做多仓、多工作区调度

本阶段只做“受控执行边界”和“独立工作区准备”。

---

## 4. 设计结论

### 4.1 采用“小而清晰的执行边界拆分”

不继续把逻辑堆进 `app/orchestrator/runner.py`，而是在 `app/workspace/` 下新增一组薄模块：

- `command_policy.py`
- `executor.py`
- `worktree.py`

其中：

- runner 负责编排执行顺序和汇总状态
- command policy 负责判断命令和执行目录是否合法
- executor 负责执行单条命令并返回统一结果
- worktree manager 负责准备和清理独立工作区

这比“把所有逻辑都塞进 runner”更适合当前仓库规模，也能给后续工具层留下清晰挂载点。

### 4.2 分两刀推进，而不是一次性抽全工具层

顺序固定为：

1. 先实现 command policy + executor
2. 再在相同目录中接入 worktree manager

原因：

- 先收口执行边界，能避免 worktree 落地后仍然把危险行为包在更大的副作用里
- 先统一 executor 返回结果，worktree 接入时只需要切换执行目录，不需要重做 CLI、trace 和汇总逻辑
- 当前还没有补丁工具，没必要提前做完整 tool layer

---

## 5. 模块设计

### 5.1 `app/workspace/command_policy.py`

职责：

- 定义命令执行的最小策略边界
- 校验命令是否来自任务声明
- 校验执行目录是否位于允许的 repo / worktree 根下
- 提供统一的拒绝结果

建议结构：

```python
class CommandPolicyDecision(BaseModel):
    allowed: bool
    reason: str | None = None


class CommandPolicy(BaseModel):
    allowed_commands: list[str]
    allowed_root: Path
    timeout_seconds: int
```

最小规则：

- 命令必须精确命中 `TaskSpec.verification_commands`
- `cwd.resolve()` 必须位于 `allowed_root.resolve()` 之下
- timeout 使用固定配置，不允许任务文件自由覆盖

被拒绝时，executor 不真正执行命令，而是返回受控失败结果。

### 5.2 `app/workspace/executor.py`

职责：

- 接收命令、执行目录和 command policy
- 做策略校验
- 运行 `subprocess.run(...)`
- 统一返回执行结果

建议结果结构至少覆盖：

- `command`
- `status`
- `exit_code`
- `duration_ms`
- `stdout_excerpt`
- `stderr_excerpt`
- `timed_out`
- `rejected`
- `cwd`

状态建议细分为：

- `passed`
- `failed`
- `timed_out`
- `rejected`

其中：

- `failed` 表示命令已执行但退出码非零
- `timed_out` 表示命令被超时中止
- `rejected` 表示策略层拒绝执行，`subprocess.run(...)` 不应发生

### 5.3 `app/workspace/worktree.py`

职责：

- 为一次 run 准备独立工作区
- 受控调用 `git worktree add`
- 记录 cleanup 结果

初版行为：

- 输入：`repo_path`、`run_id`、`base_ref`
- 输出：`workspace_path`
- 若 `base_ref` 为空，则默认基于当前 HEAD
- worktree 目录建议落在项目内受控目录，例如 `.worktrees/<run_id>/`

初版 cleanup 策略：

- 成功 run 可配置清理
- 失败 run 默认保留现场
- 无论是否清理，都要把 cleanup 结果记入 trace

### 5.4 `app/orchestrator/runner.py`

职责调整为：

- 创建 `run_id`
- 准备 workspace
- 构造 command policy
- 调用 executor 顺序执行 `verification_commands`
- 汇总验证结果
- 记录 trace
- 返回最终 `RunState`

runner 不再自己：

- 直接做命令合法性判断
- 直接调用 `subprocess.run(...)`
- 推断工作区是否合法

### 5.5 `app/schemas/run_state.py`

建议新增或扩展字段：

- `workspace_path: str | None = None`

当前不必为了 cleanup 再扩一套复杂 schema，可先把 cleanup 结果放入 trace payload，待后续补丁链路接入时再评估是否进入 `RunState`。

---

## 6. 配置设计

建议在 `app/config/settings.py` 新增最小配置：

- `workspace_root`
- `verification_timeout_seconds`
- `cleanup_success_workspace`

建议默认值：

- `workspace_root = project_root / ".worktrees"`
- `verification_timeout_seconds = 60`
- `cleanup_success_workspace = False`

当前不建议把这些配置暴露为大量 CLI 参数，先以 settings 收口。

---

## 7. 数据流

下一阶段完整数据流建议为：

1. CLI 读取任务文件
2. CLI 读取 settings，确保 trace 目录与 workspace 根目录存在
3. runner 生成 `run_id`
4. runner 通过 worktree manager 准备 `workspace_path`
5. runner 写 `run.started`
6. runner 写 `run.verification.started`
7. runner 构造 command policy
8. runner 通过 executor 顺序执行 `verification_commands`
9. executor 为每条命令返回统一结果
10. runner 为每条命令写结果 trace
11. runner 汇总最终 `VerificationResult`
12. runner 写 cleanup trace
13. runner 写 `run.completed`
14. CLI 渲染最终摘要

---

## 8. Trace 设计

保留已有事件：

- `run.started`
- `run.verification.started`
- `run.verification.command.completed`
- `run.completed`

新增一类事件：

- `run.workspace.cleanup`

关键 payload 补充：

`run.started`

- `task_id`
- `task_type`
- `status`
- `workspace_path`

`run.verification.command.completed`

- `command`
- `status`
- `exit_code`
- `duration_ms`
- `stdout_excerpt`
- `stderr_excerpt`
- `timed_out`
- `rejected`
- `cwd`

`run.workspace.cleanup`

- `workspace_path`
- `cleanup_attempted`
- `cleanup_succeeded`
- `cleanup_reason`

这样可以区分：

- 命令真正执行失败
- 命令被策略拒绝
- 命令执行超时
- 任务结束后工作区是否被保留

---

## 9. 错误处理

### 9.1 command policy 拒绝

如果命令不在允许列表内，或 `cwd` 不在允许根目录内：

- 不执行命令
- 返回 `rejected`
- `exit_code` 记为 `-1`
- `stderr_excerpt` 写明拒绝原因
- 最终整体 verification 视为 `failed`

### 9.2 命令超时

如果命令超过 timeout：

- 杀掉命令
- 返回 `timed_out`
- `exit_code` 记为 `-1`
- `stderr_excerpt` 写明超时
- 最终整体 verification 视为 `failed`

### 9.3 worktree 创建失败

如果 worktree 准备失败：

- 不进入 verification 执行
- 直接写失败态 `run.completed`
- CLI 不崩溃，但退出非零

### 9.4 cleanup 失败

cleanup 失败不应覆盖主业务结论：

- 如果 verification 已通过，cleanup 失败仍应保留运行结果为 `completed`
- cleanup 错误单独写入 trace 和摘要附加信息

---

## 10. 测试策略

### 10.1 command policy / executor

单元测试应覆盖：

- 命令在允许列表内时可执行
- 命令不在允许列表内时被拒绝
- `cwd` 越界时被拒绝
- 超时命令返回 `timed_out`
- 输出裁剪继续生效

### 10.2 worktree manager

单元或轻集成测试应覆盖：

- 能在临时 git 仓库上创建 worktree
- 生成路径位于 `.worktrees/`
- cleanup 成功和失败路径都能记录

### 10.3 runner / CLI

集成测试应覆盖：

- `task run` 成功时输出 `workspace_path`
- verification 命令在 worktree 中执行，而不是直接在 repo 根执行
- 策略拒绝、超时、普通失败三种状态都能被正确汇总

---

## 11. 验收标准

本阶段完成的标准是：

- runner 不再直接 `subprocess.run(...)`
- 验证命令必须经过 command policy
- 每条命令有明确的 `passed / failed / timed_out / rejected` 语义
- 单次 run 能准备独立 worktree
- verification 命令默认在 worktree 内执行
- trace 能暴露 `workspace_path` 与 cleanup 结果
- README、根开发方案、问题记录同步更新

---

## 12. 后续衔接

本阶段完成后，下一优先级才是：

1. `read_file`
2. `search_code`
3. `apply_patch`

届时这些工具都应默认围绕 `workspace_path` 工作，而不是直接作用于 `task.repo_path`。

这也是为什么当前必须先完成 command policy 和 worktree manager，而不是直接进入补丁生成链路。
