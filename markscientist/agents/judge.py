from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from markscientist.config import get_config
from markscientist.harness import ensure_harness_on_path
from markscientist.agents.base import BaseScientistAgent
from markscientist.prompts import JUDGE_ROLE_PROMPT, REVIEW_REQUEST_TEMPLATE

ensure_harness_on_path(get_config().harness_path)

from agent_base import agent_role


TASK_TYPE_DIMENSIONS = {
    "factual_query": ["accuracy", "completeness", "clarity", "citation"],
    "literature_review": ["coverage", "synthesis", "organization", "citation"],
    "code_analysis": ["correctness", "depth", "clarity", "actionability"],
    "idea_proposal": ["novelty", "rigor", "feasibility", "clarity"],
    "experiment_design": ["methodology", "validity", "reproducibility", "ethics"],
    "writing_draft": ["structure", "clarity", "coherence", "grammar"],
    "data_analysis": ["accuracy", "interpretation", "visualization", "limitations"],
    "problem_solving": ["correctness", "efficiency", "explanation", "alternatives"],
}


@dataclass
class ReviewResult:
    task_type: str = "unknown"
    overall_score: float = 0.0
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    verdict: str = ""
    summary: str = ""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    raw_output: str = ""
    termination_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "overall_score": self.overall_score,
            "dimension_scores": self.dimension_scores,
            "verdict": self.verdict,
            "summary": self.summary,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "confidence": self.confidence,
            "termination_reason": self.termination_reason,
            "metadata": self.metadata,
        }

    def get_dimension_names(self) -> List[str]:
        return TASK_TYPE_DIMENSIONS.get(self.task_type, ["quality"])

    @property
    def output(self) -> str:
        return self.raw_output


@agent_role(name="judge", role_prompt=JUDGE_ROLE_PROMPT, function_list=[])
class JudgeAgent(BaseScientistAgent):
    """Evaluation agent for artifacts."""

    agent_type = "judge"

    def review(
        self,
        artifact: str,
        artifact_type: str = "auto",
        requirements: Optional[str] = None,
    ) -> ReviewResult:
        type_hint = (
            "Please infer the task type from the artifact."
            if artifact_type == "auto"
            else f"Task type hint: {artifact_type}"
        )
        task = REVIEW_REQUEST_TEMPLATE.format(
            artifact_type=type_hint,
            content=artifact,
            requirements=requirements or "Evaluate using task-appropriate criteria.",
        )
        result = self.run(task)
        review = self._parse_review_result(result.output)
        review.termination_reason = result.termination_reason
        review.metadata = dict(result.metadata)
        return review

    def _parse_review_result(self, raw_output: str) -> ReviewResult:
        review = ReviewResult(raw_output=raw_output)
        json_match = re.search(r"\{[\s\S]*\}", raw_output)
        if not json_match:
            review.summary = raw_output[:500]
            return review
        try:
            data = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            review.summary = raw_output[:500]
            return review
        review.task_type = data.get("task_type", "unknown")
        review.overall_score = float(data.get("overall_score", 0))
        review.dimension_scores = data.get("dimension_scores", {})
        review.verdict = data.get("verdict", "")
        review.summary = data.get("summary", "")
        review.strengths = data.get("strengths", [])
        review.weaknesses = data.get("weaknesses", [])
        review.confidence = float(data.get("confidence", 0))
        return review

    def quick_score(self, artifact: str) -> Dict[str, Any]:
        review = self.review(artifact=artifact, artifact_type="auto")
        return {
            "task_type": review.task_type,
            "score": review.overall_score,
            "verdict": review.verdict or review.summary,
        }
