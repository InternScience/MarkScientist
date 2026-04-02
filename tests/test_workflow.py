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

    def run(self, task, context=None, workspace_dir=None):
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

    def review(self, artifact, artifact_type="auto", requirements=None):
        review = self.reviews[self.index]
        self.index += 1
        review.metadata = {"trace_path": str(self.trace_path)}
        review.termination_reason = "result"
        return review


class FakeEvaluator:
    def __init__(self, trace_path):
        self.trace_path = trace_path

    def evaluate(self, **kwargs):
        return MetaEvaluationResult(
            solver_assessment={"performance_score": 8},
            judge_assessment={"accuracy_score": 7},
            system_insights={"recommended_adjustments": ["tighten review rubric"]},
            success_probability=0.82,
            confidence=0.8,
            meta_summary="System is improving.",
            raw_output='{"success_probability": 0.82}',
            termination_reason="result",
            metadata={"trace_path": str(self.trace_path)},
        )


class DummyWorkflow(BasicResearchWorkflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_solver = None
        self.fake_judge = None
        self.fake_evaluator = None

    def _new_solver(self, workspace, trace_path, on_event=None):
        if self.fake_solver is None:
            self.fake_solver = FakeSolver(
                outputs=["initial draft", "improved draft"],
                trace_path=trace_path or workspace / "solver.jsonl",
            )
        return self.fake_solver

    def _new_judge(self, workspace, trace_path, on_event=None):
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
                trace_path=trace_path or workspace / "judge.jsonl",
            )
        return self.fake_judge

    def _new_evaluator(self, workspace, trace_path, on_event=None):
        if self.fake_evaluator is None:
            self.fake_evaluator = FakeEvaluator(trace_path or workspace / "evaluator.jsonl")
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

    workflow_json = list((tmp_path / "traces").glob("*_workflow.json"))
    assert len(workflow_json) == 1
    payload = workflow_json[0].read_text(encoding="utf-8")
    assert "initial draft" in payload or "improved draft" in payload
    assert "solver" in payload
    assert "judge" in payload
    assert "evaluator" in payload
