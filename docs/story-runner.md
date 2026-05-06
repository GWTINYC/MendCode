# Story Runner

Story Runner 是 MendCode 对 Ralph 风格开发循环的本地化版本。它不绕过 MendCode 的 Agent Runtime，也不自动执行高风险命令；第一版只负责把大任务拆成可持续推进的小 story，并记录每轮进展。

核心循环：

```text
读取 story plan
-> 选择最高优先级且 passes=false 的 story
-> 在独立 worktree 中实现
-> 运行 story 声明的 verification commands
-> 通过后标记 passes=true
-> 追加 compact progress
-> 下一轮 fresh context 继续
```

## Plan 格式

```json
{
  "branch_name": "feature/context-compaction-v2",
  "progress_path": "tasks/context-v2/progress.md",
  "stories": [
    {
      "id": "MC-001",
      "title": "Add tokenizer-aware context budget",
      "priority": 10,
      "passes": false,
      "acceptance_criteria": ["budget uses model window"],
      "verification_commands": ["pytest tests/unit/test_context_manager.py -q"],
      "notes": ["Keep provider context compact."]
    }
  ]
}
```

字段约定：

- `priority` 数字越小越优先。
- `passes=false` 表示下一轮仍可被选择。
- `verification_commands` 是 story 自己的验收命令，不替代全量回归。
- `progress_path` 可以写成 plan 同目录相对路径，也可以写成 `tasks/...` 形式。

## CLI

查看计划状态：

```bash
mendcode story status tasks/context-v2/plan.json
```

选择下一条 story：

```bash
mendcode story next tasks/context-v2/plan.json
```

标记通过：

```bash
mendcode story mark-passed tasks/context-v2/plan.json MC-001
```

追加进展：

```bash
mendcode story append-progress tasks/context-v2/plan.json MC-001 \
  --status passed \
  --summary "Implemented tokenizer-aware budget." \
  --verification "pytest tests/unit/test_context_manager.py -q" \
  --trace data/traces/run-123.jsonl \
  --commit abc1234 \
  --learning "Keep provider context compact."
```

## 当前边界

- 不自动调用模型写代码。
- 不自动创建 commit 或 push。
- 不自动提升权限。
- 不把完整 trace、patch、stdout 写入 progress，只记录摘要和指针。

后续可以把 Story Runner 接入 TUI 和 AgentLoop，让用户在对话中选择 story、执行 story、查看验证结果和审查 progress。
