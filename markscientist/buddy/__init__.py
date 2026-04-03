"""
MarkScientist Reviewer Buddy System

Fun reviewer characters that bring personality to the Judge agent.

Enhanced with JudgeBuddy system providing:
1. Scenario adaptation for different auto-research workflow stages
2. Researcher roles with specialized evaluation focus
3. Judge skill integration for different scoring methodologies
"""

from .types import (
    ReviewerBuddy,
    REVIEWER_SPECIES,
    PERSONALITIES,
    TASK_REVIEWER_AFFINITY,
    EYES,
)
from .sprites import (
    render_face,
    render_sprite,
    render_sprite_string,
    get_reaction,
    get_mood_from_score,
    render_review_header,
)
from .judge_buddy import (
    # Enums
    ResearchScenario,
    ResearcherRole,
    JudgeSkill,
    # Configs
    SCENARIO_CONFIGS,
    RESEARCHER_ROLE_CONFIGS,
    SKILL_CONFIGS,
    # Classes
    JudgeBuddy,
    JudgePanel,
    # Factory functions
    get_judge_for_scenario,
    get_panel_for_scenario,
)

__all__ = [
    # Base ReviewerBuddy
    'ReviewerBuddy',
    'REVIEWER_SPECIES',
    'PERSONALITIES',
    'TASK_REVIEWER_AFFINITY',
    'EYES',
    'render_face',
    'render_sprite',
    'render_sprite_string',
    'get_reaction',
    'get_mood_from_score',
    'render_review_header',
    # Enhanced JudgeBuddy
    'ResearchScenario',
    'ResearcherRole',
    'JudgeSkill',
    'SCENARIO_CONFIGS',
    'RESEARCHER_ROLE_CONFIGS',
    'SKILL_CONFIGS',
    'JudgeBuddy',
    'JudgePanel',
    'get_judge_for_scenario',
    'get_panel_for_scenario',
]
