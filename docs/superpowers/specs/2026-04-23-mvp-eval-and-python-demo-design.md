# MendCode MVP Eval and Python Demo Design

## 1. 背景

截至 2026-04-23，MendCode 已具备一条可运行的固定流原型：

- 结构化 `TaskSpec`
- worktree 隔离执行
- `read_file / search_code / apply_patch / verify` 最小工具链
- CLI `task run`
- 4 条 repo-native 机制 demo：
  - `success`
  - `unauthorized-tool`
  - `ambiguous-search`
  - `verification-fail`

当前真正缺的不是更多能力面，而是两个直接影响 MVP 成立的问题：

1. 还没有 batch eval，无法稳定比较一组任务的结果
2. 还没有一条真正像“修代码”的 demo，当前样例更多是在证明执行机制

因此，最快把 MVP 落地的方向应收敛为：

- 先补最小 batch eval
- 再补 1 条真实 Python 单元测试修复 demo
- 最后同步 README 的 MVP 使用路径

---

## 2. 目标

本轮设计目标是把 MendCode 收口为一个**可比较、可演示、可继续迭代**的 MVP。

本轮完成后，项目应满足：

- 能批量运行 `4 条机制 demo + 1 条 Python 单测修复 demo`
- 能输出统一且稳定的评测结果产物
- 能证明 MendCode 不只是机制框架，而是真能在 worktree 中修改源码并让测试通过

---

## 3. 非目标

本轮明确不做以下内容：

- planner / model 驱动的动态决策
- repo map、日志蒸馏、复杂上下文裁剪
- 多 Agent 调度
- Web UI / trace 可视化页面
- 更复杂的 patch 引擎
- 新任务类型扩展
- 历史结果数据库或复杂趋势分析平台

原则是只交付 MVP 必需闭环，不把“后续增强项”提前拉进来。

---

## 4. 用户选择与范围锁定

本轮设计基于以下已确认选择：

- 路线选择：方案 A
  - 先 eval
  - 后真实代码 demo
  - 最后收口文档
- 真实代码 demo 类型：Python 单元测试修复
- batch eval 默认任务集：
  - 现有 4 条机制 demo
  - 1 条新的 Python 代码修复 demo

因此，本轮 MVP 的默认评测集固定为 5 条任务。

---

## 5. 设计总览

本轮 MVP 由四个交付物组成：

1. 最小 batch eval 入口
2. 统一评测结果产物
3. 1 条真实 Python 代码修复 demo
4. README 中的 MVP 使用路径

四个交付物必须按顺序推进，不并行扩散。

---

## 6. 架构设计

### 6.1 Batch Eval 的定位

batch eval 不是第二套执行系统，而是现有单任务运行链路的薄封装。

数据流固定为：

`task list -> 逐条加载 TaskSpec -> 调用现有 run_task_preview -> 收集 RunState -> 归一化摘要 -> 写 summary.json / summary.md`

关键约束：

- batch eval 不进入 runner 内部接管状态机
- batch eval 不新增专用工具调用语义
- batch eval 只复用现有单任务运行结果，并做结果聚合

这样可以把风险控制在最小范围内，避免为了做 eval 再复制一套执行路径。

### 6.2 真实 Python Demo 的定位

新的 Python demo 必须走与现有 demo 完全相同的主链：

- 通过 task JSON 描述
- 在隔离 worktree 中运行
- 使用现有 fixed-flow 工具链
- 通过 `pytest` 验证修复是否成功

不允许为这条 demo 增加特判通道。否则它只是展示样例，不是 MVP 的真实能力证明。

### 6.3 README 的定位

README 在本轮只承担 MVP 入口说明，不承担完整产品文档职责。

README 应回答三件事：

- 如何运行单条 demo
- 如何运行 batch eval
- 如何查看结果产物

除此之外，不额外扩展未来路线、架构故事或复杂使用说明。

---

## 7. 交付物设计

### 7.1 交付物一：最小 Batch Eval 入口

第一版 batch eval 需要满足：

- 输入是一组 task 文件
- 逐条顺序运行
- 不并行
- 对每条任务都保留结构化结果
- 批量执行失败时不因单条任务失败而整体崩溃

第一版不要求：

- 历史结果比较
- 并发执行
- 多数据集管理
- 复杂过滤、重试、跳过策略

### 7.2 交付物二：统一结果产物

每次 batch eval 至少生成两个结果文件：

- `summary.json`
- `summary.md`

其中每条任务的稳定字段至少包括：

- `task_id`
- `status`
- `current_step`
- `summary`
- `passed_count`
- `failed_count`
- `applied_patch`
- `tool_results`
- `trace_path`
- `workspace_path`

要求：

- JSON 面向机器消费，字段稳定
- Markdown 面向快速阅读，能让人一眼看出整组任务表现

### 7.3 交付物三：真实 Python 单测修复 Demo

这条 demo 的目标不是“尽可能真实复杂”，而是“最小但 unmistakably code fix”。

约束：

- 使用 Python 源码文件 + 对应测试文件
- 初始状态下测试必然失败
- 修复后测试必然通过
- 变更范围小，避免引入复杂上下文依赖
- 失败与成功都应在本地稳定复现

推荐形态：

- 一个很小的函数实现有明显错误
- 一个对应测试断言当前失败
- `search_query` 能稳定命中目标实现文件
- `old_text / new_text` 替换粒度小且明确

### 7.4 交付物四：README MVP 路径

README 需要补一段 MVP 使用说明，最小包含：

- 单条 demo 的运行命令
- batch eval 的运行命令
- 结果文件位置与含义
- 真实 Python demo 的一句话说明

README 这一节应尽量短，保持“第一次打开仓库的人能立刻照着跑”。

---

## 8. 验收标准

本轮 MVP 完成的硬标准如下：

1. 能一条命令跑完 5 条任务：
   - 4 条机制 demo
   - 1 条 Python 单测修复 demo
2. 能稳定产出：
   - `summary.json`
   - `summary.md`
3. summary 中能看到每条任务的：
   - 成功 / 失败
   - 失败阶段
   - 验证命令通过情况
   - 是否实际应用 patch
4. 至少 1 条真实 Python 代码修复 demo 能从 fail 变 pass
5. README 能说明 MVP 的最小使用路径
6. 全量测试与 `ruff check .` 保持通过

---

## 9. 停手条件

为了避免范围膨胀，本轮必须明确停手点：

- batch eval 能跑、能输出结果就停
- 真实 Python 修复 demo 有 1 条稳定成功就停
- README 能支撑第一次使用就停
- 不为“更美观”“更通用”“更平台化”追加实现

一旦达到上述条件，就将本轮视为 MVP 落地完成，再进入下一轮。

---

## 10. 实施顺序

本轮实现顺序固定为三刀：

### 第一刀：Batch Eval 骨架

- 增加任务列表输入
- 复用单任务运行链路
- 写出 `summary.json / summary.md`

### 第二刀：真实 Python 修复 Demo

- 增加最小 Python 源码 / 测试 fixture
- 增加任务文件
- 确保它能被 batch eval 与单任务运行共同使用

### 第三刀：README 与最终验证

- 补 README MVP 路径
- 跑全量验证
- 确保结果产物、demo、CLI 文档一致

---

## 11. 风险与控制

### 风险 1：Batch eval 变成第二套 runner

控制方式：

- 只做顺序调度和结果汇总
- 不复制 runner 逻辑

### 风险 2：真实 Python demo 过于复杂

控制方式：

- 只做最小函数级错误修复
- 不引入复杂上下文和多文件联动

### 风险 3：README 与实际命令漂移

控制方式：

- README 命令继续用测试锁定
- batch eval 命令和结果路径进入回归测试范围

### 风险 4：为了演示效果继续扩 scope

控制方式：

- 用“5 条任务 + 2 个 summary 文件 + 1 条真实代码修复 demo”作为本轮唯一交付边界

---

## 12. 本轮完成后的项目状态

如果本设计按约束落地，MendCode 的状态将从：

`能跑单条 fixed-flow demo 的原型`

升级为：

`能批量评测固定任务集、能展示真实代码修复案例、可持续比较版本结果的 MVP`

这时项目才真正具备“继续迭代而不靠感觉”的基础。
