import json

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import JudgeAgent, _build_review_prompt, _parse_review_output
from markscientist.judging import JudgeScenario, default_report_policy, load_taste_profile


def _stub_judge_agent(payload):
    agent = object.__new__(JudgeAgent)

    def fake_run(prompt, workspace_root=None):
        fake_run.last_prompt = prompt
        fake_run.last_workspace_root = workspace_root
        return AgentResult(
            output=json.dumps(payload, ensure_ascii=False),
            success=True,
            termination_reason="result",
            trace_path="trace.jsonl",
        )

    fake_run.last_prompt = ""
    fake_run.last_workspace_root = None
    agent.run = fake_run
    agent._fake_run = fake_run
    return agent


def test_build_review_prompt_includes_policy_blocks():
    prompt = _build_review_prompt(
        original_prompt="Study the dataset.",
        instructions_text="Write report/report.md.",
        challenge_brief="Benchmark-style brief.",
        checklist_text="Need strong claim support and a main figure.",
        judge_materials_text="Judge-only hidden rubric.",
        report_text="# Report",
    )

    assert "## Project Review Policy" in prompt
    assert "## Report Review Policy" in prompt
    assert "scenario: project_definition" in prompt
    assert "perspective:" in prompt
    assert "skill:" in prompt


def test_default_report_policy_uses_explicit_scenario():
    policy = default_report_policy(JudgeScenario.CLAIM_VALIDATION)

    assert policy.scenario == JudgeScenario.CLAIM_VALIDATION
    assert "evidence_support" in policy.dimensions


def test_load_taste_profile_is_empty_without_explicit_path():
    profile = load_taste_profile()
    adjusted, metadata = profile.apply(72.0, "skeptic")

    assert adjusted == 72.0
    assert metadata["calibration_applied"] is False


def test_load_taste_profile_applies_feedback_offsets(tmp_path):
    feedback_path = tmp_path / "feedback_history.jsonl"
    feedback_path.write_text(
        "\n".join(
            [
                json.dumps({"judge_perspective": "skeptic", "user_reaction": "too_high"}),
                json.dumps({"judge_perspective": "skeptic", "user_reaction": "too_high"}),
                json.dumps({"judge_perspective": "skeptic", "user_reaction": "too_high"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = load_taste_profile(feedback_path=feedback_path, min_feedback_threshold=1)
    adjusted, metadata = profile.apply(72.0, "skeptic")

    assert adjusted < 72.0
    assert metadata["calibration_applied"] is True
    assert metadata["offset"] < 0


def test_review_result_parses_named_confidence():
    review = _parse_review_output(
        json.dumps(
            {
                "overall_score": 61,
                "project_score": 74,
                "report_score": 56,
                "summary": "Needs stronger evidence.",
                "confidence": "high",
            },
            ensure_ascii=False,
        )
    )

    assert review.overall_score == 61.0
    assert review.confidence == 0.75


def test_judge_review_project_report_uses_explicit_report_policy():
    agent = _stub_judge_agent(
        {
            "overall_score": 58,
            "project_score": 70,
            "report_score": 58,
            "summary": "Claim support is incomplete.",
            "next_action": "solver_revision",
            "strengths": ["Project is grounded."],
            "weaknesses": ["Claims remain under-supported."],
            "suggestions": ["Tighten claims and add direct evidence."],
            "confidence": "medium",
        }
    )

    review = JudgeAgent.review_project_report(
        agent,
        original_prompt="Review the current report.",
        instructions_text="Write report/report.md.",
        challenge_brief="Benchmark-style brief.",
        checklist_text="Use strict claim validation.",
        judge_materials_text="Judge-only notes.",
        report_text="# Report",
        report_scenario=JudgeScenario.CLAIM_VALIDATION,
    )

    assert review.report_score == 58.0
    assert review.metadata["report_policy"]["scenario"] == "claim_validation"
    assert "scenario: claim_validation" in agent._fake_run.last_prompt
