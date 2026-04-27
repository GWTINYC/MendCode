import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.arguments import LspArgs


class LanguageServerUnavailable(RuntimeError):
    pass


class LspClientManager:
    def request(self, args: "LspArgs", workspace_path: Path) -> dict[str, object]:
        server = self._server_for(args.path)
        if server is None:
            raise LanguageServerUnavailable("language server unavailable")
        raise LanguageServerUnavailable(
            "language server transport is unavailable in this environment"
        )

    def _server_for(self, path: str | None) -> str | None:
        if path is None:
            return None
        suffix = Path(path).suffix
        candidates: list[str] = []
        if suffix == ".py":
            candidates = ["pyright-langserver", "basedpyright-langserver"]
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            candidates = ["typescript-language-server"]
        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
        return None
