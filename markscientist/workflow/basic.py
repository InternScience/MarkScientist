from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from markscientist.agents.challenger import ChallengerAgent
from markscientist.agents.judge import JudgeAgent, ReviewResult, _build_review_prompt, _parse_review_output
from markscientist.agents.solver import SolverAgent
from markscientist.config import Config, get_config
from markscientist.project import ensure_project_layout, load_checklist_text, read_text_if_exists
from markscientist.prompts import (
    CHALLENGE_REQUEST_TEMPLATE,
    SOLVER_IMPROVEMENT_GUIDANCE_TEMPLATE,
    SOLVER_REQUEST_TEMPLATE,
)
from markscientist.trajectory.recorder import WorkflowTrajectoryRecorder


@dataclass
class WorkflowResult:
    prompt: str
    workspace_root: str
    challenge_output: str
    solver_output: str
    judge_review: Optional[ReviewResult] = None
    final_score: float = 0.0
    success: bool = False
    iterations: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "workspace_root": self.workspace_root,
            "challenge_output": self.challenge_output[:500] + "..." if len(self.challenge_output) > 500 else self.challenge_output,
            "solver_output": self.solver_output[:500] + "..." if len(self.solver_output) > 500 else self.solver_output,
            "judge_review": self.judge_review.to_dict() if self.judge_review else None,
            "final_score": self.final_score,
            "success": self.success,
            "iterations": self.iterations,
            "metadata": self.metadata,
        }


class ResearchWorkflow:
    def __init__(
        self,
        config: Optional[Config] = None,
        improvement_threshold: float = 6.0,
        max_iterations: int = 2,
        save_dir: Optional[Path] = None,
    ):
        self.config = config or get_config()
        self.improvement_threshold = improvement_threshold
        self.max_iterations = max_iterations
        self.save_dir = save_dir or self.config.trajectory.save_dir

    def _new_challenger(self, workspace_root: Path, trace_dir: Optional[Path], on_event=None) -> ChallengerAgent:
        return ChallengerAgent(
            config=self.config,
            workspace_root=workspace_root,
            trace_dir=trace_dir,
            on_event=on_event,
        )

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

    def _judge_report(
        self,
        *,
        prompt: str,
        report_text: str,
        challenge_brief: str,
        checklist_text: str,
        workspace_root: Path,
        recorder: WorkflowTrajectoryRecorder,
        on_event=None,
    ) -> ReviewResult:
        judge = self._new_judge(workspace_root, recorder.trace_dir_for("judge"), on_event=on_event)
        judge_result = judge.run(
            _build_review_prompt(
                original_prompt=prompt,
                challenge_brief=challenge_brief,
                checklist_text=checklist_text,
                report_text=report_text,
            ),
            workspace_root=workspace_root,
        )
        review = _parse_review_output(judge_result.output)
        review.termination_reason = judge_result.termination_reason
        review.trace_path = judge_result.trace_path
        recorder.capture_agent_result("judge", review)
        return review

    def run(
        self,
        prompt: str,
        workspace_root: Optional[Path] = None,
        on_event=None,
    ) -> WorkflowResult:
        workspace_root = (workspace_root or self.config.workspace_root or Path.cwd()).expanduser().resolve()
        paths = ensure_project_layout(workspace_root)
        recorder = WorkflowTrajectoryRecorder(
            prompt=prompt,
            model_name=self.config.model.model_name,
            workspace_root=str(paths.workspace_root),
            save_dir=self.save_dir if self.config.trajectory.auto_save else None,
        )
        recorder.record.challenge_brief_path = str(paths.challenge_brief_path)
        recorder.record.checklist_path = str(paths.checklist_path)
        recorder.record.report_path = str(paths.report_path)

        challenger = self._new_challenger(paths.workspace_root, recorder.trace_dir_for("challenger"), on_event=on_event)
        challenge_result = challenger.run(
            CHALLENGE_REQUEST_TEMPLATE.format(original_prompt=prompt),
            workspace_root=paths.workspace_root,
        )
        recorder.capture_agent_result("challenger", challenge_result)

        solver = self._new_solver(paths.workspace_root, recorder.trace_dir_for("solver"), on_event=on_event)
        solver_result = solver.run(
            SOLVER_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                additional_guidance="Read the prepared project files and complete the project end-to-end.",
            ),
            workspace_root=paths.workspace_root,
        )
        recorder.capture_agent_result("solver", solver_result)

        iterations = 1
        challenge_brief = read_text_if_exists(paths.challenge_brief_path, default="challenge/brief.md is missing.")
        checklist_text = load_checklist_text(paths.checklist_path)
        report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
        judge_review = self._judge_report(
            prompt=prompt,
            report_text=report_text,
            challenge_brief=challenge_brief,
            checklist_text=checklist_text,
            workspace_root=paths.workspace_root,
            recorder=recorder,
            on_event=on_event,
        )

        while judge_review.overall_score < self.improvement_threshold and iterations < self.max_iterations:
            iterations += 1
            solver = self._new_solver(paths.workspace_root, recorder.trace_dir_for("solver"), on_event=on_event)
            solver_result = solver.run(
                SOLVER_REQUEST_TEMPLATE.format(
                    original_prompt=prompt,
                    additional_guidance=SOLVER_IMPROVEMENT_GUIDANCE_TEMPLATE.format(
                        judge_feedback=judge_review.raw_output,
                    ),
                ),
                workspace_root=paths.workspace_root,
            )
            recorder.capture_agent_result("solver", solver_result)
            report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
            judge_review = self._judge_report(
                prompt=prompt,
                report_text=report_text,
                challenge_brief=challenge_brief,
                checklist_text=checklist_text,
                workspace_root=paths.workspace_root,
                recorder=recorder,
                on_event=on_event,
            )

        final_output = read_text_if_exists(paths.report_path, default=solver_result.output)
        recorder.complete(
            final_output=final_output,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            quality_scores={"overall_score": judge_review.overall_score},
            metadata={
                "workspace_root": str(paths.workspace_root),
                "challenge_brief_path": str(paths.challenge_brief_path),
                "checklist_path": str(paths.checklist_path),
                "report_path": str(paths.report_path),
            },
        )

        return WorkflowResult(
            prompt=prompt,
            workspace_root=str(paths.workspace_root),
            challenge_output=challenge_result.output,
            solver_output=final_output,
            judge_review=judge_review,
            final_score=judge_review.overall_score,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            metadata={
                "workflow_id": recorder.record.workflow_id,
                "challenge_brief_path": str(paths.challenge_brief_path),
                "checklist_path": str(paths.checklist_path),
                "report_path": str(paths.report_path),
            },
        )
