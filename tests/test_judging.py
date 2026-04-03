import json

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import JudgeAgent, _build_review_prompt, _parse_review_output
from markscientist.judging import (
    JudgePerspective,
    JudgeScenario,
    JudgeSkill,
    build_judge_policy,
    default_project_panel,
    default_report_panel,
    load_taste_profile,
    policy_key_for,
)


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

    assert "## Project Review Panel" in prompt
    assert "## Report Review Panel" in prompt
    assert "## Reviewer 1" in prompt
    assert "## Reviewer 2" in prompt
    assert "scenario: project_definition" in prompt
    assert "perspective:" in prompt
    assert "skill:" in prompt


def test_default_panels_are_multi_reviewer_and_skill_aware():
    project_panel = default_project_panel()
    report_panel = default_report_panel()

    assert len(project_panel) == 3
    assert len(report_panel) == 3
    assert len({policy.perspective for policy in report_panel}) == 3
    assert len({policy.skill for policy in project_panel}) == 3


def test_build_judge_policy_uses_explicit_scenario():
    policy = build_judge_policy(
        JudgeScenario.CLAIM_VALIDATION,
        perspective=JudgePerspective.SKEPTIC,
        skill=JudgeSkill.JUDGELM,
    )

    assert policy.scenario == JudgeScenario.CLAIM_VALIDATION
    assert "evidence_support" in policy.dimensions


def test_load_taste_profile_is_empty_without_explicit_path():
    profile = load_taste_profile()
    adjusted, metadata = profile.apply(
        72.0,
        policy_key_for(
            build_judge_policy(
                JudgeScenario.RESEARCH_REPORT,
                perspective=JudgePerspective.SKEPTIC,
                skill=JudgeSkill.GEVAL,
            )
        ),
    )

    assert adjusted == 72.0
    assert metadata["calibration_applied"] is False


def test_load_taste_profile_applies_feedback_offsets(tmp_path):
    feedback_path = tmp_path / "feedback_history.jsonl"
    policy = build_judge_policy(
        JudgeScenario.RESEARCH_REPORT,
        perspective=JudgePerspective.SKEPTIC,
        skill=JudgeSkill.GEVAL,
    )
    feedback_path.write_text(
        "\n".join(
            [
                json.dumps({"policy_key": policy_key_for(policy), "user_reaction": "too_high"}),
                json.dumps({"policy_key": policy_key_for(policy), "user_reaction": "too_high"}),
                json.dumps({"policy_key": policy_key_for(policy), "user_reaction": "too_high"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = load_taste_profile(feedback_path=feedback_path, min_feedback_threshold=1)
    adjusted, metadata = profile.apply(72.0, policy_key_for(policy))

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
                "panel_reviews": [{"reviewer": "Reviewer 1", "perspective": "skeptic", "skill": "geval"}],
            },
            ensure_ascii=False,
        )
    )

    assert review.overall_score == 61.0
    assert review.confidence == 0.75
    assert review.panel_reviews[0]["perspective"] == "skeptic"


def test_judge_review_project_report_uses_explicit_report_panel():
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
            "panel_reviews": [
                {
                    "reviewer": "Reviewer 1",
                    "perspective": "skeptic",
                    "skill": "judgelm",
                    "project_score": 70,
                    "report_score": 58,
                    "summary": "Claims are still under-supported.",
                    "recommendation": "tighten claims",
                }
            ],
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
    assert review.metadata["report_scenario"] == "claim_validation"
    assert len(review.metadata["project_panel"]) == 3
    assert len(review.metadata["report_panel"]) == 3
    assert review.panel_reviews[0]["skill"] == "judgelm"
    assert "scenario: claim_validation" in agent._fake_run.last_prompt
