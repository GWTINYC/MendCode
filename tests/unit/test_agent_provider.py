from app.agent.provider import AgentProviderInput, ProviderResponse, ScriptedAgentProvider


def test_scripted_provider_builds_initial_fix_actions() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="pytest failed",
            verification_commands=["python -m pytest -q"],
        )
    )

    assert response == ProviderResponse(
        status="succeeded",
        actions=[
            {
                "type": "tool_call",
                "action": "repo_status",
                "reason": "inspect repository state before attempting a fix",
                "args": {},
            },
            {
                "type": "tool_call",
                "action": "detect_project",
                "reason": "detect project type and likely verification commands",
                "args": {},
            },
            {
                "type": "tool_call",
                "action": "run_command",
                "reason": "run requested verification command",
                "args": {"command": "python -m pytest -q"},
            },
            {
                "type": "final_response",
                "status": "completed",
                "summary": "Agent loop completed requested verification commands",
            },
        ],
    )


def test_provider_response_rejects_success_without_actions() -> None:
    response = ProviderResponse.failed("provider timed out")

    assert response.status == "failed"
    assert response.actions == []
    assert response.observation.status == "failed"
    assert response.observation.summary == "Provider failed"
    assert response.observation.error_message == "provider timed out"


def test_provider_response_rejects_failed_without_observation() -> None:
    try:
        ProviderResponse(status="failed")
    except ValueError as exc:
        assert "failed provider responses require observation" in str(exc)
    else:
        raise AssertionError("ProviderResponse accepted failed status without observation")


def test_scripted_provider_rejects_missing_verification_commands() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="pytest failed",
            verification_commands=[],
        )
    )

    assert response.status == "failed"
    assert response.observation.status == "failed"
    assert response.observation.error_message == "at least one verification command is required"


def test_scripted_provider_can_include_patch_proposal_and_review_actions() -> None:
    provider = ScriptedAgentProvider()
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1 +1 @@
-return a - b
+return a + b
"""

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="fix add",
            verification_commands=["python check.py"],
            patch_proposal={
                "reason": "add should add operands",
                "files_to_modify": ["calculator.py"],
                "patch": patch,
            },
        )
    )

    assert response.status == "succeeded"
    actions = response.actions
    assert actions[3] == {
        "type": "patch_proposal",
        "reason": "add should add operands",
        "files_to_modify": ["calculator.py"],
        "patch": patch,
    }
    assert actions[4] == {
        "type": "tool_call",
        "action": "run_command",
        "reason": "verify patch proposal",
        "args": {"command": "python check.py"},
    }
    assert actions[5] == {
        "type": "tool_call",
        "action": "show_diff",
        "reason": "summarize worktree changes",
        "args": {},
    }


def test_scripted_provider_builds_failure_location_actions() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_failure_location_actions(
        failed_node="tests/test_calculator.py::test_add",
        file_path="tests/test_calculator.py",
        test_name="test_add",
    )

    assert response.status == "succeeded"
    assert response.actions == [
        {
            "type": "tool_call",
            "action": "read_file",
            "reason": "inspect failing test file",
            "args": {"relative_path": "tests/test_calculator.py", "max_chars": 12000},
        },
        {
            "type": "tool_call",
            "action": "search_code",
            "reason": "locate implementation related to failing test",
            "args": {"query": "test_add", "glob": "*.py", "max_results": 20},
        },
        {
            "type": "final_response",
            "status": "completed",
            "summary": "Failure location context collected",
        },
    ]


def test_scripted_provider_rejects_failure_location_without_file_path() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_failure_location_actions(
        failed_node=None,
        file_path=None,
        test_name=None,
    )

    assert response.status == "failed"
    assert response.observation.error_message == "failure insight did not include a file path"
