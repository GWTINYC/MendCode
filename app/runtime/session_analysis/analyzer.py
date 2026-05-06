from __future__ import annotations

from collections import Counter

from app.runtime.session_analysis.models import (
    AnalysisFinding,
    FindingSeverity,
    ObservationEvent,
    SessionAnalysisReport,
    SessionTranscript,
    ToolCallEvent,
    compact_text,
)

FINAL_ANSWER_VISIBLE_LIMIT = 3000
OBSERVATION_VISIBLE_LIMIT = 6000
FAILED_STATUSES = {
    "failed",
    "rejected",
    "timed_out",
    "permission_required",
    "needs_user_confirmation",
}
LOCAL_FACT_PATTERNS = [
    "当前目录",
    "当前文件夹",
    "工作区",
    "仓库",
    "最后一句",
    "文件",
    "README",
    "git",
]


def analyze_transcript(transcript: SessionTranscript) -> SessionAnalysisReport:
    expected_tools = _expected_tools(transcript.user_messages)
    missing_tools = _missing_tools(expected_tools, transcript)
    repeated_tools = _repeated_tools(transcript.tool_calls)
    failed_tools = _failed_tools(transcript.observations)
    oversized_outputs = _oversized_outputs(transcript)
    unsupported_claims = _unsupported_claims(transcript, missing_tools, failed_tools)
    risk_events = _risk_events(transcript.observations)
    root_causes = _root_causes(
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
    )
    recommendations = _recommendations(
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
    )
    return SessionAnalysisReport(
        session_id=transcript.session_id,
        source_path=transcript.source_path,
        input_kind=transcript.input_kind,
        user_messages=transcript.user_messages,
        final_answer_excerpt=compact_text(transcript.final_answer, max_chars=1200),
        tool_calls=transcript.tool_calls,
        observations=transcript.observations,
        expected_tools=expected_tools,
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
        root_causes=root_causes,
        recommendations=recommendations,
        confidence="high" if transcript.input_kind == "jsonl_trace" else "medium",
    )


def _expected_tools(user_messages: list[str]) -> list[AnalysisFinding]:
    text = "\n".join(user_messages).casefold()
    findings: list[AnalysisFinding] = []
    if any(term in text for term in ["当前文件夹", "当前目录", "列文件", "列一下", "ls"]):
        findings.append(
            _finding(
                "expected_directory_listing",
                "Expected directory listing tool",
                tools=["list_dir", "run_shell_command"],
            )
        )
    if "git status" in text or "git 状态" in text or "查看 git" in text:
        findings.append(
            _finding(
                "expected_git_status",
                "Expected git status tool",
                tools=["git", "run_shell_command"],
            )
        )
    if any(term in text for term in ["最后一句", "last sentence", "last line", "tail"]):
        findings.append(
            _finding(
                "expected_file_read",
                "Expected file read for precise file question",
                tools=["read_file"],
            )
        )
    if any(term in text for term in ["搜索", "查找", "rg ", "grep", "在哪"]):
        findings.append(
            _finding(
                "expected_code_search",
                "Expected code search tool",
                tools=["rg", "search_code", "glob_file_search"],
            )
        )
    if any(term in text for term in ["修复", "patch", "报错", "测试失败"]):
        findings.append(
            _finding(
                "expected_repair_chain",
                "Expected repair tool chain",
                tools=["read_file", "apply_patch", "run_command"],
            )
        )
    if any(term in text for term in ["删除", "rm ", "安装", "pip install", "push", "reset"]):
        findings.append(
            _finding(
                "expected_risk_event",
                "Expected permission or risk event",
                tools=["run_shell_command"],
            )
        )
    return findings


def _missing_tools(
    expected: list[AnalysisFinding], transcript: SessionTranscript
) -> list[AnalysisFinding]:
    observed = set(transcript_tool_names(transcript))
    findings: list[AnalysisFinding] = []
    for item in expected:
        tools = [str(tool) for tool in item.evidence.get("tools", [])]
        missing_group_tools = [tool for tool in tools if tool not in observed]
        if item.code != "expected_repair_chain" and len(missing_group_tools) < len(tools):
            continue
        if item.code == "expected_repair_chain" and not missing_group_tools:
            continue
        code = {
            "expected_directory_listing": "missing_directory_listing",
            "expected_git_status": "missing_git_status",
            "expected_file_read": "missing_file_read",
            "expected_code_search": "missing_code_search",
            "expected_repair_chain": "missing_repair_tool_chain",
            "expected_risk_event": "missing_risk_event",
        }.get(item.code, "missing_expected_tool")
        findings.append(
            _finding(
                code,
                f"Missing expected tool group: {', '.join(tools)}",
                tools=tools,
                missing_tools=missing_group_tools,
            )
        )
    return findings


def _repeated_tools(tool_calls: list[ToolCallEvent]) -> list[AnalysisFinding]:
    counts = Counter((call.tool_name, call.arguments_fingerprint) for call in tool_calls)
    repeated = [key for key, count in counts.items() if count > 1 and key[0] not in {"unknown"}]
    if not repeated:
        return []
    return [
        _finding(
            "repeated_tool_call",
            "Same tool and arguments were called repeatedly",
            severity="warning",
            repeated=[
                {"tool_name": tool, "count": counts[(tool, fingerprint)]}
                for tool, fingerprint in repeated
            ],
        )
    ]


def _failed_tools(observations: list[ObservationEvent]) -> list[AnalysisFinding]:
    failed = [obs for obs in observations if obs.status in FAILED_STATUSES]
    if not failed:
        return []
    return [
        _finding(
            "failed_tool_observation",
            "One or more tool observations failed or were rejected",
            severity="error",
            failed=[
                {"tool_name": obs.tool_name, "status": obs.status, "error": obs.error_excerpt}
                for obs in failed
            ],
        )
    ]


def _oversized_outputs(transcript: SessionTranscript) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    if len(transcript.final_answer) > FINAL_ANSWER_VISIBLE_LIMIT:
        findings.append(
            _finding(
                "oversized_final_answer",
                "Final answer is too long for a precise response",
                chars=len(transcript.final_answer),
            )
        )
    oversized_obs = [
        obs for obs in transcript.observations if obs.visible_chars > OBSERVATION_VISIBLE_LIMIT
    ]
    if oversized_obs:
        findings.append(
            _finding(
                "oversized_observation",
                "Tool observation visible output exceeds bounded report threshold",
                observations=[
                    {"tool_name": obs.tool_name, "visible_chars": obs.visible_chars}
                    for obs in oversized_obs
                ],
            )
        )
    return findings


def _unsupported_claims(
    transcript: SessionTranscript,
    missing_tools: list[AnalysisFinding],
    failed_tools: list[AnalysisFinding],
) -> list[AnalysisFinding]:
    final_answer = transcript.final_answer.strip()
    if not final_answer:
        return []
    if failed_tools and _looks_certain(final_answer):
        return [
            _finding(
                "unsupported_after_failed_tool",
                "Final answer is certain after failed tool observation",
                severity="error",
            )
        ]
    if missing_tools and _mentions_local_fact(final_answer):
        return [
            _finding(
                "unsupported_local_claim",
                "Final answer states local facts without required observation",
                severity="error",
            )
        ]
    return []


def _risk_events(observations: list[ObservationEvent]) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for observation in observations:
        if observation.status in {"needs_user_confirmation", "permission_required"}:
            findings.append(
                _finding(
                    "permission_confirmation_required",
                    "Tool required confirmation before execution",
                    tool_name=observation.tool_name,
                    risk_level=observation.risk_level,
                )
            )
        elif observation.status == "rejected" and (
            observation.risk_level in {"high", "critical"}
            or "permission" in observation.error_excerpt.casefold()
        ):
            findings.append(
                _finding(
                    "dangerous_tool_rejected",
                    "Dangerous or unauthorized tool was rejected",
                    tool_name=observation.tool_name,
                    risk_level=observation.risk_level,
                )
            )
    return findings


def _root_causes(**groups: list[AnalysisFinding]) -> list[AnalysisFinding]:
    causes: list[AnalysisFinding] = []
    if groups["missing_tools"]:
        causes.append(
            _finding(
                "tool_selection_gap",
                "Model did not call a required local tool",
                target="prompt_rule",
            )
        )
    if groups["failed_tools"] and groups["unsupported_claims"]:
        causes.append(
            _finding(
                "failed_observation_ignored",
                "Final response was not gated after tool failure",
                target="final_response_gate",
            )
        )
    if groups["repeated_tools"]:
        causes.append(
            _finding(
                "tool_repetition",
                "Agent repeated equivalent tool calls",
                target="context_compaction",
            )
        )
    if groups["oversized_outputs"]:
        causes.append(
            _finding(
                "context_waste",
                "Response or observation exceeded concise output budget",
                target="context_compaction",
            )
        )
    if groups["risk_events"]:
        causes.append(
            _finding(
                "permission_boundary",
                "Permission event must remain explicit and traceable",
                target="permission_policy",
            )
        )
    return causes


def _recommendations(**groups: list[AnalysisFinding]) -> list[AnalysisFinding]:
    recommendations: list[AnalysisFinding] = []
    if groups["missing_tools"]:
        recommendations.append(
            _finding(
                "recommend_prompt_rule",
                "Strengthen prompt rule for required tool use",
                target="prompt_rule",
            )
        )
        recommendations.append(
            _finding(
                "recommend_tool_schema", "Review tool schema discoverability", target="tool_schema"
            )
        )
    if groups["failed_tools"] and groups["unsupported_claims"]:
        recommendations.append(
            _finding(
                "recommend_final_response_gate",
                "Prevent certain local answers after failed observations",
                target="final_response_gate",
            )
        )
    if groups["repeated_tools"]:
        recommendations.append(
            _finding(
                "recommend_memory_or_compaction",
                "Reuse prior observations before repeated reads",
                target="memory",
            )
        )
    if groups["oversized_outputs"]:
        recommendations.append(
            _finding(
                "recommend_context_budget",
                "Compact long outputs before showing or storing them",
                target="context_compaction",
            )
        )
    if groups["risk_events"]:
        recommendations.append(
            _finding(
                "recommend_permission_policy",
                "Keep confirmation and denial behavior explicit",
                target="permission_policy",
            )
        )
    if any(groups.values()):
        recommendations.append(
            _finding(
                "recommend_benchmark_case",
                "Add or update a benchmark case for this failure pattern",
                target="benchmark_case",
            )
        )
    return recommendations


def transcript_tool_names(transcript: SessionTranscript) -> list[str]:
    return [call.tool_name for call in transcript.tool_calls] + [
        obs.tool_name for obs in transcript.observations
    ]


def _mentions_local_fact(text: str) -> bool:
    return any(pattern.casefold() in text.casefold() for pattern in LOCAL_FACT_PATTERNS)


def _looks_certain(text: str) -> bool:
    uncertain = ["无法", "不能确定", "没有成功", "需要", "请提供"]
    return not any(word in text for word in uncertain)


def _finding(
    code: str,
    summary: str,
    *,
    severity: FindingSeverity = "warning",
    **evidence: object,
) -> AnalysisFinding:
    return AnalysisFinding(code=code, severity=severity, summary=summary, evidence=evidence)
