from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from markscientist.agents.base import BaseScientistAgent
from markscientist.judging import (
    JudgePolicy,
    JudgeScenario,
    default_project_panel,
    default_report_panel,
    load_taste_profile,
    policy_key_for,
    render_policy_panel,
)
from markscientist.prompts import (
    JUDGE_REQUEST_TEMPLATE,
    JUDGE_ROLE_PROMPT,
)

from agent_base import agent_role


@dataclass
class ReviewResult:
    overall_score: float = 0.0
    project_score: float = 0.0
    report_score: float = 0.0
    verdict: str = ""
    summary: str = ""
    next_action: str = "solver_revision"
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    checklist_scores: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    raw_output: str = ""
    termination_reason: str = ""
    trace_path: str = ""
    panel_reviews: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "project_score": self.project_score,
            "report_score": self.report_score,
            "verdict": self.verdict,
            "summary": self.summary,
            "next_action": self.next_action,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "checklist_scores": self.checklist_scores,
            "confidence": self.confidence,
            "termination_reason": self.termination_reason,
            "trace_path": self.trace_path,
            "panel_reviews": self.panel_reviews,
            "metadata": self.metadata,
        }

    @property
    def output(self) -> str:
        return self.raw_output


def _extract_json_object(raw_output: str) -> Optional[Dict[str, Any]]:
    json_match = re.search(r"\{[\s\S]*\}", raw_output)
    if not json_match:
        return None
    try:
        return json.loads(json_match.group())
    except (json.JSONDecodeError, ValueError):
        return None


def _build_review_prompt(
    *,
    original_prompt: str,
    instructions_text: str,
    challenge_brief: str,
    checklist_text: str,
    judge_materials_text: str,
    report_text: str,
    project_panel: Optional[List[JudgePolicy]] = None,
    report_panel: Optional[List[JudgePolicy]] = None,
) -> str:
    project_panel = list(project_panel or default_project_panel())
    report_panel = list(report_panel or default_report_panel())
    return JUDGE_REQUEST_TEMPLATE.format(
        original_prompt=original_prompt,
        instructions_text=instructions_text,
        challenge_brief=challenge_brief,
        checklist_text=checklist_text,
        judge_materials_text=judge_materials_text or "No judge-only materials were provided.",
        report_text=report_text,
        project_policy_block=render_policy_panel("Project Review Panel", tuple(project_panel)),
        report_policy_block=render_policy_panel("Report Review Panel", tuple(report_panel)),
    )


def _parse_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        named_confidence = {
            "very low": 0.1,
            "low": 0.25,
            "medium": 0.5,
            "moderate": 0.5,
            "high": 0.75,
            "very high": 0.9,
        }
        if lowered in named_confidence:
            return named_confidence[lowered]
        try:
            return float(lowered)
        except ValueError:
            return 0.0
    return 0.0


def _parse_review_output(raw_output: str) -> ReviewResult:
    review = ReviewResult(raw_output=raw_output)
    data = _extract_json_object(raw_output)
    if data is None:
        review.summary = raw_output[:500]
        return review
    overall_score = data.get("overall_score")
    overall_value = float(overall_score or 0)
    review.project_score = float(data.get("project_score", overall_value))
    review.report_score = float(data.get("report_score", overall_value))
    if overall_score is None and (review.project_score or review.report_score):
        review.overall_score = min(
            review.project_score or review.report_score,
            review.report_score or review.project_score,
        )
    else:
        review.overall_score = overall_value
    review.verdict = data.get("verdict", "")
    review.summary = data.get("summary", "")
    next_action = str(data.get("next_action", "solver_revision")).strip().lower()
    review.next_action = "rechallenge" if next_action == "rechallenge" else "solver_revision"
    review.strengths = data.get("strengths", [])
    review.weaknesses = data.get("weaknesses", [])
    review.suggestions = data.get("suggestions", [])
    review.checklist_scores = data.get("checklist_scores", [])
    review.confidence = _parse_confidence(data.get("confidence", 0))
    panel_reviews = data.get("panel_reviews")
    if isinstance(panel_reviews, list):
        review.panel_reviews = [item for item in panel_reviews if isinstance(item, dict)]
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        review.metadata = metadata
    return review


def _apply_taste_calibration(
    review: ReviewResult,
    *,
    project_panel: List[JudgePolicy],
    report_panel: List[JudgePolicy],
    feedback_path: Optional[Path] = None,
) -> None:
    if feedback_path is None:
        return
    profile = load_taste_profile(feedback_path=feedback_path)

    def _average_adjusted_score(score: float, panel: List[JudgePolicy], channel: str) -> tuple[float, Dict[str, Any]]:
        applied_scores: List[float] = []
        reviewer_meta: List[Dict[str, Any]] = []
        for policy in panel:
            adjusted_score, metadata = profile.apply(score, policy_key_for(policy))
            reviewer_meta.append(
                {
                    "policy_key": policy_key_for(policy),
                    "perspective": policy.perspective.value,
                    "skill": policy.skill.value,
                    **metadata,
                }
            )
            applied_scores.append(adjusted_score)
        calibration_applied = any(item["calibration_applied"] for item in reviewer_meta)
        aggregate_score = sum(applied_scores) / len(applied_scores) if applied_scores else score
        return aggregate_score, {
            "channel": channel,
            "calibration_applied": calibration_applied,
            "reviewers": reviewer_meta,
            "adjusted_score": aggregate_score,
        }

    project_score, project_meta = _average_adjusted_score(review.project_score, project_panel, "project")
    report_score, report_meta = _average_adjusted_score(review.report_score, report_panel, "report")
    overall_score = min(project_score, report_score) if (project_score or report_score) else review.overall_score
    overall_meta = {
        "calibration_applied": bool(project_meta["calibration_applied"] or report_meta["calibration_applied"]),
        "policy_keys": [policy_key_for(policy) for policy in (*project_panel, *report_panel)],
    }
    review.project_score = project_score
    review.report_score = report_score
    if overall_meta["calibration_applied"]:
        review.overall_score = overall_score
    review.metadata["taste_calibration"] = {
        "project": project_meta,
        "report": report_meta,
        "overall": overall_meta,
    }


@agent_role(name="judge", role_prompt=JUDGE_ROLE_PROMPT, function_list=[])
class JudgeAgent(BaseScientistAgent):
    """Strict report reviewer for prepared research projects."""

    agent_type = "judge"

    def review_project_report(
        self,
        *,
        original_prompt: str,
        instructions_text: str,
        challenge_brief: str,
        checklist_text: str,
        judge_materials_text: str,
        report_text: str,
        report_scenario: JudgeScenario = JudgeScenario.RESEARCH_REPORT,
        taste_feedback_path: Optional[Path] = None,
        workspace_root=None,
    ) -> ReviewResult:
        project_panel = list(default_project_panel())
        report_panel = list(default_report_panel(report_scenario))
        result = self.run(
            _build_review_prompt(
                original_prompt=original_prompt,
                instructions_text=instructions_text,
                challenge_brief=challenge_brief,
                checklist_text=checklist_text,
                judge_materials_text=judge_materials_text,
                report_text=report_text,
                project_panel=project_panel,
                report_panel=report_panel,
            ),
            workspace_root=workspace_root,
        )
        review = _parse_review_output(result.output)
        review.termination_reason = result.termination_reason
        review.trace_path = result.trace_path
        review.metadata.update(
            {
                "report_scenario": report_scenario.value,
                "project_panel": [policy.to_dict() for policy in project_panel],
                "report_panel": [policy.to_dict() for policy in report_panel],
            }
        )
        _apply_taste_calibration(
            review,
            project_panel=project_panel,
            report_panel=report_panel,
            feedback_path=taste_feedback_path,
        )
        return review
