import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_benchmark_case_passed,
    assert_did_not_use_chat,
    assert_has_evidence_from_observation,
    assert_has_rejected_evidence_from_observation,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_review_queue_question_uses_review_queue_list_tool(tmp_path) -> None:
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="review queue list",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["有哪些失败可以沉淀？"],
            tool_steps=[
                ScenarioToolStep(
                    action="review_queue_list",
                    status="succeeded",
                    summary="Found 1 review candidates",
                    payload={
                        "status": "pending",
                        "total_candidates": 1,
                        "candidates": [
                            {
                                "id": "candidate-1",
                                "kind": "context_lesson",
                                "summary": "Use tail_lines for final-line questions.",
                                "suggested_memory_kind": "failure_lesson",
                                "confidence": 0.8,
                                "status": "pending",
                            }
                        ],
                    },
                    args={"status": "pending"},
                )
            ],
            final_summary=(
                "当前有 1 条可沉淀候选 candidate-1："
                "Use tail_lines for final-line questions。"
            ),
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "review_queue_list")
    assert_visible_answer_contains(transcript, "可沉淀")
    assert_visible_answer_contains(transcript, "candidate-1")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_benchmark_case_passed(
        transcript,
        case_id="review-queue-list-candidates",
        category="memory_context",
        expected_tools=["review_queue_list"],
        max_visible_chars=900,
    )


async def test_review_queue_view_question_shows_compact_candidate_summary(tmp_path) -> None:
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="review queue view",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["查看第一个候选"],
            tool_steps=[
                ScenarioToolStep(
                    action="review_queue_view",
                    status="succeeded",
                    summary="Read review candidate candidate-1",
                    payload={
                        "candidate": {
                            "id": "candidate-1",
                            "kind": "skill_lesson",
                            "target_kind": "skill",
                            "summary": "Use concise tool summaries.",
                            "suggested_memory_kind": "failure_lesson",
                            "suggested_skill": "test-fix",
                            "confidence": 0.9,
                            "status": "pending",
                        }
                    },
                    args={"candidate_id": "candidate-1"},
                )
            ],
            final_summary="第一个候选：Use concise tool summaries。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "review_queue_view")
    assert_visible_answer_contains(transcript, "第一个候选")
    assert_visible_answer_contains(transcript, "Use concise tool summaries")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_benchmark_case_passed(
        transcript,
        case_id="review-queue-view-first-candidate",
        category="memory_context",
        expected_tools=["review_queue_view"],
        max_visible_chars=900,
    )


async def test_review_queue_accept_question_enters_confirmation_then_accepts(
    tmp_path,
) -> None:
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="review queue accept",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["接受这个 skill", "确认"],
            pending_confirmation={
                "id": "confirm-review-accept",
                "tool_call_id": "call_review_accept",
                "tool_name": "review_queue_accept",
                "arguments": {
                    "candidate_id": "candidate-1",
                    "target_kind": "skill",
                    "source_report": "reports/run.json",
                    "source_trace": "traces/run.jsonl",
                },
                "reason": "tool review_queue_accept requires confirmation",
                "risk_level": "high",
                "required_mode": "workspace-write",
                "preview": {
                    "candidate_id": "candidate-1",
                    "target_kind": "skill",
                    "source_report": "reports/run.json",
                    "source_trace": "traces/run.jsonl",
                    "effect": "accept_candidate",
                },
                "source": "agent_loop",
            },
            tool_steps=[
                ScenarioToolStep(
                    action="review_queue_accept",
                    status="succeeded",
                    summary="Accepted review candidate candidate-1",
                    payload={
                        "candidate_id": "candidate-1",
                        "candidate": {
                            "id": "candidate-1",
                            "kind": "skill_lesson",
                            "target_kind": "skill",
                            "summary": "Use concise tool summaries.",
                            "status": "accepted",
                        },
                        "accepted_guidance": {
                            "target_kind": "skill",
                            "candidate_id": "candidate-1",
                            "skill_path": "data/skills/test-fix/SKILL.md",
                        },
                    },
                    args={"candidate_id": "candidate-1", "target_kind": "skill"},
                )
            ],
            review_queue_candidates=[
                {
                    "id": "candidate-1",
                    "kind": "skill_lesson",
                    "target_kind": "skill",
                    "summary": "Use concise tool summaries.",
                    "evidence": {
                        "case_id": "review-queue-accept-skill",
                        "root_causes": ["verbose_tool_output"],
                    },
                    "suggested_skill": "test-fix",
                    "source_trace_path": "traces/run.jsonl",
                    "confidence": 0.9,
                    "status": "pending",
                }
            ],
            final_summary="已接受这个 skill：Use concise tool summaries。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "review_queue_accept")
    assert_visible_answer_contains(transcript, "工具调用需要确认")
    assert_visible_answer_contains(transcript, "已接受这个 skill")
    assert_visible_answer_contains(transcript, "accept_candidate")
    assert transcript.tool_calls == ["接受这个 skill", "接受这个 skill"]
    assert transcript.initial_observation_counts == [0, 1]
    assert_answer_is_concise(transcript, max_lines=14, max_chars=1000)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_benchmark_case_passed(
        transcript,
        case_id="review-queue-accept-skill",
        category="memory_context",
        expected_tools=["review_queue_accept"],
        max_visible_chars=1000,
    )


async def test_review_queue_reject_question_records_rejected_confirmation(
    tmp_path,
) -> None:
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="review queue reject",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["拒绝这个规则", "取消"],
            pending_confirmation={
                "id": "confirm-review-reject",
                "tool_call_id": "call_review_reject",
                "tool_name": "review_queue_reject",
                "arguments": {
                    "candidate_id": "rule-1",
                    "target_kind": "rule",
                    "source_report": "reports/run.json",
                    "source_trace": "traces/run.jsonl",
                },
                "reason": "tool review_queue_reject requires confirmation",
                "risk_level": "high",
                "required_mode": "workspace-write",
                "preview": {
                    "candidate_id": "rule-1",
                    "target_kind": "rule",
                    "source_report": "reports/run.json",
                    "source_trace": "traces/run.jsonl",
                    "effect": "reject_candidate",
                },
                "source": "agent_loop",
            },
            tool_steps=[
                ScenarioToolStep(
                    action="review_queue_reject",
                    status="rejected",
                    summary="Rejected review candidate rule-1",
                    payload={
                        "candidate_id": "rule-1",
                        "candidate": {
                            "id": "rule-1",
                            "kind": "tool_policy_lesson",
                            "target_kind": "rule",
                            "summary": "Use git before answering git status.",
                            "status": "rejected",
                        },
                    },
                    args={"candidate_id": "rule-1", "target_kind": "rule"},
                )
            ],
            final_summary="已拒绝这个规则：不会写入长期记忆。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_rejected_evidence_from_observation(transcript, "review_queue_reject")
    assert_visible_answer_contains(transcript, "已取消待确认的工具调用")
    assert_visible_answer_contains(transcript, "已拒绝这个规则")
    assert transcript.tool_calls == ["拒绝这个规则", "拒绝这个规则"]
    assert transcript.initial_observation_counts == [0, 1]
    assert_answer_is_concise(transcript, max_lines=14, max_chars=1000)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_benchmark_case_passed(
        transcript,
        case_id="review-queue-reject-rule",
        category="memory_context",
        expected_tools=["review_queue_reject"],
        max_visible_chars=1000,
        expects_dangerous_block=True,
    )
