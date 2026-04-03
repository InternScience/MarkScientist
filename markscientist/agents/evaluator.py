from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from markscientist.agents.base import BaseScientistAgent
from markscientist.prompts import EVALUATOR_ROLE_PROMPT, META_EVALUATION_TEMPLATE

from agent_base import agent_role


@dataclass
class MetaEvaluationResult:
    solver_assessment: Dict[str, Any] = field(default_factory=dict)
    judge_assessment: Dict[str, Any] = field(default_factory=dict)
    system_insights: Dict[str, Any] = field(default_factory=dict)
    success_probability: float = 0.0
    confidence: float = 0.0
    meta_summary: str = ""
    raw_output: str = ""
    termination_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "solver_assessment": self.solver_assessment,
            "judge_assessment": self.judge_assessment,
            "system_insights": self.system_insights,
            "success_probability": self.success_probability,
            "confidence": self.confidence,
            "meta_summary": self.meta_summary,
            "termination_reason": self.termination_reason,
            "metadata": self.metadata,
        }

    @property
    def output(self) -> str:
        return self.raw_output


def _build_evaluation_prompt(
    original_prompt: str,
    solver_output: str,
    judge_review: str,
    solver_trace_summary: Optional[str] = None,
    final_result: Optional[str] = None,
) -> str:
    return META_EVALUATION_TEMPLATE.format(
        original_task=original_prompt,
        solver_output=solver_output[:2000] if len(solver_output) > 2000 else solver_output,
        solver_trajectory_summary=solver_trace_summary or "Not provided",
        judge_review=judge_review,
        final_result=final_result or solver_output[:500],
    )


def _parse_evaluation_output(raw_output: str) -> MetaEvaluationResult:
    evaluation = MetaEvaluationResult(raw_output=raw_output)
    json_match = re.search(r"\{[\s\S]*\}", raw_output)
    if not json_match:
        evaluation.meta_summary = raw_output[:500]
        return evaluation
    try:
        data = json.loads(json_match.group())
    except (json.JSONDecodeError, ValueError):
        evaluation.meta_summary = raw_output[:500]
        return evaluation
    evaluation.solver_assessment = data.get("solver_assessment", {})
    evaluation.judge_assessment = data.get("judge_assessment", {})
    evaluation.system_insights = data.get("system_insights", {})
    evaluation.success_probability = float(data.get("success_probability", 0))
    evaluation.confidence = float(data.get("confidence", 0))
    evaluation.meta_summary = data.get("meta_summary", "")
    return evaluation


@agent_role(name="evaluator", role_prompt=EVALUATOR_ROLE_PROMPT, function_list=[])
class EvaluatorAgent(BaseScientistAgent):
    """Meta-evaluator for Solver and Judge behavior."""

    agent_type = "evaluator"
