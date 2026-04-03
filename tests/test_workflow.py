import json
from pathlib import Path

from markscientist.agents.base import AgentResult
from markscientist.agents.evaluator import MetaEvaluationResult
from markscientist.agents.judge import ReviewResult
from markscientist.config import Config, TrajectoryConfig
from markscientist.workflow.basic import BasicResearchWorkflow


class FakeSolver:
    def __init__(self, outputs, trace_path):
        self.outputs = outputs
        self.trace_path = trace_path
        self.index = 0

    def run(self, prompt, workspace_root=None):
        output = self.outputs[self.index]
        self.index += 1
        return AgentResult(
            output=output,
            success=True,
            termination_reason="result",
            metadata={"trace_path": str(self.trace_path)},
        )


class FakeJudge:
    def __init__(self, reviews, trace_path):
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
            metadata={"trace_path": str(self.trace_path)},
        )


class FakeEvaluator:
    def __init__(self, trace_path):
        self.trace_path = trace_path

    def run(self, prompt, workspace_root=None):
        evaluation = MetaEvaluationResult(
            solver_assessment={"performance_score": 8},
            judge_assessment={"accuracy_score": 7},
            system_insights={"recommended_adjustments": ["tighten review rubric"]},
            success_probability=0.82,
            confidence=0.8,
            meta_summary="System is improving.",
            raw_output='{"success_probability": 0.82}',
        )
        return AgentResult(
            output=json.dumps(evaluation.to_dict(), ensure_ascii=False),
            success=True,
            termination_reason="result",
            metadata={"trace_path": str(self.trace_path)},
        )


class DummyWorkflow(BasicResearchWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_solver = None
        self.fake_judge = None
        self.fake_evaluator = None

    def _new_solver(self, workspace_root, trace_dir, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = FakeSolver(
                outputs=["initial draft", "improved draft"],
                trace_path=(trace_dir / "solver.jsonl") if trace_dir else workspace_root / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        task_type="writing_draft",
                        overall_score=5.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        raw_output='{"overall_score": 5.0}',
                    ),
                    ReviewResult(
                        task_type="writing_draft",
                        overall_score=7.5,
                        verdict="Good",
                        summary="Much better.",
                        raw_output='{"overall_score": 7.5}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
            )
        return self.fake_judge

    def _new_evaluator(self, workspace_root, trace_dir, on_event=None):
        if self.fake_evaluator is None:
            self.fake_evaluator = FakeEvaluator((trace_dir / "evaluator.jsonl") if trace_dir else workspace_root / "evaluator.jsonl")
        return self.fake_evaluator


def test_workflow_wraps_agent_traces(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = DummyWorkflow(config=config, save_dir=config.trajectory.save_dir)

    result = workflow.run("Write a literature review.", workspace_root=tmp_path)

    assert result.success is True
    assert result.iterations == 2
    assert result.final_score == 7.5
    assert result.improved_output == "improved draft"

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert "initial draft" in payload or "improved draft" in payload
    assert "solver" in payload
    assert "judge" in payload
    assert "evaluator" in payload
    assert "history" in payload


class RejectedImprovementWorkflow(DummyWorkflow):
    def _new_judge(self, workspace_root, trace_dir, on_event=None):
        if self.fake_judge is None:
            self.fake_judge = FakeJudge(
                reviews=[
                    ReviewResult(
                        task_type="writing_draft",
                        overall_score=5.0,
                        verdict="Needs Improvement",
                        summary="Too weak.",
                        raw_output='{"overall_score": 5.0}',
                    ),
                    ReviewResult(
                        task_type="writing_draft",
                        overall_score=5.5,
                        verdict="Still Weak",
                        summary="Not enough improvement.",
                        raw_output='{"overall_score": 5.5}',
                    ),
                ],
                trace_path=(trace_dir / "judge.jsonl") if trace_dir else workspace_root / "judge.jsonl",
            )
        return self.fake_judge


def test_workflow_keeps_last_accepted_output(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=True, save_dir=tmp_path / "traces"),
    )
    workflow = RejectedImprovementWorkflow(
        config=config,
        save_dir=config.trajectory.save_dir,
        max_improvement_iterations=2,
    )

    result = workflow.run("Write a literature review.", workspace_root=tmp_path)

    assert result.success is False
    assert result.solver_output == "initial draft"
    assert result.improved_output is None

    workflow_json = list((tmp_path / "traces").glob("**/workflow_*.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert '"final_output_preview": "initial draft"' in payload
