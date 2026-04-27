from pathlib import Path

import app.runtime.lsp_client as lsp_client_module
from app.config.settings import Settings
from app.tools.arguments import LspArgs
from app.tools.lsp_tool import lsp
from app.tools.structured import ToolExecutionContext


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


def test_lsp_unavailable_server_returns_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lsp_client_module.shutil, "which", lambda command: None)
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )
    observation = lsp(
        LspArgs(operation="definition", path="app.py", line=1, column=1),
        context,
    )

    assert observation.status == "rejected"
    assert "language server unavailable" in str(observation.error_message)
    assert observation.payload["operation"] == "definition"


def test_lsp_diagnostics_with_fake_client(tmp_path: Path) -> None:
    class FakeLspClient:
        def request(self, args: LspArgs, workspace_path: Path) -> dict[str, object]:
            return {
                "operation": args.operation,
                "results": [
                    {
                        "relative_path": "app.py",
                        "start_line": 1,
                        "message": "example diagnostic",
                    }
                ],
                "truncated": False,
            }

    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    ).model_copy(update={"lsp_client": FakeLspClient()})
    observation = lsp(LspArgs(operation="diagnostics", path="app.py"), context)

    assert observation.status == "succeeded"
    assert observation.payload["operation"] == "diagnostics"
    assert observation.payload["results"][0]["message"] == "example diagnostic"
