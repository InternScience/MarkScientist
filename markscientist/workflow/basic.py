from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from markscientist.agents.challenger import ChallengerAgent, ChallengerPackagingAgent
from markscientist.agents.judge import JudgeAgent, ReviewResult
from markscientist.judging import JudgeScenario
from markscientist.agents.solver import SolverAgent
from markscientist.config import Config, default_workspace_root, get_config
from markscientist.project import (
    detect_solver_owned_file_changes,
    describe_challenger_inputs,
    describe_workspace_inputs,
    ensure_project_layout,
    export_solver_workspace_from_task,
    invalid_source_input_files,
    invalid_solver_visible_input_files,
    load_checklist_text,
    load_judge_materials_text,
    missing_judge_contract_files,
    missing_solver_contract_files,
    missing_source_input_dirs,
    missing_solver_visible_input_dirs,
    missing_task_contract_files,
    read_text_if_exists,
    solver_artifact_status,
    snapshot_solver_owned_files,
)
from markscientist.prompts import (
    CHALLENGE_REQUEST_TEMPLATE,
    CHALLENGER_IMPROVEMENT_GUIDANCE_TEMPLATE,
    SOLVER_FINALIZATION_GUIDANCE_TEMPLATE,
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

    def _new_packaging_challenger(
        self,
        workspace_root: Path,
        trace_dir: Optional[Path],
        on_event=None,
    ) -> ChallengerPackagingAgent:
        return ChallengerPackagingAgent(
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
        checklist_text: str,
        judge_materials_text: str,
        project_root: Path,
        recorder: WorkflowTrajectoryRecorder,
        on_event=None,
    ) -> ReviewResult:
        judge = self._new_judge(project_root, recorder.trace_dir_for("judge"), on_event=on_event)
        feedback_path = project_root / "task" / "target_study" / "feedback_history.jsonl"
        review = judge.review_project_report(
            original_prompt=prompt,
            instructions_text=instructions_text,
            checklist_text=checklist_text,
            judge_materials_text=judge_materials_text,
            report_text=report_text,
            report_scenario=JudgeScenario.RESEARCH_REPORT,
            taste_feedback_path=feedback_path if feedback_path.exists() else None,
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
        def _source_material_counts() -> tuple[int, int]:
            data_files = sum(1 for path in paths.source_data_dir.rglob("*") if path.is_file())
            pdf_files = sum(1 for path in paths.source_related_work_dir.rglob("*.pdf") if path.is_file())
            return data_files, pdf_files

        solver_owned_before = snapshot_solver_owned_files(paths)
        source_data_file_count, source_pdf_count = _source_material_counts()
        source_materials_sufficient = source_data_file_count >= 1 and source_pdf_count >= 2
        source_pdfs_ready_for_dataset_derivation = source_data_file_count == 0 and source_pdf_count >= 2

        def _challenge_request(guidance: str) -> str:
            return CHALLENGE_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                source_data_inventory=input_inventory["source_data_inventory"],
                source_related_work_inventory=input_inventory["source_related_work_inventory"],
                public_data_inventory=input_inventory["public_data_inventory"],
                public_related_work_inventory=input_inventory["public_related_work_inventory"],
                additional_guidance=guidance,
            )

        if source_materials_sufficient:
            additional_guidance = (
                additional_guidance
                + "\n\nThe current private task workspace already has enough source materials for one strong project."
                + " Do not broaden source collection unless a critical prerequisite is still missing."
                + " Do not call `WebSearch` or `ScholarSearch` unless you can name that missing prerequisite explicitly."
                + " Read at most two source data items and at most two source PDFs to verify fit, then immediately write `task/task_info.json`, `task/target_study/checklist.json`, and `task/target_study/paper.pdf`."
            )
        elif source_pdfs_ready_for_dataset_derivation:
            additional_guidance = (
                additional_guidance
                + "\n\nThe private task workspace already has enough real source PDFs to stop literature discovery."
                + " Do not call `WebSearch` or `ScholarSearch` again unless a clearly named blocking prerequisite is still missing."
                + " Your next steps must use the existing PDFs under `task/related_work/` to derive one canonical structured dataset under `task/data/`."
                + " Read at most two of the current source PDFs, extract only the fields needed for one strong project, write the derived data files under `task/data/`, and then immediately write `task/task_info.json`, `task/target_study/checklist.json`, and `task/target_study/paper.pdf`."
            )

        challenger = self._new_challenger(paths.project_root, recorder.trace_dir_for("challenger"), on_event=on_event)
        challenge_result = challenger.run(
            _challenge_request(additional_guidance),
            workspace_root=paths.project_root,
        )
        recorder.capture_agent_result("challenger", challenge_result)

        solver_owned_after = snapshot_solver_owned_files(paths)
        forbidden_changes = detect_solver_owned_file_changes(solver_owned_before, solver_owned_after)
        if forbidden_changes:
            raise RuntimeError(
                "Challenger modified Solver-owned artifacts during project preparation: "
                + ", ".join(forbidden_changes)
            )

        missing_source_dirs = missing_source_input_dirs(paths)
        missing_task_files = missing_task_contract_files(paths)
        invalid_source_files = invalid_source_input_files(paths)
        missing_judge_files = missing_judge_contract_files(paths)
        missing_items = [
            *missing_source_dirs,
            *missing_task_files,
            *invalid_source_files,
            *missing_judge_files,
        ]
        if not missing_items:
            export_solver_workspace_from_task(paths)
            missing_items = [
                *missing_solver_contract_files(paths),
                *missing_solver_visible_input_dirs(paths),
                *invalid_solver_visible_input_files(paths),
            ]
        if not missing_items:
            return challenge_result

        source_data_file_count, source_pdf_count = _source_material_counts()
        repair_guidance = (
            additional_guidance
            + "\n\nThe previous Challenger pass did not finish building the full private task package. "
            + "Create the missing `task/` files now and stop once the private task is complete. "
            + "Missing items: "
            + ", ".join(f"`{path}`" for path in missing_items)
            + ". The harness will export the solver-visible workspace from `task/` automatically once the private task is coherent."
            + " Do not do Solver work such as writing analysis code, outputs, figures, `public/INSTRUCTIONS.md`, or `report/report.md`."
        )
        if source_pdf_count >= 2 and source_data_file_count == 0:
            repair_guidance += (
                " You already have enough real source PDFs. Do not do more literature search."
                " Do not call `WebSearch` or `ScholarSearch` again unless you can name a blocking missing prerequisite."
                " Your next task is to derive the canonical structured dataset under `task/data/` from the existing PDFs in `task/related_work/`, then finish `task/task_info.json`, `task/target_study/checklist.json`, and `task/target_study/paper.pdf`."
                " Use this fixed order and stop as soon as it is complete:"
                " (1) choose one target paper from the existing PDFs,"
                " (2) use `ReadPDF` on that target paper and keep one or more real extracted figure images under `task/target_study/images/`,"
                " (3) derive one canonical structured dataset under `task/data/`,"
                " (4) write `task/task_info.json`,"
                " (5) write `task/target_study/checklist.json` with at least one real image item that points into `images/`,"
                " (6) stop."
                " Do not spend additional turns on deeper paper reading once you have enough fields to complete those files."
            )
        use_packaging_only_challenger = source_pdf_count >= 2 and source_data_file_count == 0
        challenger_factory = self._new_packaging_challenger if use_packaging_only_challenger else self._new_challenger
        challenger = challenger_factory(paths.project_root, recorder.trace_dir_for("challenger"), on_event=on_event)
        challenge_result = challenger.run(
            _challenge_request(repair_guidance),
            workspace_root=paths.project_root,
        )
        recorder.capture_agent_result("challenger", challenge_result)

        solver_owned_after = snapshot_solver_owned_files(paths)
        forbidden_changes = detect_solver_owned_file_changes(solver_owned_before, solver_owned_after)
        if forbidden_changes:
            raise RuntimeError(
                "Challenger modified Solver-owned artifacts during project preparation: "
                + ", ".join(forbidden_changes)
            )

        missing_source_dirs = missing_source_input_dirs(paths)
        missing_task_files = missing_task_contract_files(paths)
        invalid_source_files = invalid_source_input_files(paths)
        missing_judge_files = missing_judge_contract_files(paths)
        missing_items = [
            *missing_source_dirs,
            *missing_task_files,
            *invalid_source_files,
            *missing_judge_files,
        ]
        if not missing_items:
            export_solver_workspace_from_task(paths)
            missing_items = [
                *missing_solver_contract_files(paths),
                *missing_solver_visible_input_dirs(paths),
                *invalid_solver_visible_input_files(paths),
            ]
        if missing_items:
            raise RuntimeError(
                "Challenger did not finish building the required project package: "
                + ", ".join(missing_items)
            )
        return challenge_result

    def _run_solver_phase(
        self,
        *,
        prompt: str,
        input_inventory: Dict[str, str],
        additional_guidance: str,
        paths,
        recorder: WorkflowTrajectoryRecorder,
        on_event=None,
    ):
        before_snapshot = snapshot_solver_owned_files(paths)
        preexisting_artifacts = solver_artifact_status(paths)
        if not (
            preexisting_artifacts["code_files"]
            or preexisting_artifacts["output_files"]
            or preexisting_artifacts["image_files"]
            or preexisting_artifacts["report_exists"]
        ):
            additional_guidance = (
                additional_guidance
                + "\n\nThis is the zero-artifact execution phase."
                + " Keep reading bounded: inspect only the smallest high-value subset of source materials needed to define the main analysis."
                + " Do not inspect more than two core data items, two core related-work documents, and one or two key figures before writing the first analysis script."
                + " Your next concrete milestone is to create at least one analysis script under `code/` and at least one real derived artifact under `outputs/`."
                + " Do not remain in pure reading mode once a feasible analysis path is clear."
            )
        solver = self._new_solver(paths.public_root, recorder.trace_dir_for("solver"), on_event=on_event)
        solver_result = solver.run(
            SOLVER_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                data_inventory=input_inventory["data_inventory"],
                related_work_inventory=input_inventory["related_work_inventory"],
                additional_guidance=additional_guidance,
            ),
            workspace_root=paths.public_root,
        )
        recorder.capture_agent_result("solver", solver_result)

        after_snapshot = snapshot_solver_owned_files(paths)
        artifact_status = solver_artifact_status(paths)
        report_rel_path = paths.report_path.relative_to(paths.public_root).as_posix()
        report_changed = before_snapshot.get(report_rel_path) != after_snapshot.get(report_rel_path)
        changed_solver_files = [
            rel_path
            for rel_path in detect_solver_owned_file_changes(before_snapshot, after_snapshot)
            if rel_path != report_rel_path
        ]

        if artifact_status["report_exists"] and (report_changed or not changed_solver_files):
            return solver_result

        has_substantial_progress = bool(
            artifact_status["code_files"] or artifact_status["output_files"] or artifact_status["image_files"]
        )
        if not has_substantial_progress:
            return solver_result

        finalization_guidance = SOLVER_FINALIZATION_GUIDANCE_TEMPLATE.format(
            code_files=artifact_status["code_files"],
            output_files=artifact_status["output_files"],
            image_files=artifact_status["image_files"],
        )
        solver = self._new_solver(paths.public_root, recorder.trace_dir_for("solver"), on_event=on_event)
        solver_result = solver.run(
            SOLVER_REQUEST_TEMPLATE.format(
                original_prompt=prompt,
                data_inventory=input_inventory["data_inventory"],
                related_work_inventory=input_inventory["related_work_inventory"],
                additional_guidance=additional_guidance + "\n\n" + finalization_guidance,
            ),
            workspace_root=paths.public_root,
        )
        recorder.capture_agent_result("solver", solver_result)
        return solver_result

    def run(
        self,
        prompt: str,
        workspace_root: Optional[Path] = None,
        on_event=None,
    ) -> WorkflowResult:
        if workspace_root is not None:
            project_root = Path(workspace_root).expanduser().resolve()
        elif self.config.workspace_root is not None:
            project_root = self.config.workspace_root.expanduser().resolve()
        else:
            project_root = default_workspace_root(datetime.now().strftime("%Y%m%d-%H%M%S"))
        paths = ensure_project_layout(project_root)
        input_inventory = describe_workspace_inputs(paths.public_root)
        recorder = WorkflowTrajectoryRecorder(
            prompt=prompt,
            model_name=self.config.model.model_name,
            workspace_root=str(paths.project_root),
            save_dir=self.save_dir if self.config.trajectory.auto_save else None,
        )
        recorder.record.checklist_path = str(paths.judge_checklist_path)
        recorder.record.report_path = str(paths.report_path)

        challenge_result = self._run_challenger_phase(
            prompt=prompt,
            input_inventory=describe_challenger_inputs(paths),
            additional_guidance=(
                "Prepare a private benchmark task under `task/` that matches the ResearchClawBench task shape. "
                "Create `task/task_info.json`, `task/data/`, `task/related_work/`, and `task/target_study/` including `task/target_study/checklist.json` and `task/target_study/paper.pdf`. "
                "The harness will export the solver-visible workspace from this private task using a fixed workflow. "
                "This phase must converge within a bounded scope: once one strong dataset family, two or more valid source PDFs, and a coherent project definition exist, stop searching and finish the private task package. "
                "Do not execute the project, write the report, generate final outputs, or score the result yourself. "
                "Those are downstream Solver and Judge responsibilities."
            ),
            paths=paths,
            recorder=recorder,
            on_event=on_event,
        )

        input_inventory = describe_workspace_inputs(paths.public_root)
        solver_result = self._run_solver_phase(
            prompt=prompt,
            input_inventory=input_inventory,
            additional_guidance="Read the prepared project files and complete the project end-to-end.",
            paths=paths,
            recorder=recorder,
            on_event=on_event,
        )

        iterations = 1
        challenge_output = challenge_result.output
        instructions_text = read_text_if_exists(paths.instructions_path, default="INSTRUCTIONS.md is missing.")
        checklist_text = load_checklist_text(paths.judge_checklist_path)
        judge_materials_text = load_judge_materials_text(paths)
        report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
        judge_review = self._judge_report(
            prompt=prompt,
            report_text=report_text,
            instructions_text=instructions_text,
            checklist_text=checklist_text,
            judge_materials_text=judge_materials_text,
            project_root=paths.project_root,
            recorder=recorder,
            on_event=on_event,
        )

        while judge_review.next_action != "accept" and iterations < self.max_iterations:
            iterations += 1
            if judge_review.next_action == "rechallenge":
                challenge_result = self._run_challenger_phase(
                    prompt=prompt,
                    input_inventory=describe_challenger_inputs(paths),
                    additional_guidance=CHALLENGER_IMPROVEMENT_GUIDANCE_TEMPLATE.format(
                        judge_feedback=judge_review.raw_output,
                    )
                    + "\n\nDo not execute the project, write the report, generate final outputs, or score the result yourself. "
                    + "Only revise the private `task/` package. The harness will regenerate the solver-visible workspace from it.",
                    paths=paths,
                    recorder=recorder,
                    on_event=on_event,
                )
                challenge_output = challenge_result.output
                instructions_text = read_text_if_exists(paths.instructions_path, default="INSTRUCTIONS.md is missing.")
                checklist_text = load_checklist_text(paths.judge_checklist_path)
                judge_materials_text = load_judge_materials_text(paths)
                solver_guidance = (
                    "The Challenger revised the project definition. "
                    "Read the updated `INSTRUCTIONS.md` from scratch and regenerate the deliverables to match it."
                )
            else:
                solver_guidance = SOLVER_IMPROVEMENT_GUIDANCE_TEMPLATE.format(
                    judge_feedback=judge_review.raw_output,
                )

            input_inventory = describe_workspace_inputs(paths.public_root)
            solver_result = self._run_solver_phase(
                prompt=prompt,
                input_inventory=input_inventory,
                additional_guidance=solver_guidance,
                paths=paths,
                recorder=recorder,
                on_event=on_event,
            )
            report_text = read_text_if_exists(paths.report_path, default=solver_result.output)
            judge_review = self._judge_report(
                prompt=prompt,
                report_text=report_text,
                instructions_text=instructions_text,
                checklist_text=checklist_text,
                judge_materials_text=judge_materials_text,
                project_root=paths.project_root,
                recorder=recorder,
                on_event=on_event,
            )

        final_output = read_text_if_exists(paths.report_path, default=solver_result.output)
        recorder.complete(
            final_output=final_output,
            success=judge_review.next_action == "accept",
            iterations=iterations,
            quality_scores={
                "overall_score": judge_review.overall_score,
                "project_score": judge_review.project_score,
                "report_score": judge_review.report_score,
            },
            metadata={
                "workspace_root": str(paths.project_root),
                "public_workspace_root": str(paths.public_root),
                "checklist_path": str(paths.judge_checklist_path),
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
            success=judge_review.next_action == "accept",
            iterations=iterations,
            metadata={
                "workflow_id": recorder.record.workflow_id,
                "public_workspace_root": str(paths.public_root),
                "checklist_path": str(paths.judge_checklist_path),
                "report_path": str(paths.report_path),
            },
        )
