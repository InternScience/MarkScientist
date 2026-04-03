from __future__ import annotations

from markscientist.agents.base import BaseScientistAgent
from markscientist.prompts import CHALLENGER_ROLE_PROMPT

from agent_base import agent_role


@agent_role(
    name="challenger",
    role_prompt=CHALLENGER_ROLE_PROMPT,
    function_list=["Glob", "Grep", "Read", "Write", "Edit", "Bash"],
)
class ChallengerAgent(BaseScientistAgent):
    """Project-scoping agent that prepares a research workspace."""

    agent_type = "challenger"
