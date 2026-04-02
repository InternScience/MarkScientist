"""Role-prompt definitions layered on top of ResearchHarness."""

from markscientist.prompts.v01_prompts import (
    EVALUATOR_ROLE_PROMPT,
    IMPROVEMENT_REQUEST_TEMPLATE,
    JUDGE_ROLE_PROMPT,
    META_EVALUATION_TEMPLATE,
    REVIEW_REQUEST_TEMPLATE,
    ROLE_PROMPTS,
    SOLVER_ROLE_PROMPT,
    get_role_prompt,
)

__all__ = [
    "SOLVER_ROLE_PROMPT",
    "JUDGE_ROLE_PROMPT",
    "EVALUATOR_ROLE_PROMPT",
    "ROLE_PROMPTS",
    "get_role_prompt",
    "REVIEW_REQUEST_TEMPLATE",
    "IMPROVEMENT_REQUEST_TEMPLATE",
    "META_EVALUATION_TEMPLATE",
]
