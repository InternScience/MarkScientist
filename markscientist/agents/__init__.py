"""MarkScientist agents built on top of ResearchHarness.

Role Model (based on AI Scientist workflow):
    Proposer → Solver → Reviewer → Iteration

    - Proposer: Generates research questions, hypotheses, and problem statements
    - Solver: Executes tasks, implements solutions, runs experiments
    - Reviewer: Evaluates artifacts and provides feedback for iteration
"""

from markscientist.agents.base import AgentResult, BaseScientistAgent
from markscientist.agents.proposer import ProposerAgent, ProposalResult
from markscientist.agents.solver import SolverAgent
from markscientist.agents.reviewer import ReviewerAgent, ReviewResult, MetaEvaluationResult

# Legacy imports for backward compatibility
ChallengerAgent = ProposerAgent
ChallengeResult = ProposalResult
JudgerAgent = ReviewerAgent
JudgeAgent = ReviewerAgent
EvaluatorAgent = ReviewerAgent

__all__ = [
    "BaseScientistAgent",
    "AgentResult",
    # Primary agents
    "ProposerAgent",
    "ProposalResult",
    "SolverAgent",
    "ReviewerAgent",
    "ReviewResult",
    "MetaEvaluationResult",
    # Legacy aliases
    "ChallengerAgent",
    "ChallengeResult",
    "JudgerAgent",
    "JudgeAgent",
    "EvaluatorAgent",
]
