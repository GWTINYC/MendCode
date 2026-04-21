# MendCode

一款专为企业本地环境设计的代码维护 Agent。

## Phase 0 Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check and task file inspection
- FastAPI health endpoint
- JSONL trace output for task previews

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

## API

```bash
uvicorn app.api.server:app --reload
```
