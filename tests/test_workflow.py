import json
from pathlib import Path

import pytest

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import ReviewResult, _build_review_prompt
from markscientist.config import Config, TrajectoryConfig
from markscientist.workflow.basic import ResearchWorkflow


class FakeChallenger:
    def __init__(self, trace_path: Path, outputs=None):
        self.trace_path = trace_path
        self.outputs = outputs or ["Challenge files created."]
        self.index = 0

    def run(self, prompt, workspace_root=None):
        public_root = Path(workspace_root)
        (public_root / "challenge").mkdir(parents=True, exist_ok=True)
        (public_root / "report" / "images").mkdir(parents=True, exist_ok=True)
        (public_root / "code").mkdir(parents=True, exist_ok=True)
        (public_root / "outputs").mkdir(parents=True, exist_ok=True)
        (public_root / "data").mkdir(parents=True, exist_ok=True)
        (public_root / "related_work").mkdir(parents=True, exist_ok=True)
        (public_root / "INSTRUCTIONS.md").write_text("Read the challenge files and write report/report.md.", encoding="utf-8")
        challenge_output = self.outputs[min(self.index, len(self.outputs) - 1)]
        if self.index == 0:
            brief_text = "Build a strong research report with code, outputs, and figures."
        else:
            brief_text = "Revised project brief with tighter scope and stronger deliverables."
        self.index += 1
        (public_root / "challenge" / "brief.md").write_text(brief_text, encoding="utf-8")
        (public_root / "challenge" / "checklist.json").write_text(
            json.dumps(
                [
                    {
                        "type": "text",
                        "content": "The report must present the main result with concrete evidence.",
                        "path": None,
                        "keywords": ["main result", "evidence"],
                        "weight": 1.0,
                    }
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
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
        challenge_brief: str,
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
                challenge_brief=challenge_brief,
                checklist_text=checklist_text,
                judge_materials_text=judge_materials_text,
                report_text=report_text,
            ),
            workspace_root=workspace_root,
        )

    def _next_review(self, *, prompt: str, workspace_root=None):
        result = self.run(prompt, workspace_root=workspace_root)
        payload = json.loads(result.output)
        review = ReviewResult(
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
        return review


class DummyWorkflow(ResearchWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_challenger = None
        self.fake_solver = None
        self.fake_judge = None

    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = FakeChallenger((trace_dir / "challenger.jsonl") if trace_dir else workspace_root / "challenger.jsonl")
        return self.fake_challenger

    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = FakeSolver(
                outputs=["initial report", "improved report"],
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else workspace_root / "solver.jsonl",
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
                        next_action="solver_revision",
                        strengths=["Main result is now clear."],
                        suggestions=["Tighten minor wording issues."],
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 75.0, "reasoning": "Evidence is now concrete."}],
                        raw_output='{"overall_score": 75.0, "project_score": 78.0, "report_score": 75.0}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
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

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert "challenger" in payload
    assert "solver" in payload
    assert "judge" in payload
    assert "history" in payload
    assert "challenge_brief_path" in payload
    assert "checklist_path" in payload
    assert "report_path" in payload


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
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
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
                (trace_dir / "challenger.jsonl") if trace_dir else workspace_root / "challenger.jsonl",
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
                        next_action="solver_revision",
                        strengths=["Scope is now much tighter."],
                        suggestions=["Minor polish only."],
                        checklist_scores=[{"title": "Main Result", "mode": "subjective", "score": 70.0, "reasoning": "The revised project is now supportable."}],
                        raw_output='{"overall_score": 70.0, "project_score": 70.0, "report_score": 74.0, "next_action": "solver_revision"}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
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
    assert (tmp_path / "public" / "challenge" / "brief.md").read_text(encoding="utf-8") == "Revised project brief with tighter scope and stronger deliverables."

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
            self.challenger = RecordingChallenger((trace_dir / "challenger.jsonl") if trace_dir else workspace_root / "challenger.jsonl")
        return self.challenger

    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.solver is None:
            self.solver = RecordingSolver(
                outputs=["report content"],
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else workspace_root / "solver.jsonl",
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
                        next_action="solver_revision",
                        checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 80.0, "reasoning": "Sufficient."}],
                        raw_output='{"overall_score": 80.0, "project_score": 82.0, "report_score": 80.0}',
                    )
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
            )
        return self.judge


def test_workflow_separates_public_workspace_from_judge_materials(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir(parents=True, exist_ok=True)
    (judge_dir / "notes.md").write_text("Hidden note: do not leak exact target conclusions.", encoding="utf-8")
    (judge_dir / "checklist.json").write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "content": "Hidden criterion",
                    "path": None,
                    "keywords": ["hidden"],
                    "weight": 1.0,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    workflow = AccessSeparationWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)
    result = workflow.run("Create a research project.", workspace_root=tmp_path)

    assert result.success is True
    assert workflow.challenger.workspace_roots == [tmp_path / "public"]
    assert workflow.solver.workspace_roots == [tmp_path / "public"]
    assert workflow.judge.workspace_roots == [tmp_path]
    assert "Hidden note: do not leak exact target conclusions." in workflow.judge.prompts[0]
    assert "Hidden criterion" in workflow.judge.prompts[0]
    assert "## Project Review Panel" in workflow.judge.prompts[0]
    assert "## Report Review Panel" in workflow.judge.prompts[0]
    assert "scenario: project_definition" in workflow.judge.prompts[0]


class RepairingChallenger:
    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        self.index = 0
        self.prompts: list[str] = []

    def run(self, prompt, workspace_root=None):
        public_root = Path(workspace_root)
        self.prompts.append(prompt)
        self.index += 1
        if self.index >= 2:
            (public_root / "challenge").mkdir(parents=True, exist_ok=True)
            (public_root / "INSTRUCTIONS.md").write_text("Read the challenge files and write report/report.md.", encoding="utf-8")
            (public_root / "challenge" / "brief.md").write_text("Recovered brief.", encoding="utf-8")
            (public_root / "challenge" / "checklist.json").write_text(
                json.dumps(
                    [
                        {
                            "type": "text",
                            "content": "Recovered checklist item",
                            "path": None,
                            "keywords": ["recovered"],
                            "weight": 1.0,
                        }
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return AgentResult(
            output=f"challenge pass {self.index}",
            success=True,
            termination_reason="result",
            trace_path=str(self.trace_path),
        )


class ChallengeRepairWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = RepairingChallenger((trace_dir / "challenger.jsonl") if trace_dir else workspace_root / "challenger.jsonl")
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
    assert "did not create all required public project-definition files" in workflow.fake_challenger.prompts[1]
    assert (tmp_path / "public" / "INSTRUCTIONS.md").exists()
    assert (tmp_path / "public" / "challenge" / "brief.md").exists()
    assert (tmp_path / "public" / "challenge" / "checklist.json").exists()


class LeakyChallenger(FakeChallenger):
    def run(self, prompt, workspace_root=None):
        result = super().run(prompt, workspace_root=workspace_root)
        public_root = Path(workspace_root)
        (public_root / "code").mkdir(parents=True, exist_ok=True)
        (public_root / "code" / "should_not_exist.py").write_text("print('solver-owned')\n", encoding="utf-8")
        return result


class LeakyChallengeWorkflow(DummyWorkflow):
    def _new_challenger(self, workspace_root, trace_dir, on_event=None):
        if self.fake_challenger is None:
            self.fake_challenger = LeakyChallenger((trace_dir / "challenger.jsonl") if trace_dir else workspace_root / "challenger.jsonl")
        return self.fake_challenger


def test_workflow_rejects_challenger_writing_solver_owned_artifacts(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = LeakyChallengeWorkflow(config=config, save_dir=config.trajectory.save_dir, max_iterations=1)

    with pytest.raises(RuntimeError, match="Challenger modified Solver-owned artifacts"):
        workflow.run("Create a research project.", workspace_root=tmp_path)
