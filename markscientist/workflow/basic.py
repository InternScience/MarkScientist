from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from markscientist.agents.challenger import ChallengerAgent
from markscientist.agents.judge import JudgeAgent, ReviewResult
from markscientist.judging import JudgeScenario
from markscientist.agents.solver import SolverAgent
from markscientist.config import Config, get_config
from markscientist.project import (
    detect_solver_owned_file_changes,
    describe_workspace_inputs,
    ensure_project_layout,
    load_checklist_text,
    load_judge_materials_text,
    missing_public_contract_files,
    read_text_if_exists,
    snapshot_solver_owned_files,
)
from markscientist.prompts import (
    CHALLENGE_REQUEST_TEMPLATE,
    CHALLENGER_IMPROVEMENT_GUIDANCE_TEMPLATE,
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
        improvement_threshold: float = 50.0,
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
        instructions_text: str,
        challenge_brief: str,
        checklist_text: str,
        judge_materials_text: str,
        project_root: Path,
        recorder: WorkflowTrajectoryRecorder,
        on_event=None,
    ) -> ReviewResult:
        judge = self._new_judge(project_root, recorder.trace_dir_for("judge"), on_event=on_event)
        review = judge.review_project_report(
            original_prompt=prompt,
            instructions_text=instructions_text,
            challenge_brief=challenge_brief,
            checklist_text=checklist_text,
            judge_materials_text=judge_materials_text,
            report_text=report_text,
            report_scenario=JudgeScenario.RESEARCH_REPORT,
            workspace_root=project_root,
        )
        recorder.capture_agent_result("judge", review)
        return review

    def _run_challenger_phase(
        self,
        *,
        prompt: str,
        input_inventory: Dict[str, str],
        additional_guidance: str,
        paths,
        recorder: WorkflowTrajectoryRecorder,
        on_event=None,
    ):
        solver_owned_before = snapshot_solver_owned_files(paths)

        def _challenge_request(guidance: str) -> str:
            return CHALLENGE_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                data_inventory=input_inventory["data_inventory"],
                related_work_inventory=input_inventory["related_work_inventory"],
                additional_guidance=guidance,
            )

        challenger = self._new_challenger(paths.public_root, recorder.trace_dir_for("challenger"), on_event=on_event)
        challenge_result = challenger.run(
            _challenge_request(additional_guidance),
            workspace_root=paths.public_root,
        )
        recorder.capture_agent_result("challenger", challenge_result)

        solver_owned_after = snapshot_solver_owned_files(paths)
        forbidden_changes = detect_solver_owned_file_changes(solver_owned_before, solver_owned_after)
        if forbidden_changes:
            raise RuntimeError(
                "Challenger modified Solver-owned artifacts during project preparation: "
                + ", ".join(forbidden_changes)
            )

        missing_files = missing_public_contract_files(paths)
        if not missing_files:
            return challenge_result

        repair_guidance = (
            additional_guidance
            + "\n\nThe previous Challenger pass did not create all required public project-definition files. "
            + "Create the missing files now and stop once they exist. "
            + "Missing files: "
            + ", ".join(f"`{path}`" for path in missing_files)
            + ". Do not do Solver work such as writing analysis code, outputs, figures, or `report/report.md`."
        )
        challenger = self._new_challenger(paths.public_root, recorder.trace_dir_for("challenger"), on_event=on_event)
        challenge_result = challenger.run(
            _challenge_request(repair_guidance),
            workspace_root=paths.public_root,
        )
        recorder.capture_agent_result("challenger", challenge_result)

        solver_owned_after = snapshot_solver_owned_files(paths)
        forbidden_changes = detect_solver_owned_file_changes(solver_owned_before, solver_owned_after)
        if forbidden_changes:
            raise RuntimeError(
                "Challenger modified Solver-owned artifacts during project preparation: "
                + ", ".join(forbidden_changes)
            )

        missing_files = missing_public_contract_files(paths)
        if missing_files:
            raise RuntimeError(
                "Challenger did not create the required public project-definition files: "
                + ", ".join(missing_files)
            )
        return challenge_result

    def run(
        self,
        prompt: str,
        workspace_root: Optional[Path] = None,
        on_event=None,
    ) -> WorkflowResult:
        project_root = (workspace_root or self.config.workspace_root or Path.cwd()).expanduser().resolve()
        paths = ensure_project_layout(project_root)
        input_inventory = describe_workspace_inputs(paths.public_root)
        recorder = WorkflowTrajectoryRecorder(
            prompt=prompt,
            model_name=self.config.model.model_name,
            workspace_root=str(paths.project_root),
            save_dir=self.save_dir if self.config.trajectory.auto_save else None,
        )
        recorder.record.challenge_brief_path = str(paths.challenge_brief_path)
        recorder.record.checklist_path = str(paths.checklist_path)
        recorder.record.report_path = str(paths.report_path)

        challenge_result = self._run_challenger_phase(
            prompt=prompt,
            input_inventory=input_inventory,
            additional_guidance=(
                "Prepare only the initial public research project definition for the Solver. "
                "Do not execute the project, write the report, generate final outputs, or score the result yourself. "
                "Those are downstream Solver and Judge responsibilities."
            ),
            paths=paths,
            recorder=recorder,
            on_event=on_event,
        )

        solver = self._new_solver(paths.public_root, recorder.trace_dir_for("solver"), on_event=on_event)
        solver_result = solver.run(
            SOLVER_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                data_inventory=input_inventory["data_inventory"],
                related_work_inventory=input_inventory["related_work_inventory"],
                additional_guidance="Read the prepared project files and complete the project end-to-end.",
            ),
            workspace_root=paths.public_root,
        )
        recorder.capture_agent_result("solver", solver_result)

        iterations = 1
        challenge_output = challenge_result.output
        instructions_text = read_text_if_exists(paths.instructions_path, default="INSTRUCTIONS.md is missing.")
        challenge_brief = read_text_if_exists(paths.challenge_brief_path, default="challenge/brief.md is missing.")
        checklist_text = load_checklist_text(paths.checklist_path)
        judge_materials_text = load_judge_materials_text(paths)
        report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
        judge_review = self._judge_report(
            prompt=prompt,
            report_text=report_text,
            instructions_text=instructions_text,
            challenge_brief=challenge_brief,
            checklist_text=checklist_text,
            judge_materials_text=judge_materials_text,
            project_root=paths.project_root,
            recorder=recorder,
            on_event=on_event,
        )

        while judge_review.overall_score < self.improvement_threshold and iterations < self.max_iterations:
            iterations += 1
            if judge_review.next_action == "rechallenge":
                challenge_result = self._run_challenger_phase(
                    prompt=prompt,
                    input_inventory=input_inventory,
                    additional_guidance=CHALLENGER_IMPROVEMENT_GUIDANCE_TEMPLATE.format(
                        judge_feedback=judge_review.raw_output,
                    )
                    + "\n\nDo not execute the project, write the report, generate final outputs, or score the result yourself. "
                    + "Only revise the public project-definition files.",
                    paths=paths,
                    recorder=recorder,
                    on_event=on_event,
                )
                challenge_output = challenge_result.output
                instructions_text = read_text_if_exists(paths.instructions_path, default="INSTRUCTIONS.md is missing.")
                challenge_brief = read_text_if_exists(paths.challenge_brief_path, default="challenge/brief.md is missing.")
                checklist_text = load_checklist_text(paths.checklist_path)
                judge_materials_text = load_judge_materials_text(paths)
                solver_guidance = (
                    "The Challenger revised the project definition. "
                    "Read the updated challenge files from scratch and regenerate the deliverables to match them."
                )
            else:
                solver_guidance = SOLVER_IMPROVEMENT_GUIDANCE_TEMPLATE.format(
                    judge_feedback=judge_review.raw_output,
                )

            solver = self._new_solver(paths.public_root, recorder.trace_dir_for("solver"), on_event=on_event)
            solver_result = solver.run(
                SOLVER_REQUEST_TEMPLATE.format(
                    original_prompt=prompt,
                    data_inventory=input_inventory["data_inventory"],
                    related_work_inventory=input_inventory["related_work_inventory"],
                    additional_guidance=solver_guidance,
                ),
                workspace_root=paths.public_root,
            )
            recorder.capture_agent_result("solver", solver_result)
            report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
            judge_review = self._judge_report(
                prompt=prompt,
                report_text=report_text,
                instructions_text=instructions_text,
                challenge_brief=challenge_brief,
                checklist_text=checklist_text,
                judge_materials_text=judge_materials_text,
                project_root=paths.project_root,
                recorder=recorder,
                on_event=on_event,
            )

        final_output = read_text_if_exists(paths.report_path, default=solver_result.output)
        recorder.complete(
            final_output=final_output,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            quality_scores={
                "overall_score": judge_review.overall_score,
                "project_score": judge_review.project_score,
                "report_score": judge_review.report_score,
            },
            metadata={
                "workspace_root": str(paths.project_root),
                "public_workspace_root": str(paths.public_root),
                "challenge_brief_path": str(paths.challenge_brief_path),
                "checklist_path": str(paths.checklist_path),
                "report_path": str(paths.report_path),
            },
        )

        return WorkflowResult(
            prompt=prompt,
            workspace_root=str(paths.project_root),
            challenge_output=challenge_output,
            solver_output=final_output,
            judge_review=judge_review,
            final_score=judge_review.overall_score,
            success=judge_review.overall_score >= self.improvement_threshold,
            iterations=iterations,
            metadata={
                "workflow_id": recorder.record.workflow_id,
                "public_workspace_root": str(paths.public_root),
                "challenge_brief_path": str(paths.challenge_brief_path),
                "checklist_path": str(paths.checklist_path),
                "report_path": str(paths.report_path),
            },
        )
