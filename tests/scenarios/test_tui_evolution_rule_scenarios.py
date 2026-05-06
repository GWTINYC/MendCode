import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_tui_lists_pending_evolution_rules(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule list",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["有哪些待确认的规则？"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_list",
                    status="succeeded",
                    summary="Found 1 evolution rule candidates",
                    payload={
                        "status": "pending",
                        "total_candidates": 1,
                        "candidates": [
                            {
                                "id": "rule-1",
                                "rule_type": "observation_required",
                                "rule_text": "回答本地事实前必须有成功 observation。",
                                "scope": "local facts",
                                "activation_hint": "git status",
                            }
                        ],
                    },
                    args={"status": "pending"},
                )
            ],
            final_summary="有 1 条待确认规则：回答本地事实前必须有成功 observation。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "待确认规则")
    assert_visible_answer_contains(transcript, "observation")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=800)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_tui_accepts_rule_candidate(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule accept",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["接受第一条规则"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_accept",
                    status="succeeded",
                    summary="Accepted evolution rule candidate rule-1",
                    payload={
                        "candidate_id": "rule-1",
                        "rule": {
                            "candidate_id": "rule-1",
                            "rule_type": "tool_required",
                            "rule_text": "回答 Git 状态前必须调用 git 工具。",
                        },
                    },
                    args={"candidate_id": "rule-1"},
                )
            ],
            final_summary="已接受第一条规则：回答 Git 状态前必须调用 git 工具。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "已接受")
    assert_visible_answer_contains(transcript, "Git")
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_tui_accepts_rule_candidate_with_edits(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule accept with edits",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["接受第一条，但改成：回答 Git 状态前必须调用 git 工具。"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_accept_with_edits",
                    status="succeeded",
                    summary="Accepted evolution rule candidate rule-1",
                    payload={
                        "candidate_id": "rule-1",
                        "rule": {
                            "candidate_id": "rule-1",
                            "rule_type": "tool_required",
                            "rule_text": "回答 Git 状态前必须调用 git 工具。",
                            "scope": "git status",
                            "activation_hint": "git status",
                        },
                    },
                    args={
                        "candidate_id": "rule-1",
                        "rule_text": "回答 Git 状态前必须调用 git 工具。",
                        "scope": "git status",
                        "activation_hint": "git status",
                    },
                )
            ],
            final_summary="已按你的修改接受规则：回答 Git 状态前必须调用 git 工具。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "已按你的修改")
    assert_visible_answer_contains(transcript, "Git")
    assert_no_raw_trace_or_large_json_dump(transcript)
