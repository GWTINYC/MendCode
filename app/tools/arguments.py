from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative file path to read.")
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_chars: int | None = Field(default=12000, ge=0)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReadFileArgs":
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


class ApplyPatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: str
    files_to_modify: list[str] = Field(default_factory=list)


class RunShellCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class EmptyToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
