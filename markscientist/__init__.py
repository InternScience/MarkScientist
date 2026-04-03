"""
MarkScientist

Core modules:
- agents: Challenger, Solver, and Judge agent types
- prompts: Role-prompt definitions layered on top of ResearchHarness
- trajectory: Workflow-level trajectory wrappers around ResearchHarness traces
- workflow: Research workflows
"""

from typing import TYPE_CHECKING

__version__ = "0.1.0"
__author__ = "MarkScientist Team"

from markscientist.config import Config

if TYPE_CHECKING:
    from markscientist.agents.challenger import ChallengerAgent
    from markscientist.agents.judge import JudgeAgent
    from markscientist.agents.solver import SolverAgent
    from markscientist.workflow import ResearchWorkflow


def __getattr__(name: str):
    if name == "ChallengerAgent":
        from markscientist.agents.challenger import ChallengerAgent

        return ChallengerAgent
    if name == "SolverAgent":
        from markscientist.agents.solver import SolverAgent

        return SolverAgent
    if name == "JudgeAgent":
        from markscientist.agents.judge import JudgeAgent

        return JudgeAgent
    if name == "ResearchWorkflow":
        from markscientist.workflow import ResearchWorkflow

        return ResearchWorkflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Config",
    "ChallengerAgent",
    "SolverAgent",
    "JudgeAgent",
    "ResearchWorkflow",
    "__version__",
]
