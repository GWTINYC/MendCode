from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative file path to read.")
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    tail_lines: int | None = Field(
        default=None,
        ge=1,
        description="Read the last N lines of the file. Use for questions about the end of a file.",
    )
    max_chars: int | None = Field(default=12000, ge=0)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReadFileArgs":
        if self.tail_lines is not None and (
            self.start_line is not None or self.end_line is not None
        ):
            raise ValueError("tail_lines cannot be combined with start_line or end_line")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.start_line > self.end_line
        ):
            raise ValueError("start_line cannot be greater than end_line")
        return self


class ListDirArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(default=".", description="Repo-relative directory path to list.")
    max_entries: int | None = Field(default=200, ge=0)


class GlobFileSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(description="Repo-relative glob pattern such as '**/*.py'.")
    max_results: int | None = Field(default=200, ge=0)


class RgArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Text to search for.")
    glob: str | None = Field(default=None, description="Optional ripgrep glob filter.")
    max_results: int | None = Field(default=50, ge=0)


class GitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["status", "diff", "log"]
    path: str | None = None
    limit: int = Field(default=5, ge=1, le=50)


class LspArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "diagnostics",
        "definition",
        "references",
        "hover",
        "document_symbols",
        "workspace_symbols",
        "implementations",
    ]
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    query: str | None = None
    max_results: int = Field(default=50, ge=1, le=500)


class ApplyPatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: str
    files_to_modify: list[str] = Field(default_factory=list)


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative file path to write.")
    content: str = Field(description="Complete text content to write.")


class EditFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative file path to edit.")
    old_string: str = Field(description="Exact text to replace.")
    new_string: str = Field(description="Replacement text.")
    replace_all: bool = False

    @model_validator(mode="after")
    def validate_old_string(self) -> "EditFileArgs":
        if not self.old_string:
            raise ValueError("old_string must not be empty")
        return self


class TodoItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "completed"]


class TodoWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todos: list[TodoItemArgs] = Field(default_factory=list)


class ToolSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)


class MemorySearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=25)


class MemoryWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=12000)
    tags: list[str] = Field(default_factory=list)
    source: str = "agent"
    metadata: dict[str, object] = Field(default_factory=dict)


class FileSummaryReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class FileSummaryRefreshArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class TraceAnalyzeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_path: str
    write_memory: bool = False


class SessionStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_tools: bool = True
    include_recent_steps: bool = True


class RunShellCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class ProcessStartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    cwd: str = "."
    name: str | None = None
    pty: bool = False
    background: bool = True


class ProcessPollArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    offset: int | None = Field(default=None, ge=0)
    stdout_offset: int | None = Field(default=None, ge=0)
    stderr_offset: int | None = Field(default=None, ge=0)
    max_chars: int = Field(default=12000, ge=0)


class ProcessWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    input: str


class ProcessStopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    signal: Literal["term", "kill"] = "term"


class EmptyToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
