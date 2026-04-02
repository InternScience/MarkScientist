"""MarkScientist agents built on top of ResearchHarness."""

from markscientist.agents.base import AgentResult, BaseScientistAgent
from markscientist.agents.solver import SolverAgent
from markscientist.agents.judge import JudgeAgent
from markscientist.agents.evaluator import EvaluatorAgent

__all__ = [
    "BaseScientistAgent",
    "AgentResult",
    "SolverAgent",
    "JudgeAgent",
    "EvaluatorAgent",
]
