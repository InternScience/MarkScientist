from pathlib import Path

from markscientist.agents import BaseScientistAgent, ChallengerAgent, JudgeAgent, SolverAgent
from markscientist.config import Config, ModelConfig, TrajectoryConfig
from markscientist.harness import ensure_harness_on_path

ensure_harness_on_path()

from agent_base.react_agent import MultiTurnReactAgent


def test_agents_inherit_research_harness(tmp_path: Path):
    config = Config(
        model=ModelConfig(
            model_name="gpt-5.4",
            api_key="test-key",
            api_base="https://example.invalid/v1",
        ),
        workspace_root=tmp_path,
        trajectory=TrajectoryConfig(auto_save=False, save_dir=tmp_path / "traces"),
    )

    challenger = ChallengerAgent(config=config, workspace_root=tmp_path)
    solver = SolverAgent(config=config, workspace_root=tmp_path)
    judge = JudgeAgent(config=config, workspace_root=tmp_path)

    assert isinstance(challenger, BaseScientistAgent)
    assert isinstance(solver, BaseScientistAgent)
    assert isinstance(judge, BaseScientistAgent)
    assert isinstance(challenger, MultiTurnReactAgent)
    assert isinstance(solver, MultiTurnReactAgent)
    assert isinstance(judge, MultiTurnReactAgent)

    assert challenger.tool_names == ["Glob", "Grep", "Read", "Write", "Edit", "Bash"]
    assert solver.tool_names
    assert judge.tool_names == []
    assert solver._llm_api_key == "test-key"
    assert solver._llm_api_base == "https://example.invalid/v1"
    assert "Challenger agent of MarkScientist" in challenger.role_prompt
    assert "Solver agent of MarkScientist" in solver.role_prompt
    assert "Judge agent of MarkScientist" in judge.role_prompt
