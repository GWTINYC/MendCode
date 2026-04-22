# MendCode Phase 2A Read-Only Tools Design

## 1. 背景

截至 2026-04-22，MendCode 已经完成了 Phase 1B 的执行边界收口：

- `task run` 会在独立 worktree 中执行 verification
- command policy、executor、worktree manager 已落地
- runner 已收敛为“编排 workspace、执行 verification、汇总 trace 与 summary”
- merge 后的仓库 hygiene 也已补齐，运行产物边界更清晰

这说明系统已经具备了“安全、受控地运行验证命令”的基础能力。但如果想继续向“真正能处理本地代码仓问题的 Agent”推进，当前还缺少一组最基础的仓内操作能力：

- 读取文件
- 检索代码
- 后续再进入补丁修改

因此，下一刀不应直接进入复杂 orchestrator、prompt 编排或自动补丁链路，而应先补齐只读工具层，让系统具备稳定的“读、搜”能力，并把工具边界冻结下来。

---

## 2. 目标

本设计只解决一个很窄的目标：

在不接入 orchestrator 自动调用的前提下，先实现两项只读工具：

1. `read_file`
2. `search_code`

并同时补齐：

- 统一的工具结果契约
- `workspace_path` 内的路径边界校验
- 工具级 trace 记录方式
- 对应的单元测试

完成后，MendCode 将从“只能跑 verification 的受控执行框架”，推进到“具备最小只读仓库操作能力的 Agent 框架”。

---

## 3. 非目标

本轮明确不做：

- 不实现 `apply_patch`
- 不接入 orchestrator 自动决策流
- 不实现 tool registry
- 不做 repo map
- 不做日志蒸馏
- 不做 prompt 层工具编排
- 不做复杂 planner
- 不做 AST 级搜索

本轮只做“只读工具层本身”，不扩展到更高层。

---

## 4. 方案选择

本轮评估过三种路径：

### 4.1 方案一：独立工具模块 + 统一结果契约

做法：

- 在 `app/tools/` 下新增只读工具模块
- 定义统一 `ToolResult` / 错误语义
- 工具只接受 `workspace_path` 范围内的参数

优点：

- 工具边界最清楚
- 后面接 orchestrator 最稳
- 不会再次把 runner 做胖

缺点：

- 本轮更像“打底”，用户面功能增长不明显

结论：

- 推荐，采用该方案

### 4.2 方案二：工具模块 + 提前做 registry

做法：

- 在工具实现之外，同时引入 registry 和统一分发入口

问题：

- 会提前把“工具实现”和“工具编排”耦合在一起
- 当前工具数量太少，抽象收益不高

结论：

- 当前不采用

### 4.3 方案三：把只读能力直接塞进 runner / workspace

做法：

- 不建立工具层，直接在现有执行链附近补函数

问题：

- 很快会破坏前面已经收口好的 runner 边界
- 后面接 `apply_patch` 时会更混乱

结论：

- 明确不采用

---

## 5. 设计结论

### 5.1 本轮只做工具层，不做 orchestrator 接线

本轮只解决：

- `read_file`
- `search_code`
- 统一结果契约
- 路径边界校验
- 测试

不解决：

- 谁来调用工具
- 何时调用工具
- 工具调用顺序怎么决策

这部分留到后续最小 orchestrator loop 再接。

### 5.2 工具先做成普通 Python 函数

当前不引入类、registry 或复杂抽象。

原因：

- 工具只有两个，函数足够
- 先保证行为稳定，比抽象更重要
- 后面如果工具数量增长，再做 registry 也不迟

### 5.3 工具输入统一围绕 `workspace_path`

所有工具都必须显式接受 `workspace_path`，并且：

- 只接受相对 `workspace_path` 的文件参数
- 不允许越界访问
- 不直接依赖 CLI、runner、prompt

这保证工具层是可复用的本地库接口，而不是临时拼接逻辑。

---

## 6. 模块设计

### 6.1 `app/tools/schemas.py`

职责：

- 定义统一工具结果契约

建议包含：

```python
ToolStatus = Literal["passed", "failed", "rejected"]


class ToolResult(BaseModel):
    tool_name: str
    status: ToolStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    workspace_path: str
```

设计要求：

- 所有工具统一返回 `ToolResult`
- `payload` 承载结构化结果，不直接暴露原始 shell 输出
- `summary` 提供给后续 trace / summary / orchestrator 使用

当前阶段不需要把 schema 设计得过宽，先服务这两个只读工具即可。

### 6.2 `app/tools/guard.py`

职责：

- 做 `workspace_path` 内的路径解析与边界校验

最小能力：

- 解析相对路径
- 归一化到 `workspace_path`
- 拒绝 `..` 越界
- 拒绝目录误用
- 拒绝不存在路径

设计要求：

- 安全边界不分散在工具实现内部
- `read_file` 和 `search_code` 共享同一套 guard 逻辑

### 6.3 `app/tools/read_only.py`

职责：

- 承载本轮两个只读工具：
  - `read_file(...)`
  - `search_code(...)`

当前阶段不强行拆成多个文件，因为：

- 工具数量只有两个
- 都属于只读能力
- 先保持实现紧凑，后面再按增长情况拆分

### 6.4 测试文件

建议新增：

- `tests/unit/test_tool_schemas.py`
- `tests/unit/test_tool_guard.py`
- `tests/unit/test_read_only_tools.py`

其中：

- schema 测结果契约
- guard 测边界
- read-only tools 测真实行为

---

## 7. 工具行为设计

### 7.1 `read_file`

输入建议：

- `workspace_path`
- `relative_path`
- `start_line: int | None = None`
- `end_line: int | None = None`
- `max_chars: int | None = None`

行为要求：

- 只读取 `workspace_path` 内普通文本文件
- 支持全文读取
- 支持按行范围读取
- 支持字符截断

明确拒绝：

- 越界路径
- 不存在路径
- 目录
- 明显二进制文件

返回 `payload` 建议至少包含：

- `relative_path`
- `start_line`
- `end_line`
- `total_lines`
- `content`
- `truncated`

设计原则：

- 目标是“Agent 可稳定读取”，不是“做万能文件查看器”
- 不做复杂编码探测
- 当前默认 `utf-8`，无法按文本读取时结构化失败

### 7.2 `search_code`

输入建议：

- `workspace_path`
- `query`
- `glob: str | None = None`
- `max_results: int | None = None`

行为要求：

- 优先直接调用 `rg`
- 返回结构化命中结果，而不是裸 stdout

明确拒绝：

- 空查询
- 越界搜索
- 参数非法

返回 `payload` 建议至少包含：

- `query`
- `glob`
- `total_matches`
- `matches`

每条 `match` 建议包含：

- `relative_path`
- `line_number`
- `line_text`

设计原则：

- 当前只做文本检索，不做 AST 级搜索
- 不做复杂排序
- `glob` 只做轻量过滤

### 7.3 统一错误语义

本轮工具统一只保留三种状态：

- `passed`
- `failed`
- `rejected`

含义：

- `passed`：工具正常完成
- `failed`：请求合法，但执行失败
- `rejected`：请求越界、不合法或违反约束

这样后续 orchestrator 不需要猜测失败类型，能更稳地接入。

---

## 8. Trace 设计

虽然本轮不接 orchestrator，但工具结果设计必须为 trace 预留稳定结构。

建议本轮先约定工具 trace payload 形态至少包含：

- `tool_name`
- `status`
- `summary`
- `workspace_path`
- `payload`
- `error_message`

本轮可以先不单独接入 CLI 或 runner trace，只要保证 `ToolResult` 结构足够稳定，下一刀即可直接挂到 trace recorder。

---

## 9. 测试策略

本轮只做三层测试：

### 9.1 guard 测试

覆盖：

- 正常相对路径解析
- `..` 越界拒绝
- 不存在路径拒绝
- 目录误用拒绝
- workspace 外路径拒绝

### 9.2 `read_file` 测试

覆盖：

- 正常读取全文
- 按行范围读取
- 大文件截断
- 目录 / 二进制 / 不存在文件失败
- 返回结构一致

### 9.3 `search_code` 测试

覆盖：

- 正常命中
- 无结果
- `max_results` 生效
- `glob` 过滤生效
- 空查询拒绝
- `rg` 异常时结构化失败

本轮不需要端到端 agent 测试，因为 orchestrator 还没有接进来。

---

## 10. 验收标准

本轮完成标准压缩为五条：

1. `read_file` 可稳定读取 `workspace_path` 内文本文件
2. `search_code` 可稳定返回结构化命中结果
3. 所有越界访问都会被拒绝
4. 两个工具共享统一 `ToolResult` 契约
5. 单测与 lint 全绿

换句话说，本轮的成功标志不是“Agent 已经会修复问题”，而是：

`只读工具边界已经稳定，后面可以安全接入 orchestrator`

---

## 11. 停手点与后续顺序

### 11.1 本轮停手点

做到下面这些就停：

- `read_file`、`search_code` 都可在 `workspace_path` 内稳定工作
- 返回结构统一
- 边界明确
- 单测齐

本轮不继续做：

- `apply_patch`
- tool registry
- repo map
- 日志蒸馏
- orchestrator 自动调用

### 11.2 下一刀顺序

本轮完成后，最自然的下一步是：

1. 补 `apply_patch`
2. 统一工具调用 trace
3. 再进入最小 orchestrator loop

顺序原则是：

`先把读、搜、改三件事做全，再去做工具编排和 Agent 决策`

---

## 12. 结论

Phase 2A 的本质不是“多了两个功能点”，而是：

- 工具层边界第一次正式建立
- 只读能力从 runner / workspace 之外独立出来
- 后续 `apply_patch`、orchestrator、eval 都有了稳定挂载点

这是 MendCode 从“受控 verification runner”向“真正可操作本地代码仓的 Agent”推进的第一步，而且必须保持范围克制。
