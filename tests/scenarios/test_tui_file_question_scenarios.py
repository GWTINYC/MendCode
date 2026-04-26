import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_has_evidence_from_observation,
    assert_no_fabricated_command_claims,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_file_first_line_question_reads_actual_file(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="file first line question",
            repo_files={
                "MendCode_开发方案.md": "# MendCode 开发方案\n\n## 1. 文档职责\n",
            },
            user_inputs=["MendCode_开发方案第一句话是什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="succeeded",
                    summary="Read MendCode_开发方案.md",
                    payload={
                        "relative_path": "MendCode_开发方案.md",
                        "content": "# MendCode 开发方案\n\n## 1. 文档职责\n",
                        "content_excerpt": "# MendCode 开发方案\n\n## 1. 文档职责\n",
                        "content_length": 28,
                        "content_truncated": False,
                    },
                    args={"path": "MendCode_开发方案.md", "end_line": 3},
                )
            ],
            final_summary="第一句话是：# MendCode 开发方案",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "read_file")
    assert_visible_answer_contains(transcript, "MendCode 开发方案")
    assert_visible_answer_contains(transcript, "## 1. 文档职责")
    assert_no_fabricated_command_claims(transcript)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)


@pytest.mark.parametrize(
    "user_input",
    [
        "帮我找一下配置 provider 的地方",
        "provider configuration 在哪里",
    ],
)
async def test_provider_config_question_uses_code_search(tmp_path, user_input):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="provider config search",
            repo_files={
                "app/config/settings.py": (
                    "provider = os.getenv('MENDCODE_PROVIDER', 'scripted')\n"
                ),
                "README.md": "Set MENDCODE_PROVIDER=openai-compatible to configure provider.\n",
            },
            user_inputs=[user_input],
            tool_steps=[
                ScenarioToolStep(
                    action="rg",
                    status="succeeded",
                    summary="Searched MENDCODE_PROVIDER",
                    payload={
                        "query": "MENDCODE_PROVIDER",
                        "total_matches": 2,
                        "matches": [
                            {
                                "relative_path": "README.md",
                                "line_number": 1,
                                "line": (
                                    "Set MENDCODE_PROVIDER=openai-compatible to "
                                    "configure provider."
                                ),
                            },
                            {
                                "relative_path": "app/config/settings.py",
                                "line_number": 1,
                                "line": (
                                    "provider = os.getenv('MENDCODE_PROVIDER', "
                                    "'scripted')"
                                ),
                            },
                        ],
                    },
                    args={"query": "MENDCODE_PROVIDER"},
                )
            ],
            final_summary="provider 配置主要在 README.md 和 app/config/settings.py。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "rg")
    assert_visible_answer_contains(transcript, "README.md")
    assert_visible_answer_contains(transcript, "app/config/settings.py")
    assert_no_fabricated_command_claims(transcript)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
