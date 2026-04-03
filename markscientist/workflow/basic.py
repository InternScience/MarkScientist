from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from markscientist.agents.evaluator import EvaluatorAgent, MetaEvaluationResult
from markscientist.agents.evaluator import _build_evaluation_prompt, _parse_evaluation_output
from markscientist.agents.judge import JudgeAgent, ReviewResult, _build_review_prompt, _parse_review_output
from markscientist.agents.solver import SolverAgent
from markscientist.config import Config, get_config
from markscientist.prompts import IMPROVEMENT_REQUEST_TEMPLATE
from markscientist.trajectory.recorder import WorkflowTrajectoryRecorder


@dataclass
class WorkflowResult:
    prompt: str
    solver_output: str
    judge_review: Optional[ReviewResult] = None
    evaluator_assessment: Optional[MetaEvaluationResult] = None
    improved_output: Optional[str] = None
    final_score: float = 0.0
    success: bool = False
    iterations: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "solver_output": self.solver_output[:500] + "..." if len(self.solver_output) > 500 else self.solver_output,
            "judge_review": self.judge_review.to_dict() if self.judge_review else None,
            "evaluator_assessment": self.evaluator_assessment.to_dict() if self.evaluator_assessment else None,
            "improved_output": self.improved_output[:500] + "..." if self.improved_output and len(self.improved_output) > 500 else self.improved_output,
            "final_score": self.final_score,
            "success": self.success,
            "iterations": self.iterations,
            "metadata": self.metadata,
        }


class BasicResearchWorkflow:
    def __init__(
        self,
        config: Optional[Config] = None,
        improvement_threshold: float = 6.0,
        max_improvement_iterations: int = 2,
        enable_evaluator: bool = True,
        save_dir: Optional[Path] = None,
    ):
        self.config = config or get_config()
        self.improvement_threshold = improvement_threshold
        self.max_improvement_iterations = max_improvement_iterations
        self.enable_evaluator = enable_evaluator
        self.save_dir = save_dir or self.config.trajectory.save_dir

    def _new_solver(self, workspace_root: Path, trace_dir: Optional[Path], on_event=None) -> SolverAgent:
        return SolverAgent(
            config=self.config,
            workspace_root=workspace_root,
            trace_dir=trace_dir,
            on_event=on_event,
        )

    def _new_judge(self, workspace_root: Path, trace_dir: Optional[Path], on_event=None) -> JudgeAgent:
        return JudgeAgent(
            config=self.config,
            workspace_root=workspace_root,
            trace_dir=trace_dir,
            on_event=on_event,
        )

    def _new_evaluator(self, workspace_root: Path, trace_dir: Optional[Path], on_event=None) -> EvaluatorAgent:
        return EvaluatorAgent(
            config=self.config,
            workspace_root=workspace_root,
            trace_dir=trace_dir,
            on_event=on_event,
        )

    def run(
        self,
        prompt: str,
        workspace_root: Optional[Path] = None,
        on_event=None,
    ) -> WorkflowResult:
        workspace_root = workspace_root or self.config.workspace_root or Path.cwd()
        recorder = WorkflowTrajectoryRecorder(
            prompt=prompt,
            model_name=self.config.model.model_name,
            workspace_root=str(workspace_root),
            save_dir=self.save_dir if self.config.trajectory.auto_save else None,
        )

        solver = self._new_solver(workspace_root, recorder.trace_dir_for("solver"), on_event=on_event)
        solver_result = solver.run(prompt)
        recorder.capture_agent_result("solver", solver_result)

        solver_output = solver_result.output
        iterations = 1
        accepted_improved_output: Optional[str] = None

        judge = self._new_judge(workspace_root, recorder.trace_dir_for("judge"), on_event=on_event)
        judge_result = judge.run(_build_review_prompt(solver_output, artifact_type="auto"))
        judge_review = _parse_review_output(judge_result.output)
        judge_review.termination_reason = judge_result.termination_reason
        judge_review.metadata = dict(judge_result.metadata)
        recorder.capture_agent_result("judge", judge_review)

        improved_output: Optional[str] = None

        while (
            judge_review.overall_score < self.improvement_threshold
            and iterations < self.max_improvement_iterations
        ):
            improvement_prompt = IMPROVEMENT_REQUEST_TEMPLATE.format(
                original_output=solver_output,
                review_feedback=judge_review.raw_output,
            )
            improvement_solver = self._new_solver(workspace_root, recorder.trace_dir_for("solver"), on_event=on_event)
            improvement_result = improvement_solver.run(improvement_prompt)
            recorder.capture_agent_result("solver", improvement_result)
            improved_output = improvement_result.output
            iterations += 1

            improvement_judge = self._new_judge(workspace_root, recorder.trace_dir_for("judge"), on_event=on_event)
            improvement_judge_result = improvement_judge.run(_build_review_prompt(improved_output, artifact_type="auto"))
            judge_review = _parse_review_output(improvement_judge_result.output)
            judge_review.termination_reason = improvement_judge_result.termination_reason
            judge_review.metadata = dict(improvement_judge_result.metadata)
            recorder.capture_agent_result("judge", judge_review)

            if judge_review.overall_score >= self.improvement_threshold:
                solver_output = improved_output
                accepted_improved_output = improved_output

        evaluator_assessment = None
        final_output = solver_output
        if self.enable_evaluator:
            evaluator = self._new_evaluator(workspace_root, recorder.trace_dir_for("evaluator"), on_event=on_event)
            evaluator_result = evaluator.run(
                _build_evaluation_prompt(
                    original_prompt=prompt,
                    solver_output=solver_output,
                    judge_review=judge_review.raw_output,
                    final_result=final_output,
                )
            )
            evaluator_assessment = _parse_evaluation_output(evaluator_result.output)
            evaluator_assessment.termination_reason = evaluator_result.termination_reason
            evaluator_assessment.metadata = dict(evaluator_result.metadata)
            recorder.capture_agent_result("evaluator", evaluator_assessment)

        quality_scores = {"overall_score": judge_review.overall_score, **judge_review.dimension_scores}
        recorder.complete(
            final_output=final_output,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            quality_scores=quality_scores,
            metadata={"workspace_root": str(workspace_root)},
        )

        return WorkflowResult(
            prompt=prompt,
            solver_output=solver_output,
            judge_review=judge_review,
            evaluator_assessment=evaluator_assessment,
            improved_output=accepted_improved_output,
            final_score=judge_review.overall_score,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            metadata={
                "workflow_id": recorder.get_record().workflow_id,
                "workspace_root": str(workspace_root),
            },
        )
