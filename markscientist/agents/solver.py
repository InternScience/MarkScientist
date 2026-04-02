from __future__ import annotations

from typing import Dict, Optional

from markscientist.config import get_config
from markscientist.harness import ensure_harness_on_path
from markscientist.prompts import SOLVER_ROLE_PROMPT
from markscientist.agents.base import BaseScientistAgent

ensure_harness_on_path(get_config().harness_path)

from agent_base import agent_role


@agent_role(name="solver", role_prompt=SOLVER_ROLE_PROMPT)
class SolverAgent(BaseScientistAgent):
    """Execution agent for research tasks."""

    agent_type = "solver"

    def solve(self, task: str, context: Optional[Dict] = None):
        return self.run(task, context=context)
