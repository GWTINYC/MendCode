from __future__ import annotations

from app.config.settings import Settings
from app.schemas.agent_action import Observation
from app.tools.arguments import ProviderDoctorArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext

_SUPPORTED_REMOTE_PROVIDERS = {"openai-compatible", "minimax"}


def provider_doctor(
    args: ProviderDoctorArgs,
    context: ToolExecutionContext,
) -> Observation:
    del args
    settings = context.settings
    payload = _build_payload(settings)
    if settings.provider == "scripted":
        payload["tool_call_check"] = {
            "status": "skipped",
            "summary": "scripted provider does not require remote tool calls",
        }
        return tool_observation(
            tool_name="provider_doctor",
            status="succeeded",
            summary="Scripted provider is configured",
            payload=payload,
        )

    missing = _missing_provider_fields(settings)
    if missing:
        payload["tool_call_check"] = {
            "status": "failed",
            "summary": "provider configuration is incomplete",
            "missing": missing,
        }
        return tool_observation(
            tool_name="provider_doctor",
            status="failed",
            summary="Provider configuration is incomplete",
            payload=payload,
            error_message="Missing required provider settings: " + ", ".join(missing),
        )

    payload["tool_call_check"] = {
        "status": "passed",
        "summary": "provider configuration can support tool calls",
        "supported": True,
    }
    return tool_observation(
        tool_name="provider_doctor",
        status="succeeded",
        summary="Provider configuration looks ready",
        payload=payload,
    )


def _build_payload(settings: Settings) -> dict[str, object]:
    return {
        "provider": settings.provider,
        "model": settings.provider_model,
        "base_url": settings.provider_base_url,
        "api_key_present": bool(settings.provider_api_key),
        "provider_mode": settings.provider,
    }


def _missing_provider_fields(settings: Settings) -> list[str]:
    missing: list[str] = []
    if settings.provider not in _SUPPORTED_REMOTE_PROVIDERS:
        missing.append("MENDCODE_PROVIDER")
    if not settings.provider_model:
        missing.append("MENDCODE_MODEL")
    if not settings.provider_base_url:
        missing.append("MENDCODE_BASE_URL")
    if not settings.provider_api_key:
        missing.append("MENDCODE_API_KEY")
    return missing
