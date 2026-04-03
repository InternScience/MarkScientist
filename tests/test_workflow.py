import json
from pathlib import Path

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import ReviewResult
from markscientist.config import Config, TrajectoryConfig
from markscientist.project import ensure_project_layout
from markscientist.workflow.basic import ResearchWorkflow


class FakeChallenger:
    def __init__(self, trace_path: Path, outputs=None):
        self.trace_path = trace_path
        self.outputs = outputs or ["Challenge files created."]
        self.index = 0

    def run(self, prompt, workspace_root=None):
        paths = ensure_project_layout(workspace_root)
        paths.instructions_path.write_text("Read the challenge files and write report/report.md.", encoding="utf-8")
        challenge_output = self.outputs[min(self.index, len(self.outputs) - 1)]
        if self.index == 0:
            brief_text = "Build a strong research report with code, outputs, and figures."
        else:
            brief_text = "Revised project brief with tighter scope and stronger deliverables."
        self.index += 1
        paths.challenge_brief_path.write_text(brief_text, encoding="utf-8")
        paths.checklist_path.write_text(
            json.dumps(
                [
                    {
                        "title": "Main Result",
                        "description": "Report the main result clearly.",
                        "evidence_required": "Concrete analysis in the report.",
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
        paths = ensure_project_layout(workspace_root)
        paths.report_path.write_text(output, encoding="utf-8")
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
                        overall_score=5.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        next_action="solver_revision",
                        weaknesses=["Missing evidence"],
                        suggestions=["Strengthen the main result section."],
                        checklist_scores=[{"title": "Main Result", "score": 5.0, "reasoning": "Needs stronger evidence."}],
                        raw_output='{"overall_score": 5.0}',
                    ),
                    ReviewResult(
                        overall_score=7.5,
                        verdict="Acceptable",
                        summary="Much stronger.",
                        next_action="solver_revision",
                        strengths=["Main result is now clear."],
                        suggestions=["Tighten minor wording issues."],
                        checklist_scores=[{"title": "Main Result", "score": 7.5, "reasoning": "Evidence is now concrete."}],
                        raw_output='{"overall_score": 7.5}',
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
    assert result.final_score == 7.5
    assert result.challenge_output == "Challenge files created."
    assert result.solver_output == "improved report"
    assert result.metadata["report_path"].endswith("report/report.md")

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
                        overall_score=5.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        next_action="solver_revision",
                        weaknesses=["Missing evidence"],
                        suggestions=["Strengthen the main result section."],
                        checklist_scores=[{"title": "Main Result", "score": 5.0, "reasoning": "Needs stronger evidence."}],
                        raw_output='{"overall_score": 5.0}',
                    ),
                    ReviewResult(
                        overall_score=5.5,
                        verdict="Still Weak",
                        summary="Not enough improvement.",
                        next_action="solver_revision",
                        weaknesses=["Still insufficient evidence"],
                        suggestions=["Add stronger validation."],
                        checklist_scores=[{"title": "Main Result", "score": 5.5, "reasoning": "Still too weak."}],
                        raw_output='{"overall_score": 5.5}',
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
    assert result.final_score == 5.5

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
                        overall_score=4.0,
                        verdict="Project Definition Weak",
                        summary="The project framing is too vague.",
                        next_action="rechallenge",
                        weaknesses=["Checklist is under-specified"],
                        suggestions=["Tighten the project scope before more solving."],
                        checklist_scores=[{"title": "Main Result", "score": 4.0, "reasoning": "The task framing is too weak."}],
                        raw_output='{"overall_score": 4.0, "next_action": "rechallenge"}',
                    ),
                    ReviewResult(
                        overall_score=7.0,
                        verdict="Acceptable",
                        summary="The revised project is executable and the report is acceptable.",
                        next_action="solver_revision",
                        strengths=["Scope is now much tighter."],
                        suggestions=["Minor polish only."],
                        checklist_scores=[{"title": "Main Result", "score": 7.0, "reasoning": "The revised project is now supportable."}],
                        raw_output='{"overall_score": 7.0, "next_action": "solver_revision"}',
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
    assert (tmp_path / "challenge" / "brief.md").read_text(encoding="utf-8") == "Revised project brief with tighter scope and stronger deliverables."

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = json.loads(workflow_json[0].read_text(encoding="utf-8"))
    challenger_entries = [entry for entry in payload["history"] if entry["agent_type"] == "challenger"]
    assert len(challenger_entries) == 2
