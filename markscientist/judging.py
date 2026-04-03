from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class JudgeScenario(str, Enum):
    PROJECT_DEFINITION = "project_definition"
    RESEARCH_REPORT = "research_report"
    CLAIM_VALIDATION = "claim_validation"
    REVISION_COMPARISON = "revision_comparison"


class JudgePerspective(str, Enum):
    SENIOR_REVIEWER = "senior_reviewer"
    METHODS_EXPERT = "methods_expert"
    LITERATURE_EXPERT = "literature_expert"
    REPRODUCIBILITY_ADVOCATE = "reproducibility_advocate"
    SKEPTIC = "skeptic"
    AREA_CHAIR = "area_chair"


class JudgeSkill(str, Enum):
    GEVAL = "geval"
    PROMETHEUS = "prometheus"
    PAIRWISE = "pairwise"
    JUDGELM = "judgelm"


SCENARIO_CONFIGS: Dict[JudgeScenario, Dict[str, Any]] = {
    JudgeScenario.PROJECT_DEFINITION: {
        "description": "Evaluate whether the prepared project is scientifically meaningful, grounded, executable, and non-toy.",
        "dimensions": ("grounding", "scope", "executability", "scientific_value", "non_toy_quality"),
        "strictness": "strict",
        "recommended_perspective": JudgePerspective.METHODS_EXPERT,
        "recommended_skill": JudgeSkill.PROMETHEUS,
    },
    JudgeScenario.RESEARCH_REPORT: {
        "description": "Evaluate the finished research report, evidence, figures, and deliverables as a complete scientific artifact.",
        "dimensions": ("methodology", "evidence", "results", "limitations", "reproducibility"),
        "strictness": "strict",
        "recommended_perspective": JudgePerspective.AREA_CHAIR,
        "recommended_skill": JudgeSkill.JUDGELM,
    },
    JudgeScenario.CLAIM_VALIDATION: {
        "description": "Check whether the claims in the report are actually supported by the available evidence.",
        "dimensions": ("evidence_support", "claim_scope", "overclaim_risk"),
        "strictness": "very_strict",
        "recommended_perspective": JudgePerspective.SKEPTIC,
        "recommended_skill": JudgeSkill.JUDGELM,
    },
    JudgeScenario.REVISION_COMPARISON: {
        "description": "Compare two report revisions and decide whether the new version is materially better.",
        "dimensions": ("improvement", "regression_risk", "evidence_gain", "checklist_progress"),
        "strictness": "strict",
        "recommended_perspective": JudgePerspective.SENIOR_REVIEWER,
        "recommended_skill": JudgeSkill.PAIRWISE,
    },
}


PERSPECTIVE_CONFIGS: Dict[JudgePerspective, Dict[str, str]] = {
    JudgePerspective.SENIOR_REVIEWER: {
        "title": "Senior Reviewer",
        "focus": "overall scientific quality and decision making",
        "guidance": (
            "Focus on the big picture, scientific significance, and whether the artifact "
            "deserves to pass a strong benchmark bar."
        ),
    },
    JudgePerspective.METHODS_EXPERT: {
        "title": "Methods Expert",
        "focus": "experimental design, scope control, and methodological rigor",
        "guidance": (
            "Focus on whether the task or report is methodologically sound, executable, "
            "well-controlled, and free of toy shortcuts."
        ),
    },
    JudgePerspective.LITERATURE_EXPERT: {
        "title": "Literature Expert",
        "focus": "positioning, prior work coverage, and fairness to existing work",
        "guidance": (
            "Focus on whether prior work is used correctly, whether important references "
            "are missing, and whether novelty claims are honest."
        ),
    },
    JudgePerspective.REPRODUCIBILITY_ADVOCATE: {
        "title": "Reproducibility Advocate",
        "focus": "artifact completeness and whether another researcher could reproduce the work",
        "guidance": (
            "Focus on code, figures, outputs, parameters, and whether the report exposes "
            "enough details to support real reproducibility."
        ),
    },
    JudgePerspective.SKEPTIC: {
        "title": "Skeptic",
        "focus": "unsupported claims, missing evidence, and overclaim detection",
        "guidance": (
            "Assume claims are not yet proven. Require direct evidence, detect overreach, "
            "and prefer narrow honest conclusions over broad ungrounded ones."
        ),
    },
    JudgePerspective.AREA_CHAIR: {
        "title": "Area Chair",
        "focus": "balanced final judgment across project quality, execution quality, and benchmark fit",
        "guidance": (
            "Integrate multiple criteria, weigh strengths against weaknesses, and decide "
            "whether the overall artifact clears a benchmark-quality threshold."
        ),
    },
}


SKILL_CONFIGS: Dict[JudgeSkill, Dict[str, Any]] = {
    JudgeSkill.GEVAL: {
        "description": "multi-dimensional rubric scoring with explicit reasoning",
        "bias_controls": ("dimension-by-dimension scoring", "explicit evidence tracing"),
    },
    JudgeSkill.PROMETHEUS: {
        "description": "strict rubric-based absolute grading",
        "bias_controls": ("rubric anchoring", "criterion-by-criterion judgment"),
    },
    JudgeSkill.PAIRWISE: {
        "description": "head-to-head revision comparison",
        "bias_controls": ("before-after comparison", "regression detection"),
    },
    JudgeSkill.JUDGELM: {
        "description": "evidence-heavy judgment with bias mitigation and claim scrutiny",
        "bias_controls": ("claim-evidence alignment", "overclaim suppression"),
    },
}


@dataclass(frozen=True)
class JudgePolicy:
    scenario: JudgeScenario
    perspective: JudgePerspective
    skill: JudgeSkill
    description: str
    dimensions: Tuple[str, ...]
    strictness: str
    focus: str
    guidance: str
    skill_description: str
    bias_controls: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "perspective": self.perspective.value,
            "skill": self.skill.value,
            "description": self.description,
            "dimensions": list(self.dimensions),
            "strictness": self.strictness,
            "focus": self.focus,
            "guidance": self.guidance,
            "skill_description": self.skill_description,
            "bias_controls": list(self.bias_controls),
        }

    def render(self, heading: str) -> str:
        lines = [
            f"## {heading}",
            f"- scenario: {self.scenario.value}",
            f"- perspective: {self.perspective.value} ({PERSPECTIVE_CONFIGS[self.perspective]['title']})",
            f"- skill: {self.skill.value}",
            f"- strictness: {self.strictness}",
            f"- focus: {self.focus}",
            f"- scenario_description: {self.description}",
            f"- perspective_guidance: {self.guidance}",
            f"- skill_description: {self.skill_description}",
            "- dimensions:",
        ]
        lines.extend(f"  - {dimension}" for dimension in self.dimensions)
        if self.bias_controls:
            lines.append("- bias_controls:")
            lines.extend(f"  - {control}" for control in self.bias_controls)
        return "\n".join(lines)


def build_judge_policy(
    scenario: JudgeScenario,
    perspective: Optional[JudgePerspective] = None,
    skill: Optional[JudgeSkill] = None,
) -> JudgePolicy:
    scenario_config = SCENARIO_CONFIGS[scenario]
    perspective = perspective or scenario_config["recommended_perspective"]
    skill = skill or scenario_config["recommended_skill"]
    perspective_config = PERSPECTIVE_CONFIGS[perspective]
    skill_config = SKILL_CONFIGS[skill]
    return JudgePolicy(
        scenario=scenario,
        perspective=perspective,
        skill=skill,
        description=str(scenario_config["description"]),
        dimensions=tuple(scenario_config["dimensions"]),
        strictness=str(scenario_config["strictness"]),
        focus=str(perspective_config["focus"]),
        guidance=str(perspective_config["guidance"]),
        skill_description=str(skill_config["description"]),
        bias_controls=tuple(skill_config["bias_controls"]),
    )


def default_project_policy() -> JudgePolicy:
    return build_judge_policy(JudgeScenario.PROJECT_DEFINITION)


def default_report_policy(scenario: JudgeScenario = JudgeScenario.RESEARCH_REPORT) -> JudgePolicy:
    if scenario not in {JudgeScenario.RESEARCH_REPORT, JudgeScenario.CLAIM_VALIDATION}:
        raise ValueError(f"Unsupported report scenario: {scenario.value}")
    return build_judge_policy(scenario)


@dataclass
class TasteCalibration:
    policy_key: str
    score_offset: float = 0.0
    agreement_count: int = 0
    disagree_count: int = 0
    too_high_count: int = 0
    too_low_count: int = 0

    @property
    def total_feedback(self) -> int:
        return self.agreement_count + self.disagree_count + self.too_high_count + self.too_low_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_key": self.policy_key,
            "score_offset": self.score_offset,
            "agreement_count": self.agreement_count,
            "disagree_count": self.disagree_count,
            "too_high_count": self.too_high_count,
            "too_low_count": self.too_low_count,
            "total_feedback": self.total_feedback,
        }


@dataclass
class TasteProfile:
    calibrations: Dict[str, TasteCalibration] = field(default_factory=dict)
    min_feedback_threshold: int = 3

    def apply(self, score: float, policy_key: str) -> Tuple[float, Dict[str, Any]]:
        calibration = self.calibrations.get(policy_key)
        metadata = {
            "policy_key": policy_key,
            "calibration_applied": False,
            "original_score": score,
            "offset": 0.0,
        }
        if calibration is None or calibration.total_feedback < self.min_feedback_threshold:
            return score, metadata
        adjusted_score = max(0.0, min(100.0, score + calibration.score_offset))
        metadata["calibration_applied"] = True
        metadata["offset"] = calibration.score_offset
        metadata["adjusted_score"] = adjusted_score
        metadata["feedback_count"] = calibration.total_feedback
        return adjusted_score, metadata


def load_taste_profile(
    feedback_path: Optional[Path] = None,
    min_feedback_threshold: int = 3,
) -> TasteProfile:
    if feedback_path is None:
        return TasteProfile(min_feedback_threshold=min_feedback_threshold)
    path = feedback_path
    if not path.exists():
        return TasteProfile(min_feedback_threshold=min_feedback_threshold)

    raw_counts: Dict[str, Dict[str, int]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                policy_key = (
                    record.get("policy_key")
                    or record.get("judge_perspective")
                    or record.get("reviewer_role")
                    or record.get("buddy_name")
                )
                reaction = record.get("user_reaction")
                if not policy_key or not reaction:
                    continue
                stats = raw_counts.setdefault(
                    str(policy_key),
                    {"agree": 0, "disagree": 0, "too_high": 0, "too_low": 0},
                )
                if reaction in stats:
                    stats[reaction] += 1
    except OSError:
        return TasteProfile(min_feedback_threshold=min_feedback_threshold)

    calibrations: Dict[str, TasteCalibration] = {}
    for policy_key, stats in raw_counts.items():
        offset = max(-20.0, min(20.0, (stats["too_low"] - stats["too_high"]) * 3.0))
        calibrations[policy_key] = TasteCalibration(
            policy_key=policy_key,
            score_offset=offset,
            agreement_count=stats["agree"],
            disagree_count=stats["disagree"],
            too_high_count=stats["too_high"],
            too_low_count=stats["too_low"],
        )
    return TasteProfile(calibrations=calibrations, min_feedback_threshold=min_feedback_threshold)
