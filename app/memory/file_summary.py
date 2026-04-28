import hashlib
import re
from pathlib import Path

from app.memory.models import FileSummary, MemoryRecord

_SYMBOL_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def build_file_summary(
    repo_path: Path,
    relative_path: str,
    *,
    max_chars: int = 1200,
) -> FileSummary:
    repo, file_path = _resolve_repo_file(repo_path, relative_path)
    content = file_path.read_text(encoding="utf-8")
    stat = file_path.stat()
    symbols = _extract_symbols(content)
    summary = _summary_text(content, symbols=symbols, max_chars=max_chars)
    return FileSummary(
        path=file_path.relative_to(repo).as_posix(),
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        line_count=len(content.splitlines()),
        summary=summary,
        symbols=symbols,
    )


def summary_record_for_file(repo_path: Path, relative_path: str) -> MemoryRecord:
    summary = build_file_summary(repo_path, relative_path)
    return MemoryRecord(
        kind="file_summary",
        title=f"File summary: {summary.path}",
        content=summary.summary,
        source=f"file:{summary.path}",
        tags=["file", summary.path],
        metadata=summary.model_dump(mode="json"),
    )


def _resolve_repo_file(repo_path: Path, relative_path: str) -> tuple[Path, Path]:
    path = (repo_path / relative_path).resolve()
    repo = repo_path.resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise ValueError("file summary path must stay inside repo") from exc
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return repo, path


def _extract_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    for match in _SYMBOL_RE.finditer(content):
        name = match.group(1)
        if name not in symbols:
            symbols.append(name)
    return symbols


def _summary_text(content: str, *, symbols: list[str], max_chars: int) -> str:
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    head = "\n".join(lines[:20])
    symbol_text = f"Symbols: {', '.join(symbols)}\n" if symbols else ""
    text = symbol_text + head
    return text[:max_chars] + ("...[truncated]" if len(text) > max_chars else "")
