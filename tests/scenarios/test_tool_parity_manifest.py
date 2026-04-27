import json
from pathlib import Path


def test_tool_parity_manifest_covers_core_tool_roundtrips() -> None:
    manifest_path = Path(__file__).with_name("tool_parity_scenarios.json")

    scenarios = json.loads(manifest_path.read_text(encoding="utf-8"))

    names = {scenario["name"] for scenario in scenarios}
    assert names >= {
        "read_file_roundtrip",
        "rg_chunk_assembly",
        "write_file_allowed",
        "write_file_denied",
        "multi_tool_turn_roundtrip",
        "bash_stdout_roundtrip",
        "bash_permission_prompt_approved",
        "bash_permission_prompt_denied",
    }
    for scenario in scenarios:
        assert scenario["user_input"].strip()
        assert scenario["expected_tools"]
        assert scenario["expected_visible_answer"].strip()
        assert scenario["max_visible_chars"] <= 900
