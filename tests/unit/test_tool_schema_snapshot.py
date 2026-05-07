import json
from pathlib import Path

from app.tools.registry import default_tool_registry

SNAPSHOT_PATH = Path(__file__).parents[1] / "fixtures" / "tool_schema_snapshot.json"
CORE_TOOL_NAMES = {
    "read_file",
    "stat",
    "tree",
    "list_dir",
    "rg",
    "apply_patch",
    "git",
    "memory_search",
}


def build_tool_schema_snapshot() -> list[dict[str, object]]:
    registry = default_tool_registry()
    pool = registry.tool_pool(
        permission_mode="danger-full-access",
        allowed_tools=CORE_TOOL_NAMES,
    )
    snapshot: list[dict[str, object]] = []
    for name in pool.names():
        spec = registry.get(name)
        openai_tool = spec.to_openai_tool()
        parameters = openai_tool["function"]["parameters"]
        snapshot.append(
            {
                "name": name,
                "description": openai_tool["function"]["description"],
                "required": sorted(parameters.get("required", [])),
                "risk": spec.risk_level.value,
            }
        )
    return snapshot


def test_core_tool_schema_snapshot_matches_fixture() -> None:
    actual = build_tool_schema_snapshot()
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert {item["name"] for item in actual} == CORE_TOOL_NAMES
    assert actual == expected
