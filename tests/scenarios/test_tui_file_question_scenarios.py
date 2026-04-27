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
    assert_visible_answer_contains(transcript, "content: omitted from chat stream")
    assert_visible_answer_contains(transcript, "content_length=28")
    if "## 1. 文档职责" in transcript.visible_text:
        pytest.fail(transcript.debug_text())
    assert_no_fabricated_command_claims(transcript)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)


async def test_document_last_sentence_question_does_not_dump_file_content(tmp_path):
    last_sentence = "最后一句：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"
    document = "\n\n".join(
        [
            "# MendCode 问题记录",
            "第一段说明这个文档记录工程问题。",
            "第二段继续解释背景。",
            last_sentence,
        ]
    )
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="document last sentence",
            repo_files={"MendCode_问题记录.md": document},
            user_inputs=["MendCode_问题记录的最后一句是什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="succeeded",
                    summary="Read MendCode_问题记录.md",
                    payload={
                        "relative_path": "MendCode_问题记录.md",
                        "start_line": 7,
                        "end_line": 7,
                        "total_lines": 7,
                        "content": last_sentence,
                        "content_excerpt": last_sentence,
                        "content_length": len(last_sentence),
                        "content_truncated": False,
                    },
                    args={"path": "MendCode_问题记录.md", "tail_lines": 3},
                )
            ],
            final_summary="最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "read_file")
    assert_visible_answer_contains(
        transcript,
        "不再记录纯讨论、一次性环境噪声、旧路线细枝末节",
    )
    if "# MendCode 问题记录" in transcript.visible_text:
        pytest.fail(transcript.debug_text())
    if "第一段说明这个文档记录工程问题" in transcript.visible_text:
        pytest.fail(transcript.debug_text())
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
                                    "Set MENDCODE_PROVIDER=openai-compatible to configure provider."
                                ),
                            },
                            {
                                "relative_path": "app/config/settings.py",
                                "line_number": 1,
                                "line": ("provider = os.getenv('MENDCODE_PROVIDER', 'scripted')"),
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
