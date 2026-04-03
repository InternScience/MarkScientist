from __future__ import annotations

from markscientist.prompts import SOLVER_ROLE_PROMPT
from markscientist.agents.base import BaseScientistAgent

from agent_base import agent_role


@agent_role(name="solver", role_prompt=SOLVER_ROLE_PROMPT)
class SolverAgent(BaseScientistAgent):
    """Execution agent for research tasks."""

    agent_type = "solver"
