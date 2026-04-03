import json
from pathlib import Path

from markscientist.agents.base import AgentResult
from markscientist.agents.evaluator import MetaEvaluationResult
from markscientist.agents.judge import ReviewResult
from markscientist.cli import MarkScientistCLI, run_once
from markscientist.config import Config, TrajectoryConfig


class FakeSolverAgent:
    def run(self, prompt, workspace_root=None):
        return AgentResult(
            output="solver output",
            success=True,
            termination_reason="result",
            metadata={"trace_path": ""},
        )


class FakeJudgeAgent:
    def __init__(self):
        self.prompts = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
        review = ReviewResult(
            task_type="code_analysis",
            overall_score=7.5,
            verdict="Good",
            summary="Looks solid.",
            raw_output='{"overall_score": 7.5}',
        )
        return AgentResult(
            output=json.dumps(review.to_dict(), ensure_ascii=False),
            success=True,
            termination_reason="result",
            metadata={"trace_path": ""},
        )


class FakeEvaluatorAgent:
    def __init__(self):
        self.prompts = []

    def run(self, prompt, workspace_root=None):
        self.prompts.append(prompt)
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
            metadata={"trace_path": ""},
        )


class FakeCLI(MarkScientistCLI):
    def __init__(self, config=None):
        super().__init__(config)
        self.solver = FakeSolverAgent()
        self.judge = FakeJudgeAgent()
        self.evaluator = FakeEvaluatorAgent()

    def _get_agent(self, agent_type: str):
        if agent_type == "solver":
            return self.solver
        if agent_type == "judge":
            return self.judge
        if agent_type == "evaluator":
            return self.evaluator
        raise ValueError(agent_type)


def test_run_query_uses_specialized_review_paths(tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )
    cli = FakeCLI(config)
    cli._last_prompt = "prior prompt"
    cli._last_output = "prior output"
    cli._last_review_raw = '{"overall_score": 7.5}'

    review_payload = json.loads(cli.run_query("artifact body", "judge", show_spinner=False))
    eval_payload = json.loads(cli.run_query("evaluate session", "evaluator", show_spinner=False))

    assert review_payload["overall_score"] == 7.5
    assert "artifact body" in cli.judge.prompts[0]
    assert eval_payload["success_probability"] == 0.82
    assert "prior output" in cli.evaluator.prompts[0]


def test_run_once_solver_json_output(monkeypatch, capsys, tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )

    monkeypatch.setattr("markscientist.cli.MarkScientistCLI", FakeCLI)

    exit_code = run_once(
        config,
        "solve this",
        agent_type="solver",
        workflow=False,
        json_output=True,
        auto_review=True,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["solver"]["output"] == "solver output"
    assert payload["judge"]["overall_score"] == 7.5


def test_run_once_judge_and_evaluator_json_output(monkeypatch, capsys, tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )

    monkeypatch.setattr("markscientist.cli.MarkScientistCLI", FakeCLI)

    judge_exit_code = run_once(
        config,
        "review this artifact",
        agent_type="judge",
        workflow=False,
        json_output=True,
        auto_review=False,
    )
    assert judge_exit_code == 0
    judge_payload = json.loads(capsys.readouterr().out)
    assert judge_payload["overall_score"] == 7.5
    assert "output" not in judge_payload

    evaluator_exit_code = run_once(
        config,
        "evaluate this session",
        agent_type="evaluator",
        workflow=False,
        json_output=True,
        auto_review=False,
    )
    assert evaluator_exit_code == 0
    evaluator_payload = json.loads(capsys.readouterr().out)
    assert evaluator_payload["success_probability"] == 0.82
    assert "output" not in evaluator_payload
