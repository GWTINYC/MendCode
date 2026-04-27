from app.runtime.lsp_client import LanguageServerUnavailable, LspClientManager
from app.schemas.agent_action import Observation
from app.tools.arguments import LspArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def lsp(args: LspArgs, context: ToolExecutionContext) -> Observation:
    client = context.lsp_client or LspClientManager()
    try:
        payload = client.request(args, context.workspace_path)
    except LanguageServerUnavailable as exc:
        return tool_observation(
            tool_name="lsp",
            status="rejected",
            summary="Language server unavailable",
            payload=args.model_dump(mode="json"),
            error_message=str(exc),
        )
    return tool_observation(
        tool_name="lsp",
        status="succeeded",
        summary=f"LSP {args.operation}",
        payload=payload,
    )
