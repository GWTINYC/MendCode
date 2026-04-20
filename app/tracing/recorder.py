from pathlib import Path

import orjson

from app.schemas.trace import TraceEvent


class TraceRecorder:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def record(self, event: TraceEvent) -> Path:
        output_path = self.base_dir / f"{event.run_id}.jsonl"
        with output_path.open("ab") as handle:
            handle.write(orjson.dumps(event.model_dump(mode="json")))
            handle.write(b"\n")
        return output_path
