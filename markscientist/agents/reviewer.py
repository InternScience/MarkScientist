from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from markscientist.agents.base import BaseScientistAgent
from markscientist.prompts import REVIEWER_ROLE_PROMPT, REVIEW_REQUEST_TEMPLATE, META_EVALUATION_TEMPLATE
from markscientist.taste import get_taste_profile
from markscientist.buddy import (
    JudgeBuddy,
    JudgePanel,
    ResearchScenario,
    ResearcherRole,
    JudgeSkill,
    get_judge_for_scenario,
    get_panel_for_scenario,
)

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

# Map task types to research scenarios for JudgeBuddy integration
TASK_TO_SCENARIO = {
    "factual_query": ResearchScenario.LITERATURE_REVIEW,
    "literature_review": ResearchScenario.LITERATURE_REVIEW,
    "code_analysis": ResearchScenario.CODE_REVIEW,
    "idea_proposal": ResearchScenario.IDEA_GENERATION,
    "experiment_design": ResearchScenario.EXPERIMENT_DESIGN,
    "writing_draft": ResearchScenario.SECTION_DRAFT,
    "data_analysis": ResearchScenario.RESULT_ANALYSIS,
    "problem_solving": ResearchScenario.CODE_REVIEW,
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


@dataclass
class MetaEvaluationResult:
    solver_assessment: Dict[str, Any] = field(default_factory=dict)
    proposer_assessment: Dict[str, Any] = field(default_factory=dict)
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
            "proposer_assessment": self.proposer_assessment,
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


@agent_role(name="reviewer", role_prompt=REVIEWER_ROLE_PROMPT, function_list=[])
class ReviewerAgent(BaseScientistAgent):
    """Unified review agent for artifacts and system-level meta-evaluation."""

    agent_type = "reviewer"

    def review(
        self,
        artifact: str,
        artifact_type: str = "auto",
        requirements: Optional[str] = None,
    ) -> ReviewResult:
        """Review an artifact and produce evaluation feedback."""
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

    def _parse_review_result(
        self, raw_output: str, buddy_name: Optional[str] = None
    ) -> ReviewResult:
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

        # Parse overall_score with normalization (handle 0-1 scale if model returns it)
        raw_score = float(data.get("overall_score", 0))
        # If score is between 0 and 1 (exclusive of 1), assume it's 0-1 scale and convert to 0-10
        if 0 < raw_score <= 1:
            raw_score = raw_score * 10
        review.overall_score = raw_score

        # Parse dimension_scores with same normalization
        dim_scores = data.get("dimension_scores", {})
        normalized_dims = {}
        for dim, score in dim_scores.items():
            score_val = float(score) if isinstance(score, (int, float)) else 0
            # Normalize 0-1 scores to 0-10
            if 0 < score_val <= 1:
                score_val = score_val * 10
            normalized_dims[dim] = score_val
        review.dimension_scores = normalized_dims

        review.verdict = data.get("verdict", "")
        review.summary = data.get("summary", "")
        review.strengths = data.get("strengths", [])
        review.weaknesses = data.get("weaknesses", [])
        review.confidence = float(data.get("confidence", 0))

        # Apply taste calibration if buddy_name is provided
        if buddy_name:
            profile = get_taste_profile()
            if profile.has_calibration(buddy_name):
                adjusted, meta = profile.apply_to_score(review.overall_score, buddy_name)
                review.metadata["taste_calibration"] = meta
                review.overall_score = adjusted

        return review

    def quick_score(self, artifact: str) -> Dict[str, Any]:
        """Quick evaluation returning only essential metrics."""
        review = self.review(artifact=artifact, artifact_type="auto")
        return {
            "task_type": review.task_type,
            "score": review.overall_score,
            "verdict": review.verdict or review.summary,
        }

    def evaluate(
        self,
        original_task: str,
        solver_output: str,
        proposal_info: Optional[str] = None,
        solver_trajectory_summary: Optional[str] = None,
        final_result: Optional[str] = None,
    ) -> MetaEvaluationResult:
        """Meta-evaluation of the Proposer-Solver interaction."""
        task = META_EVALUATION_TEMPLATE.format(
            original_task=original_task,
            solver_output=solver_output[:2000] if len(solver_output) > 2000 else solver_output,
            solver_trajectory_summary=solver_trajectory_summary or "Not provided",
            proposal_info=proposal_info or "Not provided",
            final_result=final_result or solver_output[:500],
        )
        result = self.run(task)
        evaluation = self._parse_evaluation_result(result.output)
        evaluation.termination_reason = result.termination_reason
        evaluation.metadata = dict(result.metadata)
        return evaluation

    def _parse_evaluation_result(self, raw_output: str) -> MetaEvaluationResult:
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
        evaluation.proposer_assessment = data.get("proposer_assessment", {})
        evaluation.system_insights = data.get("system_insights", {})
        evaluation.success_probability = float(data.get("success_probability", 0))
        evaluation.confidence = float(data.get("confidence", 0))
        evaluation.meta_summary = data.get("meta_summary", "")
        return evaluation

    # =========================================================================
    # Enhanced Review Methods with JudgeBuddy Integration
    # =========================================================================

    def review_with_buddy(
        self,
        artifact: str,
        scenario: Union[str, ResearchScenario],
        role: Optional[Union[str, ResearcherRole]] = None,
        skill: Optional[Union[str, JudgeSkill]] = None,
        requirements: Optional[str] = None,
    ) -> ReviewResult:
        """
        Review an artifact using a configured JudgeBuddy.

        Args:
            artifact: Content to evaluate
            scenario: Research scenario (e.g., "idea_generation", "experiment_design")
            role: Reviewer role (e.g., "senior_reviewer", "novelty_critic")
            skill: Scoring skill (e.g., "geval", "prometheus", "pairwise")
            requirements: Additional evaluation requirements

        Returns:
            ReviewResult with scores and feedback
        """
        # Create JudgeBuddy
        if isinstance(scenario, str):
            scenario = ResearchScenario(scenario)
        if isinstance(role, str) and role:
            role = ResearcherRole(role)
        if isinstance(skill, str) and skill:
            skill = JudgeSkill(skill)

        buddy = get_judge_for_scenario(scenario, role=role, skill=skill)

        # Build enhanced prompt with buddy's system prompt
        buddy_prompt = buddy.get_system_prompt()
        dimensions_str = ", ".join(buddy.dimensions)

        enhanced_requirements = f"""
{buddy_prompt}

Additional Requirements:
{requirements or "Evaluate using the dimensions and criteria specified above."}

Evaluate the following dimensions specifically: {dimensions_str}
Strictness level: {buddy.strictness}

IMPORTANT - Scoring Scale:
- overall_score: integer from 0-10 (10=excellent, 8-9=good, 5-7=acceptable, <5=poor)
- dimension_scores: each dimension should be scored 0-10
- confidence: float from 0.0 to 1.0
"""

        # Run review with enhanced prompt
        task = REVIEW_REQUEST_TEMPLATE.format(
            artifact_type=f"Scenario: {scenario.value}",
            content=artifact,
            requirements=enhanced_requirements,
        )

        result = self.run(task)
        review = self._parse_review_result(result.output, buddy_name=buddy.name)
        review.termination_reason = result.termination_reason

        # Preserve taste_calibration if applied, then merge with result metadata
        taste_cal = review.metadata.get("taste_calibration")
        review.metadata = dict(result.metadata)
        if taste_cal:
            review.metadata["taste_calibration"] = taste_cal

        review.metadata["judge_buddy"] = {
            "name": buddy.name,
            "role": buddy.role.value,
            "skill": buddy.skill.value,
            "scenario": scenario.value,
            "dimensions": buddy.dimensions,
        }

        return review

    def review_with_panel(
        self,
        artifact: str,
        scenario: Union[str, ResearchScenario],
        num_judges: int = 3,
        requirements: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Review an artifact using a panel of multiple JudgeBuddies.

        Args:
            artifact: Content to evaluate
            scenario: Research scenario
            num_judges: Number of judges in the panel (default: 3)
            requirements: Additional evaluation requirements

        Returns:
            Dict with individual reviews and aggregated scores
        """
        if isinstance(scenario, str):
            scenario = ResearchScenario(scenario)

        panel = get_panel_for_scenario(scenario, num_judges)

        # Collect reviews from each judge
        reviews = []
        for judge in panel.judges:
            review = self.review_with_buddy(
                artifact=artifact,
                scenario=scenario,
                role=judge.role,
                skill=judge.skill,
                requirements=requirements,
            )
            reviews.append({
                "judge": {
                    "name": judge.name,
                    "role": judge.role.value,
                    "skill": judge.skill.value,
                    "focus": judge.role_config.get("focus", ""),
                },
                "review": review.to_dict(),
            })

        # Aggregate scores
        scores = [r["review"]["overall_score"] for r in reviews if r["review"]["overall_score"] > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Aggregate dimension scores
        all_dimensions = {}
        for r in reviews:
            for dim, score in r["review"].get("dimension_scores", {}).items():
                if dim not in all_dimensions:
                    all_dimensions[dim] = []
                all_dimensions[dim].append(score)

        avg_dimensions = {
            dim: sum(scores) / len(scores)
            for dim, scores in all_dimensions.items()
            if scores
        }

        # Collect all weaknesses
        all_weaknesses = []
        for r in reviews:
            for w in r["review"].get("weaknesses", []):
                if isinstance(w, dict):
                    w["from_judge"] = r["judge"]["name"]
                all_weaknesses.append(w)

        return {
            "panel_intro": panel.get_panel_intro(),
            "scenario": scenario.value,
            "num_judges": num_judges,
            "individual_reviews": reviews,
            "aggregated": {
                "overall_score": avg_score,
                "dimension_scores": avg_dimensions,
                "score_variance": max(scores) - min(scores) if len(scores) > 1 else 0,
                "all_weaknesses": all_weaknesses,
            },
            "verdict": self._aggregate_verdict(reviews),
        }

    def _aggregate_verdict(self, reviews: List[Dict]) -> str:
        """Aggregate verdicts from multiple reviews."""
        verdicts = [r["review"].get("verdict", "") for r in reviews]

        # Simple majority voting
        verdict_counts = {}
        for v in verdicts:
            if v:
                verdict_counts[v] = verdict_counts.get(v, 0) + 1

        if not verdict_counts:
            return "needs_review"

        return max(verdict_counts, key=verdict_counts.get)

    def compare_artifacts(
        self,
        artifact_a: str,
        artifact_b: str,
        scenario: Union[str, ResearchScenario],
        role: Optional[Union[str, ResearcherRole]] = None,
    ) -> Dict[str, Any]:
        """
        Compare two artifacts using pairwise evaluation.

        Args:
            artifact_a: First artifact
            artifact_b: Second artifact
            scenario: Research scenario for context
            role: Reviewer role

        Returns:
            Dict with comparison result
        """
        if isinstance(scenario, str):
            scenario = ResearchScenario(scenario)
        if isinstance(role, str) and role:
            role = ResearcherRole(role)

        # Use pairwise skill for comparison
        buddy = get_judge_for_scenario(scenario, role=role, skill=JudgeSkill.PAIRWISE)

        comparison_prompt = f"""
{buddy.get_system_prompt()}

## Pairwise Comparison Task

Compare the following two artifacts and determine which is better.

### Artifact A
{artifact_a}

### Artifact B
{artifact_b}

### Evaluation Criteria
Dimensions: {", ".join(buddy.dimensions)}

### Output Format
Return JSON with:
- winner: "A" | "B" | "Tie"
- confidence: "high" | "medium" | "low"
- analysis: detailed comparison
- dimension_comparison: per-dimension winner
"""

        result = self.run(comparison_prompt)

        # Parse comparison result
        json_match = re.search(r"\{[\s\S]*\}", result.output)
        if json_match:
            try:
                comparison = json.loads(json_match.group())
            except (json.JSONDecodeError, ValueError):
                comparison = {"winner": "Tie", "analysis": result.output[:500]}
        else:
            comparison = {"winner": "Tie", "analysis": result.output[:500]}

        comparison["judge"] = {
            "name": buddy.name,
            "role": buddy.role.value,
            "scenario": scenario.value,
        }

        return comparison

    def validate_claims(
        self,
        claims: List[str],
        evidence: str,
        requirements: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate claims against evidence (result-to-claim style).

        Args:
            claims: List of claims to validate
            evidence: Evidence/results to check against
            requirements: Additional validation requirements

        Returns:
            Dict with claim validation results
        """
        buddy = get_judge_for_scenario(
            ResearchScenario.CLAIM_VALIDATION,
            role=ResearcherRole.SKEPTIC,
            skill=JudgeSkill.JUDGELM,
        )

        claims_text = "\n".join(f"- Claim {i+1}: {c}" for i, c in enumerate(claims))

        validation_prompt = f"""
{buddy.get_system_prompt()}

## Claim Validation Task

Validate whether the evidence supports the following claims.

### Claims to Validate
{claims_text}

### Evidence
{evidence}

### Additional Requirements
{requirements or "Be strict. Only mark claims as supported if the evidence clearly demonstrates them."}

### Output Format
Return JSON with:
- claims: list of {{
    "claim": original claim text,
    "supported": "yes" | "partial" | "no",
    "evidence_found": specific evidence supporting/refuting,
    "missing_evidence": what's needed to fully support,
    "confidence": "high" | "medium" | "low"
  }}
- overall_assessment: summary of claim support
- recommendation: "proceed" | "supplement" | "revise_claims"
"""

        result = self.run(validation_prompt)

        # Parse validation result
        json_match = re.search(r"\{[\s\S]*\}", result.output)
        if json_match:
            try:
                validation = json.loads(json_match.group())
            except (json.JSONDecodeError, ValueError):
                validation = {"overall_assessment": result.output[:500]}
        else:
            validation = {"overall_assessment": result.output[:500]}

        validation["judge"] = {
            "name": buddy.name,
            "role": buddy.role.value,
        }

        return validation
