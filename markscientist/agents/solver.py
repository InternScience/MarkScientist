from __future__ import annotations

from markscientist.agents.base import BaseScientistAgent
from markscientist.prompts import SOLVER_ROLE_PROMPT

from agent_base import agent_role


@agent_role(name="solver", role_prompt=SOLVER_ROLE_PROMPT)
class SolverAgent(BaseScientistAgent):
    """Execution agent for prepared research projects."""

    agent_type = "solver"
