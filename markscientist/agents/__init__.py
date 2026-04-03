"""MarkScientist agents built on top of ResearchHarness."""

from typing import TYPE_CHECKING

from markscientist.agents.base import AgentResult, BaseScientistAgent

if TYPE_CHECKING:
    from markscientist.agents.evaluator import EvaluatorAgent
    from markscientist.agents.judge import JudgeAgent
    from markscientist.agents.solver import SolverAgent


def __getattr__(name: str):
    if name == "SolverAgent":
        from markscientist.agents.solver import SolverAgent

        return SolverAgent
    if name == "JudgeAgent":
        from markscientist.agents.judge import JudgeAgent

        return JudgeAgent
    if name == "EvaluatorAgent":
        from markscientist.agents.evaluator import EvaluatorAgent

        return EvaluatorAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BaseScientistAgent",
    "AgentResult",
    "SolverAgent",
    "JudgeAgent",
    "EvaluatorAgent",
]
