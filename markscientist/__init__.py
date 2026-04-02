"""
MarkScientist v0.1 - Self-evolving Research Agent with Built-in Scientific Taste

Core modules:
- agents: Three specialized agent types
- prompts: Role-prompt definitions layered on top of ResearchHarness
- trajectory: Workflow-level trajectory wrappers around ResearchHarness traces
- workflow: Research workflows
"""

__version__ = "0.1.0"
__author__ = "MarkScientist Team"

from markscientist.config import Config
from markscientist.agents.solver import SolverAgent
from markscientist.agents.judge import JudgeAgent
from markscientist.agents.evaluator import EvaluatorAgent

__all__ = [
    "Config",
    "SolverAgent",
    "JudgeAgent",
    "EvaluatorAgent",
    "__version__",
]
