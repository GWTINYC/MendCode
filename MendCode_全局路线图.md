# MendCode 全局路线图

## 1. 总方向

MendCode 的目标是成为面向本地代码仓库的可进化 Code Agent Runtime。

核心不是做一个命令行问答壳，而是让用户在 TUI 中用自然语言完成代码仓库里的查看、定位、修改、验证和复盘。模型不能直接操作终端，也不能凭空回答本地事实；所有本地能力都必须经过 schema tool call、权限校验、路径边界和 observation 回传。

主闭环：

```text
自然语言任务
-> 模型选择工具
-> ToolRegistry 校验参数
-> PermissionPolicy 判断风险
-> 本地执行
-> Observation 回传模型
-> 基于证据回答 / 修复 / 继续调用工具
-> Trace / Memory / Benchmark 复盘
```

长期要解决三类问题：

- 工具调用失控：统一工具注册、权限模式、Shell 风险和路径限制。
- 上下文膨胀：通过分层记忆、文件摘要、context compaction 和按需 recall 控制上下文。
- 经验难沉淀：把 trace、失败归因和 benchmark 结果转成可审查的 memory、rule 和 SKILL。

## 2. 长期原则

- TUI-first：自然语言对话是主入口，CLI 只保留为开发、兼容和评测辅助。
- Tool-first：本地事实必须来自工具 observation，不能由模型自由编造。
- Permission-first：provider-visible 工具必须来自 ToolPool，工具执行必须经过 PermissionPolicy。
- Evidence-first：修复任务必须有验证命令或验证 observation，不能只靠模型描述。
- Memory-with-review：长期记忆、规则和 SKILL 必须可审查、可追踪、可回滚。
- Benchmark-driven：每个用户暴露的问题都应沉淀为 scenario、PTY 或 benchmark case。

## 3. 阶段规划

### Phase A：Agent Runtime 与工具闭环

目标：稳定完成 `tool_call -> permission gate -> executor -> tool_result -> final_response`。

当前状态：主链路已完成。TUI 自然语言请求已统一走 schema tool-call AgentLoop；ToolRegistry、ToolPool、PermissionPolicy、session store、trace recorder 和 final response gate 已形成基础运行时。仍需继续剥离 legacy helper 和兼容路径。

下一步重点：

- 继续把 `app.agent.loop` 中的 legacy action/helper 收敛到 runtime 模块。
- 让 Provider 请求/响应摘要进入 trace，便于排查真实模型行为。
- 扩展 mock provider harness，覆盖写工具、权限确认恢复和 tool retry。

### Phase B：工具与权限系统

目标：支持 20 多种本地工具和 3 档权限模式，并让高风险命令拦截率接近目标。

当前状态：读文件、列目录、glob、rg、代码搜索、Patch、写文件、Shell、Git、验证、进程、LSP、记忆、trace、review queue 和 evolution rule 工具已经进入注册表。权限模式已收敛到 `read-only`、`workspace-write`、`danger-full-access`，旧模式作为兼容别名保留。

下一步重点：

- 强化写入工具的 diff preview、确认恢复和安全测试。
- 补齐文件系统元信息工具，例如受限 `stat` / `tree`。
- 继续增加权限场景测试，覆盖 install、network、git mutate、path escape 和 destructive shell。

### Phase C：分层记忆与上下文管理

目标：让短期状态、中期文件摘要和长期经验按需进入上下文，减少重复读文件和无效历史堆叠。

当前状态：JSONL memory store、文件摘要缓存、自动 recall、memory tools、review queue、context metrics 和 observation compaction 已落地。Runtime 已记录 memory recall 命中、read_file 次数、重复 read_file 次数和 compact 字符量。

下一步重点：

- 接入 tokenizer-aware context budget，按模型窗口动态裁剪上下文。
- 将文件摘要扩展为 repo map 和跨轮摘要缓存。
- 建立长会话 compact summary 和 session health。
- 把 repeated read、context size 和 token-ish 指标纳入固定 benchmark 观察。

### Phase D：自进化闭环

目标：让 trace 和 benchmark 失败能够沉淀为可审查、可回滚、可验证收益的 memory、rule 和 SKILL。

当前状态：EvolutionRuntime 能生成 lesson candidate；analysis report 可以通过 schema tools 转成 pending memory/rule candidates；evolution rule 可以通过 TUI 对话 list/view/accept/reject；accepted rules 会写入本地 `data/evolution/rules.jsonl` 并按相关性注入后续 provider context。Session analysis 和 benchmark analysis 已能产生结构化失败证据。

下一步重点：

- 扩展 analysis ingestion 的候选类型，覆盖 prompt rule、skill 和 tool schema hint。
- 把候选统一进入 TUI review loop，用户接受后才影响 runtime。
- 建立 SKILL.md-compatible skill system，先沉淀 Debug、Test-Fix、Review、Repo-Map。
- 用 benchmark 回归证明候选是否提升工具链路、降低重复读取或减少上下文。

### Phase E：TUI 体验与评测体系

目标：让真实用户常见问题在 TUI 中稳定、简洁、可复盘地完成。

当前状态：已有真实 PTY e2e 测试、scenario tests、tool parity manifest、benchmark manifest 和 benchmark gate。测试覆盖目录查看、文档末句、Git 状态、代码定位、危险命令拦截、会话列表、多轮对话、记忆召回和修复链路。

下一步重点：

- 每个用户暴露的体验问题都先补 scenario / PTY / benchmark case。
- 增加工具调用折叠/展开、trace viewer、review 面板和 provider doctor。
- 固化 6 类以上评测集，并持续统计工具链路通过率、高风险命令拦截率、Token-ish 降低和重复读文件次数。

## 4. 暂缓事项

在 Runtime、工具权限、记忆压缩、自进化闭环和 TUI 评测稳定前，暂缓：

- 多 Agent 调度
- MCP 生命周期管理
- 插件市场
- Web 搜索
- Notebook 编辑
- 自动 commit / push
- GitHub PR 自动化
- 企业权限系统
- 长期无人值守后台任务

## 5. 开发前检查

每轮开发前只问五个问题：

1. 是否加强了自然语言 TUI 到工具 observation 的闭环？
2. 是否减少了模型编造本地事实的机会？
3. 是否让权限边界更集中、更可测？
4. 是否降低了上下文膨胀或重复读取？
5. 是否能通过 trace、conversation、scenario 或 benchmark 复盘收益？

如果答案不清楚，先不要扩功能。
