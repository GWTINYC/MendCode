# MendCode

一款专为企业本地环境设计的代码维护 Agent。

## Current Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check, task file inspection, and `task run` verification execution inside a per-run git worktree
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

```bash
mendcode version
mendcode health
mendcode task validate data/tasks/demo.json
mendcode task show data/tasks/demo.json
mendcode task run data/tasks/demo.json
```

`task run` now creates a temporary workspace under `.worktrees/preview-<id>/`, executes verification commands there, and records `workspace_path` plus cleanup results in trace output.

## API

```bash
uvicorn app.api.server:app --reload
```
