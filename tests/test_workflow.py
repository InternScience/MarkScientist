import json
from pathlib import Path

import pytest

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import ReviewResult, _build_review_prompt
from markscientist.config import Config, TrajectoryConfig
from markscientist.workflow.basic import ResearchWorkflow


def _resolve_project_roots(workspace_root) -> tuple[Path, Path, Path, Path]:
    project_root = Path(workspace_root)
    task_root = project_root / "task"
    public_root = project_root / "public"
    target_study_root = task_root / "target_study"
    return project_root, task_root, public_root, target_study_root


def _write_private_task(
    workspace_root,
    *,
    task_desc: str,
    checklist_content: str = "The report must present the main result with concrete evidence.",
) -> None:
    project_root, task_root, _, target_study_root = _resolve_project_roots(workspace_root)
    (task_root / "data").mkdir(parents=True, exist_ok=True)
    (task_root / "related_work").mkdir(parents=True, exist_ok=True)
    (target_study_root / "images").mkdir(parents=True, exist_ok=True)
    (task_root / "data" / "input.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (task_root / "related_work" / "paper.pdf").write_bytes(b"%PDF-1.4\n% fake source pdf\n")
    (target_study_root / "paper.pdf").write_bytes(b"%PDF-1.4\n% fake target paper\n")
    (target_study_root / "images" / "figure1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\x0f"
        b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb1\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (task_root / "task_info.json").write_text(
        json.dumps(
            {
                "task": task_desc,
                "data": [
                    {
                        "name": "Input Data",
                        "path": "./data/input.csv",
                        "type": "CSV",
                        "description": "Synthetic test fixture for workflow validation.",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (target_study_root / "checklist.json").write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "content": checklist_content,
                    "path": None,
                    "keywords": ["main result", "evidence"],
                    "weight": 0.7,
                },
                {
                    "type": "image",
                    "content": "The report must reproduce or substantively match the key target-paper figure logic.",
                    "path": "images/figure1.png",
                    "keywords": ["figure", "comparison", "main visual"],
                    "weight": 0.3,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class FakeChallenger:
    def __init__(self, trace_path: Path, outputs=None):
        self.trace_path = trace_path
        self.outputs = outputs or ["Challenge files created."]
        self.index = 0

    def run(self, prompt, workspace_root=None):
        task_desc = (
            "Build a strong research report with code, outputs, and figures."
            if self.index == 0
            else "Revised instructions with tighter scope and stronger deliverables."
        )
        _write_private_task(workspace_root, task_desc=task_desc)
        challenge_output = self.outputs[min(self.index, len(self.outputs) - 1)]
        self.index += 1
        return AgentResult(
            output=challenge_output,
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class FakeSolver:
    def __init__(self, outputs, trace_path: Path):
        self.outputs = outputs
        self.trace_path = trace_path
        self.index = 0

    def run(self, prompt, workspace_root=None):
        output = self.outputs[self.index]
        self.index += 1
        public_root = Path(workspace_root)
        (public_root / "report").mkdir(parents=True, exist_ok=True)
        (public_root / "report" / "report.md").write_text(output, encoding="utf-8")
        return AgentResult(
            output=output,
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class FakeJudge:
    def __init__(self, reviews, trace_path: Path):
        self.reviews = reviews
        self.trace_path = trace_path
        self.index = 0

    def run(self, prompt, workspace_root=None):
        review = self.reviews[self.index]
        self.index += 1
        return AgentResult(
            output=json.dumps(review.to_dict(), ensure_ascii=False),
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )

    def review_project_report(
        self,
        *,
        original_prompt: str,
        instructions_text: str,
        checklist_text: str,
        judge_materials_text: str,
        report_text: str,
        report_scenario=None,
        taste_feedback_path=None,
        workspace_root=None,
    ):
        return self._next_review(
            prompt=_build_review_prompt(
                original_prompt=original_prompt,
                instructions_text=instructions_text,
                checklist_text=checklist_text,
                judge_materials_text=judge_materials_text,
                report_text=report_text,
            ),
            workspace_root=workspace_root,
        )

    def _next_review(self, *, prompt: str, workspace_root=None):
        result = self.run(prompt, workspace_root=workspace_root)
        payload = json.loads(result.output)
        return ReviewResult(
            overall_score=payload.get("overall_score", 0.0),
            project_score=payload.get("project_score", 0.0),
            report_score=payload.get("report_score", 0.0),
            verdict=payload.get("verdict", ""),
            summary=payload.get("summary", ""),
            next_action=payload.get("next_action", "solver_revision"),
            strengths=payload.get("strengths", []),
            weaknesses=payload.get("weaknesses", []),
            suggestions=payload.get("suggestions", []),
            checklist_scores=payload.get("checklist_scores", []),
            confidence=payload.get("confidence", 0.0),
            raw_output=result.output,
            termination_reason=result.termination_reason,
            trace_path=result.trace_path,
            metadata=payload.get("metadata", {}),
        )


class DummyWorkflow(ResearchWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_challenger = None
        self.fake_solver = None
        self.fake_judge = None

    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = FakeChallenger((trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl")
        return self.fake_challenger

    def _new_packaging_challenger(self, workspace_root, trace_dir, on_event=None):
        return self._new_challenger(workspace_root, trace_dir, on_event=on_event)

    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = FakeSolver(
                outputs=["initial report", "improved report"],
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else Path(workspace_root) / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=45.0,
                        project_score=72.0,
                        report_score=45.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        next_action="solver_revision",
                        weaknesses=["Missing evidence"],
                        suggestions=["Strengthen the main result section."],
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 45.0, "reasoning": "Needs stronger evidence."}],
                        raw_output='{"overall_score": 45.0, "project_score": 72.0, "report_score": 45.0}',
                    ),
                    ReviewResult(
                        overall_score=75.0,
                        project_score=78.0,
                        report_score=75.0,
                        verdict="Acceptable",
                        summary="Much stronger.",
                        next_action="accept",
                        strengths=["Main result is now clear."],
                        suggestions=["Tighten minor wording issues."],
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 75.0, "reasoning": "Evidence is now concrete."}],
                        raw_output='{"overall_score": 75.0, "project_score": 78.0, "report_score": 75.0, "next_action": "accept"}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_runs_challenger_solver_judge_cycle(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = DummyWorkflow(config=config, save_dir=config.trajectory.save_dir)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert result.iterations == 2
    assert result.final_score == 75.0
    assert result.challenge_output == "Challenge files created."
    assert result.solver_output == "improved report"
    assert result.metadata["public_workspace_root"].endswith("public")
    assert result.metadata["report_path"].endswith("public/report/report.md")
    assert (tmp_path / "public" / "INSTRUCTIONS.md").exists()

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert "challenger" in payload
    assert "solver" in payload
    assert "judge" in payload
    assert "history" in payload
    assert "checklist_path" in payload
    assert "report_path" in payload
    assert '"checklist_path": "' + str(tmp_path / "task" / "target_study" / "checklist.json") + '"' in payload


def test_workflow_defaults_workspace_under_markscientist_data(monkeypatch, tmp_path: Path):
    workspaces_root = (tmp_path / "data" / "workspaces").resolve()
    monkeypatch.setattr(
        "markscientist.workflow.basic.default_workspace_root",
        lambda session_id: workspaces_root / session_id,
    )
    config = Config(
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = DummyWorkflow(config=config, save_dir=config.trajectory.save_dir)

    result = workflow.run("Create a research project.")

    assert Path(result.workspace_root).is_relative_to(workspaces_root)
    assert Path(result.metadata["public_workspace_root"]).is_relative_to(workspaces_root)
    assert Path(result.metadata["report_path"]).exists()


class RejectedImprovementWorkflow(DummyWorkflow):
    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=45.0,
                        project_score=72.0,
                        report_score=45.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        next_action="solver_revision",
                        weaknesses=["Missing evidence"],
                        suggestions=["Strengthen the main result section."],
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 45.0, "reasoning": "Needs stronger evidence."}],
                        raw_output='{"overall_score": 45.0, "project_score": 72.0, "report_score": 45.0}',
                    ),
                    ReviewResult(
                        overall_score=48.0,
                        project_score=72.0,
                        report_score=48.0,
                        verdict="Still Weak",
                        summary="Not enough improvement.",
                        next_action="solver_revision",
                        weaknesses=["Still insufficient evidence"],
                        suggestions=["Add stronger validation."],
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 48.0, "reasoning": "Still too weak."}],
                        raw_output='{"overall_score": 48.0, "project_score": 72.0, "report_score": 48.0}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_keeps_latest_report_when_threshold_not_met(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = RejectedImprovementWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=2)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is False
    assert result.solver_output == "improved report"
    assert result.final_score == 48.0

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert '"final_output_preview": "improved report"' in payload


class RechallengeWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = FakeChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl",
                outputs=["Initial challenge files created.", "Revised challenge files created."],
            )
        return self.fake_challenger

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=35.0,
                        project_score=35.0,
                        report_score=55.0,
                        verdict="Project Definition Weak",
                        summary="The project framing is too vague.",
                        next_action="rechallenge",
                        weaknesses=["Checklist is under-specified"],
                        suggestions=["Tighten the project scope before more solving."],
                        checklist_scores=[{"title": "Main Result", "mode": "subjective", "score": 35.0, "reasoning": "The task framing is too weak."}],
                        raw_output='{"overall_score": 35.0, "project_score": 35.0, "report_score": 55.0, "next_action": "rechallenge"}',
                    ),
                    ReviewResult(
                        overall_score=70.0,
                        project_score=70.0,
                        report_score=74.0,
                        verdict="Acceptable",
                        summary="The revised project is executable and the report is acceptable.",
                        next_action="accept",
                        strengths=["Scope is now much tighter."],
                        suggestions=["Minor polish only."],
                        checklist_scores=[{"title": "Main Result", "mode": "subjective", "score": 70.0, "reasoning": "The revised project is now supportable."}],
                        raw_output='{"overall_score": 70.0, "project_score": 70.0, "report_score": 74.0, "next_action": "accept"}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_can_rechallenge_before_retrying_solver(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = RechallengeWorkflow(config=config, save_dir=config.trajectory.save_dir)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert result.iterations == 2
    assert result.challenge_output == "Revised challenge files created."
    assert result.solver_output == "improved report"
    assert workflow.fake_challenger.index == 2
    instructions_text = (tmp_path / "public" / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "Revised instructions with tighter scope and stronger deliverables." in instructions_text

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = json.loads(workflow_json[0].read_text(encoding="utf-8"))
    challenger_entries = [entry for entry in payload["history"] if entry["agent_type"] == "challenger"]
    assert len(challenger_entries) == 2


class RecordingChallenger(FakeChallenger):
    def __init__(self, trace_path: Path):
        super().__init__(trace_path)
        self.workspace_roots: list[Path] = []

    def run(self, prompt, workspace_root=None):
        self.workspace_roots.append(Path(workspace_root))
        return super().run(prompt, workspace_root=workspace_root)


class RecordingSolver(FakeSolver):
    def __init__(self, outputs, trace_path: Path):
        super().__init__(outputs, trace_path)
        self.workspace_roots: list[Path] = []

    def run(self, prompt, workspace_root=None):
        self.workspace_roots.append(Path(workspace_root))
        return super().run(prompt, workspace_root=workspace_root)


class RecordingJudge(FakeJudge):
    def __init__(self, reviews, trace_path: Path):
        super().__init__(reviews, trace_path)
        self.workspace_roots: list[Path] = []
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.workspace_roots.append(Path(workspace_root))
        self.prompts.append(prompt)
        return super().run(prompt, workspace_root=workspace_root)


class AccessSeparationWorkflow(ResearchWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.challenger = None
        self.solver = None
        self.judge = None

    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.challenger is None:
            self.challenger = RecordingChallenger((trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl")
        return self.challenger

    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.solver is None:
            self.solver = RecordingSolver(
                outputs=["report content"],
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else Path(workspace_root) / "solver.jsonl",
            )
        return self.solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.judge is None:
            self.judge = RecordingJudge(
                reviews=[
                    ReviewResult(
                        overall_score=80.0,
                        project_score=82.0,
                        report_score=80.0,
                        verdict="Acceptable",
                        summary="Good separation.",
                        next_action="accept",
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 80.0, "reasoning": "Sufficient."}],
                        raw_output='{"overall_score": 80.0, "project_score": 82.0, "report_score": 80.0, "next_action": "accept"}',
                    )
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.judge


def test_workflow_separates_public_workspace_from_judge_materials(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    _, _, _, target_study_root = _resolve_project_roots(tmp_path)
    target_study_root.mkdir(parents=True, exist_ok=True)
    (target_study_root / "notes.md").write_text("Hidden note: do not leak exact target conclusions.", encoding="utf-8")

    workflow = AccessSeparationWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)
    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert workflow.challenger.workspace_roots == [tmp_path]
    assert workflow.solver.workspace_roots == [tmp_path / "public"]
    assert workflow.judge.workspace_roots == [tmp_path]
    assert "Hidden note: do not leak exact target conclusions." in workflow.judge.prompts[0]
    assert "The report must present the main result with concrete evidence." in workflow.judge.prompts[0]
    assert "## Project Review Panel" in workflow.judge.prompts[0]
    assert "## Report Review Panel" in workflow.judge.prompts[0]
    assert "scenario: project_definition" in workflow.judge.prompts[0]


class RepairingChallenger:
    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        self.index = 0
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        self.index += 1
        if self.index >= 2:
            _write_private_task(workspace_root, task_desc="Recovered instructions.")
        return AgentResult(
            output=f"challenge pass {self.index}",
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class PromptCapturingChallenger(FakeChallenger):
    def __init__(self, trace_path: Path):
        super().__init__(trace_path=trace_path)
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        return super().run(prompt, workspace_root=workspace_root)


class ExistingSourceMaterialsWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = PromptCapturingChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_adds_explicit_convergence_gate_when_source_materials_are_already_sufficient(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    _write_private_task(tmp_path, task_desc="Seed task.")
    (tmp_path / "task" / "related_work" / "paper_b.pdf").write_bytes(b"%PDF-1.4\n% fake second source pdf\n")

    workflow = ExistingSourceMaterialsWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)
    workflow.run("Create a research project.", workspace_root=tmp_path)

    assert "The current private task workspace already has enough source materials for one strong project." in workflow.fake_challenger.prompts[0]
    assert "Do not call `WebSearch` or `ScholarSearch` unless you can name that missing prerequisite explicitly." in workflow.fake_challenger.prompts[0]
    assert "Read at most two source data items and at most two source PDFs" in workflow.fake_challenger.prompts[0]


def test_workflow_forces_dataset_derivation_when_pdfs_exist_but_data_is_missing(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    task_root = tmp_path / "task"
    (task_root / "related_work").mkdir(parents=True, exist_ok=True)
    (task_root / "related_work" / "paper_a.pdf").write_bytes(b"%PDF-1.4\n% fake source pdf A\n")
    (task_root / "related_work" / "paper_b.pdf").write_bytes(b"%PDF-1.4\n% fake source pdf B\n")

    workflow = ExistingSourceMaterialsWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)
    workflow.run("Create a research project.", workspace_root=tmp_path)

    prompt = workflow.fake_challenger.prompts[0]
    assert "already has enough real source PDFs to stop literature discovery" in prompt
    assert "Do not call `WebSearch` or `ScholarSearch` again" in prompt
    assert "derive one canonical structured dataset under `task/data/`" in prompt


class ChallengeRepairWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = RepairingChallenger((trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl")
        return self.fake_challenger


def test_workflow_repairs_missing_challenge_contract_before_solver(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = ChallengeRepairWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is False
    assert workflow.fake_challenger.index == 2
    assert "did not finish building the full private task package" in workflow.fake_challenger.prompts[1]
    assert (tmp_path / "public" / "INSTRUCTIONS.md").exists()
    assert (tmp_path / "task" / "target_study" / "checklist.json").exists()
    assert (tmp_path / "task" / "data" / "input.csv").exists()
    assert (tmp_path / "task" / "related_work" / "paper.pdf").exists()


class GatherOnlyChallenger:
    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        self.index = 0

    def run(self, prompt, workspace_root=None):
        self.index += 1
        task_root = Path(workspace_root) / "task"
        (task_root / "related_work").mkdir(parents=True, exist_ok=True)
        (task_root / "related_work" / "paper_a.pdf").write_bytes(b"%PDF-1.4\n% fake source pdf A\n")
        (task_root / "related_work" / "paper_b.pdf").write_bytes(b"%PDF-1.4\n% fake source pdf B\n")
        return AgentResult(
            output="downloaded source pdfs",
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class PackagingRepairChallenger:
    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        self.prompts: list[str] = []
        self.index = 0

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        self.index += 1
        _write_private_task(workspace_root, task_desc="Recovered from gathered PDFs.")
        return AgentResult(
            output="packaged private task",
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class GatherThenPackagingWorkflow(DummyWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gather_challenger = None
        self.packaging_challenger = None

    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.gather_challenger is None:
            self.gather_challenger = GatherOnlyChallenger(
                (trace_dir / "challenger-gather.jsonl") if trace_dir else Path(workspace_root) / "challenger-gather.jsonl"
            )
        return self.gather_challenger

    def _new_packaging_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.packaging_challenger is None:
            self.packaging_challenger = PackagingRepairChallenger(
                (trace_dir / "challenger-packaging.jsonl") if trace_dir else Path(workspace_root) / "challenger-packaging.jsonl"
            )
        return self.packaging_challenger


def test_workflow_switches_to_packaging_only_after_first_pass_gathers_pdfs(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = GatherThenPackagingWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is False
    assert workflow.gather_challenger.index == 1
    assert workflow.packaging_challenger.index == 1
    prompt = workflow.packaging_challenger.prompts[0]
    assert "You already have enough real source PDFs" in prompt
    assert "derive the canonical structured dataset under `task/data/` from the existing PDFs" in prompt
    assert (tmp_path / "task" / "target_study" / "images" / "figure1.png").exists()


class LeakyChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, _, public_root, _ = _resolve_project_roots(workspace_root)
        (public_root / "code").mkdir(parents=True, exist_ok=True)
        (public_root / "code" / "should_not_exist.py").write_text("print('solver-owned')\n", encoding="utf-8")
        return result


class LeakyChallengeWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = LeakyChallenger((trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl")
        return self.fake_challenger


def test_workflow_rejects_challenger_writing_solver_owned_artifacts(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = LeakyChallengeWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="Challenger modified Solver-owned artifacts"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class NonPdfRelatedWorkChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, _ = _resolve_project_roots(workspace_root)
        (task_root / "related_work" / "notes.md").write_text("# Not allowed\n", encoding="utf-8")
        return result


class NonPdfRelatedWorkWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = NonPdfRelatedWorkChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_rejects_non_pdf_source_related_work(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = NonPdfRelatedWorkWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="top-level source related work must be PDF"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class InvalidPdfSignatureChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, target_study_root = _resolve_project_roots(workspace_root)
        fake_pdf_bytes = b"<!doctype html><html><body>not a real pdf</body></html>"
        (task_root / "related_work" / "paper.pdf").write_bytes(fake_pdf_bytes)
        (target_study_root / "paper.pdf").write_bytes(fake_pdf_bytes)
        return result


class InvalidPdfSignatureWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = InvalidPdfSignatureChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_rejects_invalid_pdf_signature_related_work(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = InvalidPdfSignatureWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="invalid or not a real PDF"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class MissingTargetImageChecklistChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, target_study_root = _resolve_project_roots(workspace_root)
        (target_study_root / "images" / "figure1.png").unlink()
        (target_study_root / "checklist.json").write_text(
            json.dumps(
                [
                    {
                        "type": "text",
                        "content": "Only text item.",
                        "path": None,
                        "keywords": ["result"],
                        "weight": 1.0,
                    }
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result


class MissingTargetImageChecklistWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = MissingTargetImageChecklistChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_requires_target_study_images_and_image_checklist_items(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = MissingTargetImageChecklistWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="checklist must include at least one image item|target_study/images"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class PdfInDataChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, _ = _resolve_project_roots(workspace_root)
        (task_root / "data" / "source_report.pdf").write_bytes(b"%PDF-1.4\n% fake data pdf\n")
        (task_root / "task_info.json").write_text(
            json.dumps(
                {
                    "task": "Bad task with PDF data path.",
                    "data": [
                        {
                            "name": "Bad PDF Data",
                            "path": "./data/source_report.pdf",
                            "type": "pdf",
                            "description": "Should be rejected because data must not be PDF.",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result


class PdfInDataWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = PdfInDataChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_rejects_pdf_files_inside_source_data(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = PdfInDataWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="source data must not contain PDF files|data\\[\\]\\.path` must not reference PDF files"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class SourcePdfSidecarChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, _ = _resolve_project_roots(workspace_root)
        sidecar_dir = task_root / "related_work" / "paper"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        (sidecar_dir / "full.md").write_text("# extracted text\n", encoding="utf-8")
        (sidecar_dir / "layout.json").write_text("{}", encoding="utf-8")
        return result


class SourcePdfSidecarWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = SourcePdfSidecarChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_allows_readpdf_sidecars_under_source_related_work(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = SourcePdfSidecarWorkflow(config=config, save_dir=config.trajectory.save_dir)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert (tmp_path / "task" / "related_work" / "paper" / "full.md").exists()
    assert (tmp_path / "public" / "related_work" / "paper.pdf").exists()


class ExportSubsetChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, _ = _resolve_project_roots(workspace_root)
        (task_root / "data" / "unused.csv").write_text("a,b\n3,4\n", encoding="utf-8")
        return result


class ExportSubsetWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = ExportSubsetChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_exports_only_manifest_declared_public_data_subset(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = ExportSubsetWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    workflow.run("Create a research project.", workspace_root=tmp_path)

    assert (tmp_path / "public" / "data" / "input.csv").exists()
    assert not (tmp_path / "public" / "data" / "unused.csv").exists()


class MissingSourceMaterialsChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        _, task_root, _, _ = _resolve_project_roots(workspace_root)
        for path in sorted((task_root / "data").rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
        for path in sorted((task_root / "related_work").rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
        return result


class MissingSourceMaterialsWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = MissingSourceMaterialsChallenger(
                (trace_dir / "challenger.jsonl") if trace_dir else Path(workspace_root) / "challenger.jsonl"
            )
        return self.fake_challenger


def test_workflow_requires_private_source_materials_before_solver(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = MissingSourceMaterialsWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="task/data|task/related_work"):
        workflow.run("Create a research project.", workspace_root=tmp_path)


class PromptCapturingSolver(FakeSolver):
    def __init__(self, trace_path: Path):
        super().__init__(outputs=["initial report"], trace_path=trace_path)
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        return super().run(prompt, workspace_root=workspace_root)


class ZeroArtifactGateWorkflow(DummyWorkflow):
    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = PromptCapturingSolver(
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else Path(workspace_root) / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=55.0,
                        project_score=70.0,
                        report_score=55.0,
                        verdict="Acceptable",
                        summary="Enough for a single-pass test.",
                        next_action="accept",
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 55.0, "reasoning": "Enough."}],
                        raw_output='{"overall_score": 55.0, "project_score": 70.0, "report_score": 55.0, "next_action": "accept"}',
                    )
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_adds_zero_artifact_solver_gate_to_first_solver_pass(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = ZeroArtifactGateWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    workflow.run("Create a research project.", workspace_root=tmp_path)

    assert "This is the zero-artifact execution phase." in workflow.fake_solver.prompts[0]
    assert "Do not inspect more than two core data items, two core related-work documents, and one or two key figures" in workflow.fake_solver.prompts[0]
    assert "create at least one analysis script under `code/` and at least one real derived artifact under `outputs/`" in workflow.fake_solver.prompts[0]


class FinalizingSolver(FakeSolver):
    def __init__(self, trace_path: Path):
        super().__init__(outputs=["analysis in progress", "final report"], trace_path=trace_path)
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        public_root = Path(workspace_root)
        (public_root / "code").mkdir(parents=True, exist_ok=True)
        (public_root / "outputs").mkdir(parents=True, exist_ok=True)
        (public_root / "report" / "images").mkdir(parents=True, exist_ok=True)
        if self.index == 0:
            (public_root / "code" / "analysis.py").write_text("print('ok')\n", encoding="utf-8")
            (public_root / "outputs" / "summary.csv").write_text("metric,value\ncount,1\n", encoding="utf-8")
            (public_root / "report" / "images" / "figure.png").write_text("png", encoding="utf-8")
            output = self.outputs[self.index]
            self.index += 1
            return AgentResult(
                output=output,
                success=True,
                termination_reason="result",
                trace_path=str(self.trace_path),
            )
        return super().run(prompt, workspace_root=workspace_root)


class FinalizationWorkflow(DummyWorkflow):
    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = FinalizingSolver(
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else Path(workspace_root) / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=78.0,
                        project_score=78.0,
                        report_score=78.0,
                        verdict="Acceptable",
                        summary="Finalized report is present.",
                        next_action="accept",
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 78.0, "reasoning": "Sufficient."}],
                        raw_output='{"overall_score": 78.0, "project_score": 78.0, "report_score": 78.0, "next_action": "accept"}',
                    )
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_forces_solver_report_finalization_when_artifacts_exist(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = FinalizationWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert result.solver_output == "final report"
    assert (tmp_path / "public" / "report" / "report.md").exists()
    assert len(workflow.fake_solver.prompts) == 2
    assert "Focus now on final report completion" in workflow.fake_solver.prompts[1]


class RevisingSolver(FakeSolver):
    def __init__(self, trace_path: Path):
        super().__init__(outputs=["revised analysis", "revised final report"], trace_path=trace_path)
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        public_root = Path(workspace_root)
        (public_root / "code").mkdir(parents=True, exist_ok=True)
        (public_root / "outputs").mkdir(parents=True, exist_ok=True)
        (public_root / "report").mkdir(parents=True, exist_ok=True)
        (public_root / "report" / "images").mkdir(parents=True, exist_ok=True)
        if self.index == 0:
            (public_root / "report" / "report.md").write_text("stale report", encoding="utf-8")
            (public_root / "code" / "analysis.py").write_text("print('old')\n", encoding="utf-8")
            self.index += 1
            return AgentResult(
                output="seed report",
                success=True,
                termination_reason="result",
                trace_path=str(self.trace_path),
            )
        if self.index == 1:
            (public_root / "code" / "analysis.py").write_text("print('revised')\n", encoding="utf-8")
            (public_root / "outputs" / "summary.csv").write_text("metric,value\ncount,2\n", encoding="utf-8")
            (public_root / "report" / "images" / "figure.png").write_text("png", encoding="utf-8")
            self.index += 1
            return AgentResult(
                output="revised analysis",
                success=True,
                termination_reason="result",
                trace_path=str(self.trace_path),
            )
        (public_root / "report" / "report.md").write_text("revised final report", encoding="utf-8")
        self.index += 1
        return AgentResult(
            output="revised final report",
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class RevisionFinalizationWorkflow(DummyWorkflow):
    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = RevisingSolver(
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else Path(workspace_root) / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        overall_score=42.0,
                        project_score=72.0,
                        report_score=42.0,
                        verdict="Needs Improvement",
                        summary="Refresh the report after regenerating outputs.",
                        next_action="solver_revision",
                        suggestions=["Update report/report.md to match the regenerated artifacts."],
                        checklist_scores=[{"title": "Traceability", "mode": "objective", "score": 42.0, "reasoning": "Report is stale."}],
                        raw_output='{"overall_score": 42.0, "project_score": 72.0, "report_score": 42.0, "next_action": "solver_revision"}',
                    ),
                    ReviewResult(
                        overall_score=80.0,
                        project_score=80.0,
                        report_score=80.0,
                        verdict="Acceptable",
                        summary="Report now matches the regenerated artifacts.",
                        next_action="accept",
                        checklist_scores=[{"title": "Traceability", "mode": "objective", "score": 80.0, "reasoning": "Report was refreshed."}],
                        raw_output='{"overall_score": 80.0, "project_score": 80.0, "report_score": 80.0, "next_action": "accept"}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else Path(workspace_root) / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_re_finalizes_when_solver_updates_artifacts_but_leaves_stale_report(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = RevisionFinalizationWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=2)

    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert result.solver_output == "revised final report"
    assert (tmp_path / "public" / "report" / "report.md").read_text(encoding="utf-8") == "revised final report"
    assert len(workflow.fake_solver.prompts) == 3
    assert "Focus now on final report completion" in workflow.fake_solver.prompts[2]
