import json
from pathlib import Path

from markscientist.agents.base import AgentResult
from markscientist.agents.judge import ReviewResult
from markscientist.cli import MarkScientistCLI, run_once
from markscientist.config import Config, TrajectoryConfig


class FakeAgent:
    def __init__(self, output: str, trace_path: str = ""):
        self.output = output
        self.trace_path = trace_path

    def run(self, prompt, workspace_root=None):
        return AgentResult(
            output=self.output,
            success=True,
            termination_reason="result",
            trace_path=self.trace_path,
        )


class FakeCLI(MarkScientistCLI):
    def __init__(self, config=None):
        super().__init__(config)
        self.challenger = FakeAgent("Challenge files created.")
        self.solver = FakeAgent("Report content")
        self.review = ReviewResult(
            overall_score=75.0,
            project_score=72.0,
            report_score=75.0,
            verdict="Acceptable",
            summary="Solid report.",
            strengths=["Good structure"],
            suggestions=["Add one more validation plot."],
            checklist_scores=[{"title": "Main Result", "mode": "objective", "score": 75.0, "reasoning": "Well supported."}],
            raw_output='{"overall_score": 75.0, "project_score": 72.0, "report_score": 75.0}',
        )

    def _get_agent(self, agent_type: str):
        if agent_type == "challenger":
            return self.challenger
        if agent_type == "solver":
            return self.solver
        if agent_type == "judge":
            return FakeAgent(json.dumps(self.review.to_dict(), ensure_ascii=False))
        raise ValueError(agent_type)

    def run_judge(self, prompt: str, show_spinner: bool = True):
        return self.review

    def run_workflow(self, prompt: str, show_spinner: bool = True):
        class WorkflowPayload:
            def to_dict(self_nonlocal):
                return {
                    "prompt": prompt,
                    "workspace_root": str(self._workspace_root()),
                    "challenge_output": "Challenge files created.",
                    "solver_output": "Report content",
                    "judge_review": self.review.to_dict(),
                    "final_score": 75.0,
                    "success": True,
                    "iterations": 1,
                    "metadata": {
                        "public_workspace_root": str(self._workspace_root() / "public"),
                        "report_path": str(self._workspace_root() / "public" / "report" / "report.md"),
                    },
                }

            solver_output = "Report content"
            success = True
            final_score = 75.0
            iterations = 1
            workspace_root = ""
            metadata = {"public_workspace_root": "", "report_path": ""}

        payload = WorkflowPayload()
        payload.workspace_root = str(self._workspace_root())
        payload.metadata = {
            "public_workspace_root": str(self._workspace_root() / "public"),
            "report_path": str(self._workspace_root() / "public" / "report" / "report.md"),
        }
        return payload


def test_run_once_workflow_json_output(monkeypatch, capsys, tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )
    monkeypatch.setattr("markscientist.cli.MarkScientistCLI", FakeCLI)

    exit_code = run_once(config, "build a project", agent_type=None, json_output=True)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["challenge_output"] == "Challenge files created."
    assert payload["judge_review"]["overall_score"] == 75.0


def test_run_once_single_agent_json_output(monkeypatch, capsys, tmp_path: Path):
    config = Config(
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )
    monkeypatch.setattr("markscientist.cli.MarkScientistCLI", FakeCLI)

    challenger_exit = run_once(config, "build a project", agent_type="challenger", json_output=True)
    assert challenger_exit == 0
    challenger_payload = json.loads(capsys.readouterr().out)
    assert challenger_payload["output"] == "Challenge files created."

    judge_exit = run_once(config, "score current report", agent_type="judge", json_output=True)
    assert judge_exit == 0
    judge_payload = json.loads(capsys.readouterr().out)
    assert judge_payload["overall_score"] == 75.0
    assert judge_payload["project_score"] == 72.0
    assert judge_payload["verdict"] == "Acceptable"


def test_cli_defaults_workspace_under_markscientist_data(monkeypatch, tmp_path: Path):
    config = Config(
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )
    workspaces_root = (tmp_path / "data" / "workspaces").resolve()
    monkeypatch.setattr(
        "markscientist.cli.default_workspace_root",
        lambda session_id: workspaces_root / session_id,
    )

    cli = MarkScientistCLI(config)

    assert cli._workspace_root().is_relative_to(workspaces_root)
