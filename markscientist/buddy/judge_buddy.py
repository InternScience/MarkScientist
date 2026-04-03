"""
MarkScientist Judge Buddy System

Enhanced reviewer buddies with three core capabilities:
1. Scenario Adaptation - Adapts to different auto-research workflow stages
2. Researcher Roles - Different reviewer personas with specialized focus
3. Skill Integration - Loads appropriate scoring methodologies from judge skills

Design inspired by:
- DeepEval G-Eval
- Prometheus-Eval
- AlpacaEval
- PandaLM
- JudgeLM
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from .types import ReviewerBuddy, PERSONALITIES, TASK_REVIEWER_AFFINITY, EYES
from .sprites import render_face, get_reaction


# =============================================================================
# 1. SCENARIO ADAPTATION - Auto-research workflow stages
# =============================================================================

class ResearchScenario(Enum):
    """Auto-research workflow scenarios that need different evaluation approaches."""

    # Idea Discovery Phase
    IDEA_GENERATION = "idea_generation"      # Evaluating brainstormed ideas
    NOVELTY_CHECK = "novelty_check"          # Checking idea novelty against literature
    IDEA_REFINEMENT = "idea_refinement"      # Evaluating refined research proposals

    # Experiment Phase
    EXPERIMENT_DESIGN = "experiment_design"  # Evaluating experiment plans
    RESULT_ANALYSIS = "result_analysis"      # Evaluating experimental results
    CLAIM_VALIDATION = "claim_validation"    # Result-to-claim evaluation
    ABLATION_REVIEW = "ablation_review"      # Evaluating ablation study design

    # Paper Writing Phase
    PAPER_OUTLINE = "paper_outline"          # Evaluating paper structure
    SECTION_DRAFT = "section_draft"          # Evaluating draft sections
    FIGURE_TABLE = "figure_table"            # Evaluating figures and tables
    FULL_PAPER = "full_paper"                # Full paper review

    # Review Phase
    REBUTTAL = "rebuttal"                    # Evaluating rebuttal responses
    REVISION = "revision"                    # Evaluating paper revisions

    # General
    CODE_REVIEW = "code_review"              # Evaluating code quality
    LITERATURE_REVIEW = "literature_review"  # Evaluating lit review coverage


SCENARIO_CONFIGS: Dict[ResearchScenario, Dict[str, Any]] = {
    ResearchScenario.IDEA_GENERATION: {
        "primary_dimensions": ["novelty", "feasibility", "impact", "clarity"],
        "recommended_skill": "geval",
        "recommended_roles": ["novelty_critic", "senior_reviewer"],
        "strictness": "lenient",  # Early stage, encourage exploration
        "description": "Evaluate brainstormed research ideas",
    },
    ResearchScenario.NOVELTY_CHECK: {
        "primary_dimensions": ["originality", "differentiation", "gap_identification"],
        "recommended_skill": "pairwise",  # Compare with existing work
        "recommended_roles": ["novelty_critic", "literature_expert"],
        "strictness": "strict",
        "description": "Verify idea novelty against existing literature",
    },
    ResearchScenario.IDEA_REFINEMENT: {
        "primary_dimensions": ["rigor", "specificity", "testability", "scope"],
        "recommended_skill": "prometheus",
        "recommended_roles": ["methods_expert", "senior_reviewer"],
        "strictness": "moderate",
        "description": "Evaluate refined research proposals",
    },
    ResearchScenario.EXPERIMENT_DESIGN: {
        "primary_dimensions": ["methodology", "validity", "reproducibility", "efficiency"],
        "recommended_skill": "geval",
        "recommended_roles": ["methods_expert", "reproducibility_advocate"],
        "strictness": "strict",
        "description": "Evaluate experiment design and methodology",
    },
    ResearchScenario.RESULT_ANALYSIS: {
        "primary_dimensions": ["accuracy", "interpretation", "statistical_rigor", "limitations"],
        "recommended_skill": "prometheus",
        "recommended_roles": ["statistics_expert", "methods_expert"],
        "strictness": "strict",
        "description": "Evaluate experimental results and analysis",
    },
    ResearchScenario.CLAIM_VALIDATION: {
        "primary_dimensions": ["evidence_support", "claim_scope", "overclaim_detection"],
        "recommended_skill": "judgelm",
        "recommended_roles": ["senior_reviewer", "skeptic"],
        "strictness": "very_strict",
        "description": "Validate claims against evidence",
    },
    ResearchScenario.ABLATION_REVIEW: {
        "primary_dimensions": ["coverage", "isolation", "necessity", "insight"],
        "recommended_skill": "geval",
        "recommended_roles": ["methods_expert", "senior_reviewer"],
        "strictness": "strict",
        "description": "Evaluate ablation study completeness",
    },
    ResearchScenario.PAPER_OUTLINE: {
        "primary_dimensions": ["structure", "flow", "completeness", "balance"],
        "recommended_skill": "prometheus",
        "recommended_roles": ["writing_expert", "senior_reviewer"],
        "strictness": "moderate",
        "description": "Evaluate paper outline and structure",
    },
    ResearchScenario.SECTION_DRAFT: {
        "primary_dimensions": ["clarity", "coherence", "technical_depth", "conciseness"],
        "recommended_skill": "geval",
        "recommended_roles": ["writing_expert", "domain_expert"],
        "strictness": "moderate",
        "description": "Evaluate draft paper sections",
    },
    ResearchScenario.FIGURE_TABLE: {
        "primary_dimensions": ["clarity", "informativeness", "aesthetics", "caption_quality"],
        "recommended_skill": "prometheus",
        "recommended_roles": ["writing_expert", "visualization_expert"],
        "strictness": "moderate",
        "description": "Evaluate figures and tables",
    },
    ResearchScenario.FULL_PAPER: {
        "primary_dimensions": ["novelty", "rigor", "clarity", "impact", "reproducibility"],
        "recommended_skill": "pandalm",  # Full comparison with reference
        "recommended_roles": ["senior_reviewer", "area_chair"],
        "strictness": "strict",
        "description": "Full paper review (NeurIPS/ICML level)",
    },
    ResearchScenario.REBUTTAL: {
        "primary_dimensions": ["responsiveness", "evidence", "clarity", "diplomacy"],
        "recommended_skill": "pairwise",
        "recommended_roles": ["senior_reviewer", "writing_expert"],
        "strictness": "moderate",
        "description": "Evaluate rebuttal responses",
    },
    ResearchScenario.REVISION: {
        "primary_dimensions": ["improvement", "completeness", "consistency"],
        "recommended_skill": "pairwise",  # Compare before/after
        "recommended_roles": ["senior_reviewer", "methods_expert"],
        "strictness": "strict",
        "description": "Evaluate paper revisions",
    },
    ResearchScenario.CODE_REVIEW: {
        "primary_dimensions": ["correctness", "efficiency", "readability", "reproducibility"],
        "recommended_skill": "geval",
        "recommended_roles": ["code_expert", "reproducibility_advocate"],
        "strictness": "strict",
        "description": "Evaluate code quality and correctness",
    },
    ResearchScenario.LITERATURE_REVIEW: {
        "primary_dimensions": ["coverage", "synthesis", "organization", "recency"],
        "recommended_skill": "prometheus",
        "recommended_roles": ["literature_expert", "domain_expert"],
        "strictness": "moderate",
        "description": "Evaluate literature review coverage",
    },
}


# =============================================================================
# 2. RESEARCHER ROLES - Different reviewer personas
# =============================================================================

class ResearcherRole(Enum):
    """Researcher personas with different evaluation focus areas."""

    SENIOR_REVIEWER = "senior_reviewer"
    NOVELTY_CRITIC = "novelty_critic"
    METHODS_EXPERT = "methods_expert"
    STATISTICS_EXPERT = "statistics_expert"
    WRITING_EXPERT = "writing_expert"
    DOMAIN_EXPERT = "domain_expert"
    LITERATURE_EXPERT = "literature_expert"
    CODE_EXPERT = "code_expert"
    REPRODUCIBILITY_ADVOCATE = "reproducibility_advocate"
    SKEPTIC = "skeptic"
    AREA_CHAIR = "area_chair"
    VISUALIZATION_EXPERT = "visualization_expert"


RESEARCHER_ROLE_CONFIGS: Dict[ResearcherRole, Dict[str, Any]] = {
    ResearcherRole.SENIOR_REVIEWER: {
        "name": "Prof. Reviewer",
        "title": "Senior Reviewer",
        "focus": "Overall quality and publishability",
        "traits": ["experienced", "balanced", "thorough"],
        "bias_toward": ["impact", "novelty", "significance"],
        "buddy_species": "owl",
        "catchphrase": "Let's evaluate the big picture...",
        "review_style": "balanced",
        "prompt_modifier": """You are a senior reviewer with 10+ years of experience at top venues.
Focus on: overall contribution, significance, and whether this advances the field.
Be fair but maintain high standards. Consider both strengths and weaknesses.""",
    },
    ResearcherRole.NOVELTY_CRITIC: {
        "name": "Dr. Novel",
        "title": "Novelty Critic",
        "focus": "Originality and differentiation from prior work",
        "traits": ["critical", "well-read", "demanding"],
        "bias_toward": ["novelty", "originality", "differentiation"],
        "buddy_species": "ghost",
        "catchphrase": "I've seen something similar before...",
        "review_style": "critical",
        "prompt_modifier": """You are a novelty critic who has read extensively in this field.
Focus on: Is this truly novel? How does it differ from prior work? Is the contribution incremental?
Be skeptical of novelty claims. Point out any overlap with existing work.""",
    },
    ResearcherRole.METHODS_EXPERT: {
        "name": "Dr. Methods",
        "title": "Methodology Expert",
        "focus": "Experimental design and methodological rigor",
        "traits": ["rigorous", "detail-oriented", "systematic"],
        "bias_toward": ["methodology", "validity", "soundness"],
        "buddy_species": "robot",
        "catchphrase": "Let me check the methodology...",
        "review_style": "systematic",
        "prompt_modifier": """You are a methodology expert focused on experimental rigor.
Focus on: Is the experimental design sound? Are baselines appropriate? Are comparisons fair?
Check for methodological flaws, confounds, and missing controls.""",
    },
    ResearcherRole.STATISTICS_EXPERT: {
        "name": "Prof. Stats",
        "title": "Statistics Expert",
        "focus": "Statistical validity and analysis correctness",
        "traits": ["quantitative", "precise", "skeptical"],
        "bias_toward": ["statistical_rigor", "significance", "sample_size"],
        "buddy_species": "robot",
        "catchphrase": "What's the p-value?",
        "review_style": "quantitative",
        "prompt_modifier": """You are a statistics expert reviewing the analysis.
Focus on: Are statistical tests appropriate? Is significance properly reported? Sample sizes adequate?
Look for p-hacking, multiple comparisons issues, and overfitting.""",
    },
    ResearcherRole.WRITING_EXPERT: {
        "name": "Dr. Clarity",
        "title": "Writing Expert",
        "focus": "Clarity, organization, and presentation",
        "traits": ["articulate", "organized", "reader-focused"],
        "bias_toward": ["clarity", "structure", "readability"],
        "buddy_species": "cat",
        "catchphrase": "This could be clearer...",
        "review_style": "editorial",
        "prompt_modifier": """You are a writing expert focused on presentation quality.
Focus on: Is the writing clear? Is the paper well-organized? Are figures effective?
Suggest improvements for clarity and readability.""",
    },
    ResearcherRole.DOMAIN_EXPERT: {
        "name": "Prof. Domain",
        "title": "Domain Expert",
        "focus": "Technical correctness in the specific domain",
        "traits": ["expert", "technical", "knowledgeable"],
        "bias_toward": ["technical_correctness", "domain_knowledge"],
        "buddy_species": "dragon",
        "catchphrase": "From a domain perspective...",
        "review_style": "technical",
        "prompt_modifier": """You are a domain expert with deep knowledge in this area.
Focus on: Is the technical content correct? Are domain-specific details handled properly?
Check for technical errors and misunderstandings of the field.""",
    },
    ResearcherRole.LITERATURE_EXPERT: {
        "name": "Dr. Literature",
        "title": "Literature Expert",
        "focus": "Related work coverage and positioning",
        "traits": ["well-read", "comprehensive", "fair"],
        "bias_toward": ["coverage", "positioning", "citations"],
        "buddy_species": "octopus",
        "catchphrase": "Have you considered the work by...",
        "review_style": "comprehensive",
        "prompt_modifier": """You are a literature expert who knows the field comprehensively.
Focus on: Is related work adequately covered? Are important papers missing? Is positioning fair?
Suggest missing references and check for misattributions.""",
    },
    ResearcherRole.CODE_EXPERT: {
        "name": "Dr. Code",
        "title": "Code Expert",
        "focus": "Code quality and implementation correctness",
        "traits": ["practical", "detail-oriented", "efficient"],
        "bias_toward": ["correctness", "efficiency", "reproducibility"],
        "buddy_species": "robot",
        "catchphrase": "Let me check the implementation...",
        "review_style": "technical",
        "prompt_modifier": """You are a code expert reviewing the implementation.
Focus on: Is the code correct? Are there bugs? Is it efficient and well-structured?
Check for implementation issues that could affect results.""",
    },
    ResearcherRole.REPRODUCIBILITY_ADVOCATE: {
        "name": "Dr. Reproduce",
        "title": "Reproducibility Advocate",
        "focus": "Reproducibility and openness",
        "traits": ["thorough", "practical", "skeptical"],
        "bias_toward": ["reproducibility", "details", "artifacts"],
        "buddy_species": "cat",
        "catchphrase": "Can I reproduce this?",
        "review_style": "practical",
        "prompt_modifier": """You are a reproducibility advocate checking if results can be reproduced.
Focus on: Are hyperparameters specified? Is code available? Are datasets described?
Identify any missing details needed for reproduction.""",
    },
    ResearcherRole.SKEPTIC: {
        "name": "Dr. Skeptic",
        "title": "The Skeptic",
        "focus": "Finding flaws and challenging claims",
        "traits": ["critical", "thorough", "demanding"],
        "bias_toward": ["validity", "soundness", "evidence"],
        "buddy_species": "ghost",
        "catchphrase": "I'm not convinced...",
        "review_style": "adversarial",
        "prompt_modifier": """You are a skeptical reviewer who challenges every claim.
Focus on: Are claims supported by evidence? What could go wrong? What's missing?
Be constructively critical. Find weaknesses but suggest how to address them.""",
    },
    ResearcherRole.AREA_CHAIR: {
        "name": "AC Chair",
        "title": "Area Chair",
        "focus": "Meta-review and decision making",
        "traits": ["balanced", "decisive", "experienced"],
        "bias_toward": ["overall_quality", "impact", "fit"],
        "buddy_species": "dragon",
        "catchphrase": "Weighing all perspectives...",
        "review_style": "meta",
        "prompt_modifier": """You are an area chair making acceptance decisions.
Focus on: Overall quality, impact, and fit for the venue. Weigh strengths vs weaknesses.
Provide a balanced assessment and clear recommendation.""",
    },
    ResearcherRole.VISUALIZATION_EXPERT: {
        "name": "Dr. Visual",
        "title": "Visualization Expert",
        "focus": "Figures, tables, and visual presentation",
        "traits": ["aesthetic", "clear", "informative"],
        "bias_toward": ["clarity", "informativeness", "design"],
        "buddy_species": "octopus",
        "catchphrase": "A picture is worth a thousand words...",
        "review_style": "visual",
        "prompt_modifier": """You are a visualization expert reviewing figures and tables.
Focus on: Are figures clear and informative? Are axes labeled? Are colors accessible?
Suggest improvements for visual presentation.""",
    },
}


# =============================================================================
# 3. SKILL INTEGRATION - Judge skill capabilities
# =============================================================================

class JudgeSkill(Enum):
    """Available judge skills from .claude/skills/."""

    GEVAL = "geval"           # G-Eval multi-dimensional scoring
    PROMETHEUS = "prometheus"  # Rubric-based absolute/relative grading
    PAIRWISE = "pairwise"     # AlpacaEval-style win rate
    PANDALM = "pandalm"       # Reproducible evaluation with reference
    JUDGELM = "judgelm"       # Scalable judging with bias mitigation


SKILL_CONFIGS: Dict[JudgeSkill, Dict[str, Any]] = {
    JudgeSkill.GEVAL: {
        "skill_path": "judge-geval",
        "description": "Multi-dimensional Chain-of-Thought evaluation",
        "source": "DeepEval (14k+ stars)",
        "best_for": ["detailed_scoring", "multi_dimension", "cot_reasoning"],
        "output_format": "dimension_scores + overall_score (1-5)",
        "supports_pairwise": False,
        "supports_reference": True,
        "bias_mitigation": ["chain_of_thought"],
    },
    JudgeSkill.PROMETHEUS: {
        "skill_path": "judge-prometheus",
        "description": "Custom rubric-based evaluation",
        "source": "Prometheus-Eval (1k+ stars)",
        "best_for": ["custom_rubrics", "absolute_grading", "relative_grading"],
        "output_format": "score (1-5) + feedback",
        "supports_pairwise": True,
        "supports_reference": True,
        "bias_mitigation": ["explicit_rubric"],
    },
    JudgeSkill.PAIRWISE: {
        "skill_path": "judge-pairwise",
        "description": "Head-to-head comparison with win rate",
        "source": "AlpacaEval (2k+ stars)",
        "best_for": ["model_comparison", "a_b_testing", "ranking"],
        "output_format": "winner (A/B/Tie) + confidence",
        "supports_pairwise": True,
        "supports_reference": False,
        "bias_mitigation": ["length_control", "swap_augmentation"],
    },
    JudgeSkill.PANDALM: {
        "skill_path": "judge-pandalm",
        "description": "Reproducible evaluation with tie detection",
        "source": "PandaLM (900+ stars)",
        "best_for": ["reproducible_eval", "tie_detection", "reference_generation"],
        "output_format": "result (1/2/Tie) + reason + reference",
        "supports_pairwise": True,
        "supports_reference": True,
        "bias_mitigation": ["consistency_check"],
    },
    JudgeSkill.JUDGELM: {
        "skill_path": "judge-rubric",
        "description": "Scalable judging with bias mitigation",
        "source": "JudgeLM (400+ stars, ICLR 2025)",
        "best_for": ["bias_free", "multi_mode", "high_agreement"],
        "output_format": "scores + consistency metrics",
        "supports_pairwise": True,
        "supports_reference": True,
        "bias_mitigation": ["swap_augmentation", "reference_support", "reference_drop"],
    },
}


# =============================================================================
# JUDGE BUDDY - Unified judge character with all three capabilities
# =============================================================================

@dataclass
class JudgeBuddy:
    """
    Enhanced reviewer buddy with three core capabilities:
    1. Scenario adaptation for different research workflow stages
    2. Researcher role with specialized focus
    3. Judge skill integration for scoring methodology
    """

    # Core identity
    name: str
    title: str
    species: str

    # Capability 1: Scenario
    scenario: ResearchScenario
    scenario_config: Dict[str, Any] = field(default_factory=dict)

    # Capability 2: Role
    role: ResearcherRole = ResearcherRole.SENIOR_REVIEWER
    role_config: Dict[str, Any] = field(default_factory=dict)

    # Capability 3: Skill
    skill: JudgeSkill = JudgeSkill.GEVAL
    skill_config: Dict[str, Any] = field(default_factory=dict)

    # Visual
    eye: str = '•'
    mood: str = 'neutral'
    color: str = 'blue'

    # Evaluation state
    strictness: str = "moderate"
    dimensions: List[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        scenario: ResearchScenario,
        role: Optional[ResearcherRole] = None,
        skill: Optional[JudgeSkill] = None,
        mood: str = 'neutral',
    ) -> 'JudgeBuddy':
        """
        Create a JudgeBuddy configured for a specific scenario.

        Auto-selects role and skill based on scenario if not specified.
        """
        scenario_cfg = SCENARIO_CONFIGS[scenario]

        # Auto-select role if not specified
        if role is None:
            recommended_roles = scenario_cfg.get("recommended_roles", ["senior_reviewer"])
            role = ResearcherRole(recommended_roles[0])

        # Auto-select skill if not specified
        if skill is None:
            recommended_skill = scenario_cfg.get("recommended_skill", "geval")
            skill = JudgeSkill(recommended_skill)

        role_cfg = RESEARCHER_ROLE_CONFIGS[role]
        skill_cfg = SKILL_CONFIGS[skill]

        return cls(
            name=role_cfg["name"],
            title=role_cfg["title"],
            species=role_cfg["buddy_species"],
            scenario=scenario,
            scenario_config=scenario_cfg,
            role=role,
            role_config=role_cfg,
            skill=skill,
            skill_config=skill_cfg,
            eye=EYES.get(mood, EYES['neutral']),
            mood=mood,
            color=PERSONALITIES[role_cfg["buddy_species"]]["color"],
            strictness=scenario_cfg.get("strictness", "moderate"),
            dimensions=scenario_cfg.get("primary_dimensions", ["quality"]),
        )

    @classmethod
    def for_idea_review(cls, critical: bool = False) -> 'JudgeBuddy':
        """Create a buddy for reviewing research ideas."""
        role = ResearcherRole.NOVELTY_CRITIC if critical else ResearcherRole.SENIOR_REVIEWER
        return cls.create(ResearchScenario.IDEA_GENERATION, role=role)

    @classmethod
    def for_experiment_review(cls) -> 'JudgeBuddy':
        """Create a buddy for reviewing experiment design."""
        return cls.create(ResearchScenario.EXPERIMENT_DESIGN)

    @classmethod
    def for_paper_review(cls, full: bool = True) -> 'JudgeBuddy':
        """Create a buddy for paper review."""
        scenario = ResearchScenario.FULL_PAPER if full else ResearchScenario.SECTION_DRAFT
        return cls.create(scenario)

    @classmethod
    def for_code_review(cls) -> 'JudgeBuddy':
        """Create a buddy for code review."""
        return cls.create(ResearchScenario.CODE_REVIEW, role=ResearcherRole.CODE_EXPERT)

    @classmethod
    def for_claim_validation(cls) -> 'JudgeBuddy':
        """Create a buddy for result-to-claim validation."""
        return cls.create(ResearchScenario.CLAIM_VALIDATION, role=ResearcherRole.SKEPTIC)

    def get_system_prompt(self) -> str:
        """Generate the full system prompt combining all three capabilities."""
        parts = [
            f"# Judge: {self.name} ({self.title})",
            "",
            "## Scenario Context",
            f"You are evaluating: {self.scenario_config.get('description', self.scenario.value)}",
            f"Strictness level: {self.strictness}",
            "",
            "## Your Role",
            self.role_config.get("prompt_modifier", ""),
            "",
            "## Evaluation Dimensions",
            "Focus on these dimensions:",
        ]

        for dim in self.dimensions:
            parts.append(f"- {dim}")

        parts.extend([
            "",
            "## Scoring Methodology",
            f"Using: {self.skill_config.get('description', self.skill.value)}",
            f"Output format: {self.skill_config.get('output_format', 'score + feedback')}",
        ])

        # Add bias mitigation
        bias_methods = self.skill_config.get("bias_mitigation", [])
        if bias_methods:
            parts.extend([
                "",
                "## Bias Mitigation",
                "Apply these techniques:",
            ])
            for method in bias_methods:
                parts.append(f"- {method}")

        return "\n".join(parts)

    def get_catchphrase(self) -> str:
        """Get the buddy's catchphrase."""
        return self.role_config.get("catchphrase", "Let me evaluate this...")

    def get_intro(self) -> str:
        """Get introduction message."""
        return f"{self.get_catchphrase()}"

    def get_skill_path(self) -> str:
        """Get the path to the judge skill."""
        return self.skill_config.get("skill_path", "judge-geval")

    def supports_pairwise(self) -> bool:
        """Check if the skill supports pairwise comparison."""
        return self.skill_config.get("supports_pairwise", False)

    def supports_reference(self) -> bool:
        """Check if the skill supports reference answers."""
        return self.skill_config.get("supports_reference", False)

    def to_reviewer_buddy(self) -> ReviewerBuddy:
        """Convert to base ReviewerBuddy for sprite rendering."""
        return ReviewerBuddy.from_species(self.species, self.mood)

    def render_face(self) -> str:
        """Render the buddy's face."""
        base_buddy = self.to_reviewer_buddy()
        return render_face(base_buddy)

    def get_reaction(self, score: float) -> str:
        """Get reaction based on score."""
        base_buddy = self.to_reviewer_buddy()
        return get_reaction(base_buddy, score)

    def render_header(self, score: Optional[float] = None) -> str:
        """Render a header for the review."""
        face = self.render_face()
        if score is not None:
            reaction = self.get_reaction(score)
            return f"{face} {self.name}: {reaction}"
        return f"{face} {self.name} ({self.title})"


# =============================================================================
# JUDGE PANEL - Multiple judges for comprehensive review
# =============================================================================

@dataclass
class JudgePanel:
    """A panel of multiple JudgeBuddies for comprehensive evaluation."""

    judges: List[JudgeBuddy]
    scenario: ResearchScenario

    @classmethod
    def create_for_scenario(
        cls,
        scenario: ResearchScenario,
        num_judges: int = 3,
    ) -> 'JudgePanel':
        """Create a diverse panel for a scenario."""
        scenario_cfg = SCENARIO_CONFIGS[scenario]
        recommended_roles = scenario_cfg.get("recommended_roles", ["senior_reviewer"])

        judges = []

        # Primary judge with recommended role and skill
        judges.append(JudgeBuddy.create(scenario))

        # Add diverse perspectives
        all_roles = list(ResearcherRole)
        for role_name in recommended_roles[1:num_judges]:
            try:
                role = ResearcherRole(role_name)
                judges.append(JudgeBuddy.create(scenario, role=role))
            except ValueError:
                pass

        # Fill remaining with senior reviewer or skeptic
        while len(judges) < num_judges:
            if len(judges) % 2 == 0:
                judges.append(JudgeBuddy.create(scenario, role=ResearcherRole.SKEPTIC))
            else:
                judges.append(JudgeBuddy.create(scenario, role=ResearcherRole.SENIOR_REVIEWER))

        return cls(judges=judges[:num_judges], scenario=scenario)

    @classmethod
    def create_full_paper_panel(cls) -> 'JudgePanel':
        """Create a standard panel for full paper review."""
        return cls(
            judges=[
                JudgeBuddy.create(ResearchScenario.FULL_PAPER, ResearcherRole.SENIOR_REVIEWER),
                JudgeBuddy.create(ResearchScenario.FULL_PAPER, ResearcherRole.NOVELTY_CRITIC),
                JudgeBuddy.create(ResearchScenario.FULL_PAPER, ResearcherRole.METHODS_EXPERT),
            ],
            scenario=ResearchScenario.FULL_PAPER,
        )

    @classmethod
    def create_idea_panel(cls) -> 'JudgePanel':
        """Create a panel for idea evaluation."""
        return cls(
            judges=[
                JudgeBuddy.create(ResearchScenario.IDEA_GENERATION, ResearcherRole.SENIOR_REVIEWER),
                JudgeBuddy.create(ResearchScenario.IDEA_GENERATION, ResearcherRole.NOVELTY_CRITIC),
                JudgeBuddy.create(ResearchScenario.IDEA_GENERATION, ResearcherRole.DOMAIN_EXPERT),
            ],
            scenario=ResearchScenario.IDEA_GENERATION,
        )

    def get_all_dimensions(self) -> List[str]:
        """Get all unique dimensions from all judges."""
        dims = set()
        for judge in self.judges:
            dims.update(judge.dimensions)
        return sorted(dims)

    def get_panel_intro(self) -> str:
        """Get introduction for the panel."""
        lines = [f"=== Judge Panel for {self.scenario.value} ===", ""]
        for i, judge in enumerate(self.judges, 1):
            lines.append(f"{i}. {judge.render_header()}")
            lines.append(f"   Focus: {judge.role_config.get('focus', 'general')}")
            lines.append(f"   Skill: {judge.skill.value}")
            lines.append("")
        return "\n".join(lines)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def get_judge_for_scenario(
    scenario: str | ResearchScenario,
    role: Optional[str | ResearcherRole] = None,
    skill: Optional[str | JudgeSkill] = None,
) -> JudgeBuddy:
    """Factory function to create a JudgeBuddy for any scenario."""
    if isinstance(scenario, str):
        scenario = ResearchScenario(scenario)
    if isinstance(role, str):
        role = ResearcherRole(role)
    if isinstance(skill, str):
        skill = JudgeSkill(skill)

    return JudgeBuddy.create(scenario, role=role, skill=skill)


def get_panel_for_scenario(
    scenario: str | ResearchScenario,
    num_judges: int = 3,
) -> JudgePanel:
    """Factory function to create a JudgePanel for any scenario."""
    if isinstance(scenario, str):
        scenario = ResearchScenario(scenario)

    return JudgePanel.create_for_scenario(scenario, num_judges)


# Convenience exports
__all__ = [
    # Enums
    'ResearchScenario',
    'ResearcherRole',
    'JudgeSkill',
    # Configs
    'SCENARIO_CONFIGS',
    'RESEARCHER_ROLE_CONFIGS',
    'SKILL_CONFIGS',
    # Classes
    'JudgeBuddy',
    'JudgePanel',
    # Factory functions
    'get_judge_for_scenario',
    'get_panel_for_scenario',
]
