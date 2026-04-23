# MendCode

一款专为企业本地环境设计的代码维护 Agent。

## Current Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check, task file inspection, and `task run` fixed-flow execution inside a per-run git worktree
- Command-policy guarded verification execution with timeout and trace output
- FastAPI health endpoint
- JSONL trace output for task runs

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## CLI

Installed usage:

```bash
mendcode version
mendcode health
mendcode task validate data/tasks/demos/success.json
mendcode task run data/tasks/demos/success.json
mendcode task run data/tasks/demos/unauthorized-tool.json
mendcode task run data/tasks/demos/ambiguous-search.json
mendcode task run data/tasks/demos/verification-fail.json
mendcode task run data/tasks/demos/python-unit-fix.json
```

In this nested worktree development setup, `python -m app.cli.main ...` is the authoritative invocation path. The `mendcode ...` examples remain valid for normal installed usage, but the branch-accurate commands are:

```bash
python -m app.cli.main version
python -m app.cli.main health
python -m app.cli.main task validate data/tasks/demos/success.json
python -m app.cli.main task run data/tasks/demos/success.json
python -m app.cli.main task run data/tasks/demos/unauthorized-tool.json
python -m app.cli.main task run data/tasks/demos/ambiguous-search.json
python -m app.cli.main task run data/tasks/demos/verification-fail.json
python -m app.cli.main task run data/tasks/demos/python-unit-fix.json
```

`task run` creates a per-run workspace under `.worktrees/preview-<id>/`, can execute the demo task suite using structured `entry_artifacts`, preserves successful workspaces by default, and records `workspace_path` plus cleanup results in trace output.

Demo coverage:

- `success.json`: proves the fixed `read -> search -> patch -> verify` happy path.
- `unauthorized-tool.json`: proves task-declared tool authorization is enforced.
- `ambiguous-search.json`: proves locate-stage failure is surfaced when search is not unique.
- `verification-fail.json`: proves verify-stage failure is surfaced cleanly.
- `python-unit-fix.json`: proves a real Python source repair by making a pytest check pass.

## MVP Eval

Run the current MVP demo suite in one batch:

```bash
python -m app.cli.main eval run \
  data/tasks/demos/success.json \
  data/tasks/demos/unauthorized-tool.json \
  data/tasks/demos/ambiguous-search.json \
  data/tasks/demos/verification-fail.json \
  data/tasks/demos/python-unit-fix.json
```

Batch eval writes result files under `data/evals/eval-<id>/`:

- `summary.json`: machine-readable batch result with one row per task.
- `summary.md`: human-readable summary for quick review.

`python-unit-fix.json` is the first real code-repair demo. It patches a Python source file in a detached worktree and proves the fix by making `pytest` pass.

## API

```bash
uvicorn app.api.server:app --reload
```
