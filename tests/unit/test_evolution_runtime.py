from app.evolution.lesson_builder import build_lesson_candidates
from app.evolution.models import EvolutionTurnInput
from app.evolution.runtime import EvolutionRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def test_evolution_runtime_generates_failure_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="修复测试",
            turn_status="failed",
            final_response="Provider failed",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={},
        )
    )

    assert result.signals == ["turn_failed"]
    assert result.generated_candidates[0].kind == "failure_lesson"
    assert memory_runtime.list_candidates()[0].summary.startswith("Turn failed")


def test_evolution_runtime_generates_rejected_tool_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="查看状态",
            turn_status="failed",
            final_response="tool rejected",
            trace_path="trace.jsonl",
            tool_steps=[
                {
                    "index": 1,
                    "action": {"type": "tool_call", "action": "apply_patch"},
                    "observation": {
                        "status": "rejected",
                        "summary": "tool is not allowed",
                        "error_message": "tool is not allowed in this turn",
                    },
                }
            ],
            context_metrics={},
        )
    )

    assert "tool_rejected" in result.signals
    assert result.generated_candidates[0].kind == "tool_policy_lesson"


def test_lesson_builder_compacts_rejected_tool_evidence() -> None:
    large_patch = "diff --git a/secret.py b/secret.py\n" + "secret_value = 'token'\n" * 500
    turn = EvolutionTurnInput(
        user_message="apply unsafe patch",
        turn_status="failed",
        final_response="tool rejected",
        trace_path="trace.jsonl",
        tool_steps=[
            {
                "index": 1,
                "action": {
                    "type": "tool_call",
                    "action": "apply_patch",
                    "reason": "unsafe write",
                    "args": {"patch": large_patch, "path": "secret.py"},
                },
                "observation": {
                    "status": "rejected",
                    "summary": "tool is not allowed",
                    "error_message": "permission denied",
                    "payload": {"patch": large_patch, "content": large_patch},
                },
            }
        ],
        context_metrics={},
    )

    signals, candidates = build_lesson_candidates(turn)
    evidence = candidates[0].evidence

    assert "tool_rejected" in signals
    assert candidates[0].kind == "tool_policy_lesson"
    assert "secret_value" not in str(evidence)
    assert evidence["action"]["arg_keys"] == ["patch", "path"]
    assert evidence["observation"]["payload_keys"] == ["content", "patch"]


def test_evolution_runtime_generates_repeated_read_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="读文件",
            turn_status="completed",
            final_response="done",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={"repeated_read_file_count": 2, "read_file_count": 4},
        )
    )

    assert "repeated_read_file" in result.signals
    assert result.generated_candidates[0].kind == "context_lesson"


def test_evolution_runtime_preserves_candidates_when_enqueue_fails(
    tmp_path,
    monkeypatch,
) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    def fail_enqueue(candidate):
        raise OSError("review queue unavailable")

    monkeypatch.setattr(memory_runtime, "enqueue_candidate", fail_enqueue)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="读文件",
            turn_status="completed",
            final_response="done",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={"repeated_read_file_count": 2, "read_file_count": 4},
        )
    )

    assert "repeated_read_file" in result.signals
    assert result.generated_candidates[0].kind == "context_lesson"
    assert result.error is not None
    assert result.error["type"] == "OSError"
    assert result.error["message"] == "review queue unavailable"


def test_evolution_runtime_generates_verification_recovered_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="修测试",
            turn_status="completed",
            final_response="fixed",
            trace_path="trace.jsonl",
            tool_steps=[
                {
                    "index": 1,
                    "action": {"type": "tool_call", "action": "run_command"},
                    "observation": {"status": "failed", "summary": "pytest failed"},
                },
                {
                    "index": 2,
                    "action": {"type": "tool_call", "action": "run_command"},
                    "observation": {"status": "succeeded", "summary": "pytest passed"},
                },
            ],
            context_metrics={},
        )
    )

    assert "verification_recovered" in result.signals
    assert result.generated_candidates[0].kind == "test_fix_lesson"
    assert result.generated_candidates[0].suggested_skill == "test-fix"


def test_evolution_runtime_skips_ordinary_success(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="列目录",
            turn_status="completed",
            final_response="done",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={"repeated_read_file_count": 0},
        )
    )

    assert result.generated_candidates == []
    assert result.skipped_reason == "no evolution signals"
    assert memory_runtime.list_candidates() == []


def test_lesson_builder_is_deterministic_for_identical_turn_input() -> None:
    turn = EvolutionTurnInput(
        user_message="修复测试",
        turn_status="failed",
        final_response="Provider failed",
        trace_path="trace.jsonl",
        tool_steps=[
            {
                "index": 1,
                "action": {"type": "tool_call", "action": "apply_patch"},
                "observation": {"status": "rejected", "summary": "tool rejected"},
            }
        ],
        context_metrics={"repeated_read_file_count": 1, "read_file_count": 2},
    )

    first_signals, first_candidates = build_lesson_candidates(turn)
    second_signals, second_candidates = build_lesson_candidates(turn)

    assert second_signals == first_signals
    assert [candidate.model_dump(mode="json") for candidate in second_candidates] == [
        candidate.model_dump(mode="json") for candidate in first_candidates
    ]
