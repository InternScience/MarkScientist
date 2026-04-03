"""
MarkScientist Interactive CLI

Interactive command-line interface inspired by cc-mini.
Supports REPL mode with slash commands and auto-review mode.
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.spinner import Spinner
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich.align import Align

from markscientist.config import Config, get_config, set_config
from markscientist.taste import get_taste_profile
from markscientist.buddy import (
    JudgeBuddy,
    JudgePanel,
    ResearchScenario,
    ResearcherRole,
    JudgeSkill,
    SCENARIO_CONFIGS,
    RESEARCHER_ROLE_CONFIGS,
    SKILL_CONFIGS,
    get_judge_for_scenario,
    get_panel_for_scenario,
)

console = Console()
_HISTORY_FILE = Path.home() / ".markscientist_history"

# Double-press timeout for Ctrl+C exit
_DOUBLE_PRESS_TIMEOUT_MS = 0.8

# Iron Man Mark I ASCII Art Logo
_MARK_I_LOGO_SMALL = """\
 ▄██████▄
██ ▄▄▄▄ ██
██ ▀██▀ ██
 ▀██████▀
 ████████
██████████
 ▀██████▀
"""


def _get_cwd_display() -> str:
    """Get current working directory for display."""
    cwd = Path.cwd()
    home = Path.home()
    try:
        return f"~/{cwd.relative_to(home)}"
    except ValueError:
        return str(cwd)


def _print_welcome_banner(config: Config) -> None:
    """Print welcome banner with Iron Man Mark I logo."""
    from markscientist import __version__

    # Left side: Logo with model name below (purple theme for eye comfort)
    logo_lines = _MARK_I_LOGO_SMALL.strip().split('\n')
    logo_text = Text()
    for line in logo_lines:
        logo_text.append(line + "\n", style="#9370db")  # medium purple
    logo_text.append(f"{config.model.model_name}", style="dim italic")

    # Right side: Tips and info (muted purple colors)
    tips_table = Table.grid(padding=(0, 1))
    tips_table.add_column(style="#8b7b8b", justify="left", width=22)  # muted purple-grey
    tips_table.add_column(style="dim")

    tips_table.add_row("Tips", "")
    tips_table.add_row("  /help", "Show available commands")
    tips_table.add_row("  /workflow", "Full research pipeline")
    tips_table.add_row("", "")
    tips_table.add_row("Workflow modes", "")
    tips_table.add_row("  [dim]workflow[/dim]", "Proposer → Solver → Reviewer")
    tips_table.add_row("  [dim]solver[/dim]", "Direct problem solving")

    # Build the panel content
    panel_table = Table.grid(padding=(0, 3))
    panel_table.add_column(justify="left", width=14)
    panel_table.add_column(justify="left")
    panel_table.add_row(logo_text, tips_table)

    # Print the welcome panel (purple theme)
    console.print(Panel(
        panel_table,
        title=f"[#9370db]─── MarkScientist v{__version__} ───[/#9370db]",
        subtitle=f"[dim]{_get_cwd_display()}[/dim]",
        border_style="#6a5a8e",
        padding=(0, 2),
    ))


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands."""

    COMMANDS: list[tuple[str, str]] = [
        ('help', 'Show available commands'),
        ('workflow', 'Run research workflow with step-by-step choices'),
        ('solver', 'Run Solver only (skip Proposer)'),
        ('review', 'Toggle auto-review mode on/off'),
        ('model', 'Show or switch model'),
        ('config', 'Show current configuration'),
        ('clear', 'Clear conversation history'),
        ('exit', 'Exit the REPL'),
        # JudgeBuddy commands
        ('judge', 'Review with JudgeBuddy (scenario-aware evaluation)'),
        ('panel', 'Review with Judge Panel (multi-judge evaluation)'),
        ('compare', 'Compare two artifacts with pairwise evaluation'),
        ('scenarios', 'List available research scenarios'),
        ('roles', 'List available reviewer roles'),
        ('skills', 'List available judge skills'),
    ]

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith('/'):
            return

        query = text[1:].lower()

        for name, desc in self.COMMANDS:
            if not query or name.startswith(query):
                yield Completion(
                    f'/{name}',
                    start_position=-len(text),
                    display=f'/{name}',
                    display_meta=desc,
                )


class SpinnerManager:
    """Manages spinner display during processing."""

    def __init__(self, con: Console):
        self._console = con
        self._live: Optional[Live] = None
        self._spinner: Optional[Spinner] = None

    def start(self, message: str = "Thinking..."):
        self.stop()
        self._spinner = Spinner("dots", text=f"[dim]{message}[/dim]")
        self._live = Live(self._spinner, console=self._console, refresh_per_second=10)
        self._live.start()

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None
            self._spinner = None

    def update(self, message: str):
        if self._spinner:
            self._spinner.text = f"[dim]{message}[/dim]"


class MarkScientistCLI:
    """Interactive CLI for MarkScientist.

    Default mode runs the full workflow: Proposer → Solver → Reviewer
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._spinner = SpinnerManager(console)
        self._auto_review = True  # Auto-review mode enabled by default
        self._use_proposer = True  # Use Proposer by default (full workflow)
        self._last_task = ""
        self._last_output = ""
        self._last_review_raw = ""
        self._last_proposal_raw = ""
        self._last_proposal = None  # Store last proposal for reference

        # Load taste profile for score calibration
        self._taste_profile = get_taste_profile()

    def _get_agent(self, agent_type: str):
        """Get agent instance by type."""
        from markscientist.agents import ProposerAgent, SolverAgent, ReviewerAgent

        workspace = self.config.workspace_root or Path.cwd()
        trace_dir = self.config.trajectory.save_dir
        trace_path = trace_dir / f"{self._session_id}_{agent_type}.jsonl" if self.config.trajectory.auto_save else None

        if agent_type == "proposer":
            return ProposerAgent(
                config=self.config,
                workspace_root=workspace,
                trace_path=trace_path,
            )
        elif agent_type == "solver":
            return SolverAgent(
                config=self.config,
                workspace_root=workspace,
                trace_path=trace_path,
            )
        elif agent_type == "reviewer":
            return ReviewerAgent(
                config=self.config,
                workspace_root=workspace,
                trace_path=trace_path,
            )
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

    def _format_review_result(self, review, buddy=None) -> Table:
        """Format Reviewer result as a compact display."""
        from markscientist.buddy import ReviewerBuddy, render_face, get_reaction

        # Get appropriate reviewer buddy for the task type
        if buddy is None:
            buddy = ReviewerBuddy.for_task_type(review.task_type)
            buddy.eye = buddy.get_mood_eye(review.overall_score)

        # Build score display
        score_color = "green" if review.overall_score >= 7 else "yellow" if review.overall_score >= 5 else "red"

        # Create a compact table for scores
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value")

        # Show reaction based on score
        reaction = get_reaction(buddy, review.overall_score)
        table.add_row("Reaction", f"[{buddy.color} italic]{reaction}[/{buddy.color} italic]")

        # Show task type
        table.add_row("Type", f"[cyan]{review.task_type}[/cyan]")
        table.add_row("Score", f"[{score_color} bold]{review.overall_score:.1f}/10[/{score_color} bold]")

        # Add dimension scores if available
        if review.dimension_scores:
            dims = []
            for dim, score in review.dimension_scores.items():
                dim_color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
                dims.append(f"{dim}: [{dim_color}]{score:.1f}[/{dim_color}]")
            if dims:
                table.add_row("Details", " | ".join(dims[:4]))  # Show max 4 dimensions

        # Add verdict if available
        if review.verdict:
            table.add_row("Verdict", f"[bold]{review.verdict}[/bold]")

        # Format weaknesses if any (show top 2)
        if review.weaknesses:
            weak_items = []
            for w in review.weaknesses[:2]:
                if isinstance(w, dict):
                    weak_items.append(w.get("description", str(w))[:50])
                else:
                    weak_items.append(str(w)[:50])
            if weak_items:
                table.add_row("Issues", "; ".join(weak_items))

        return table

    def _format_proposal_result(self, proposal) -> Table:
        """Format Proposer result as a compact display."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value")

        table.add_row("Type", f"[cyan]{proposal.proposal_type}[/cyan]")
        table.add_row("Difficulty", f"[yellow]{proposal.difficulty}[/yellow]")
        if proposal.hypothesis:
            table.add_row("Hypothesis", proposal.hypothesis[:120])
        if proposal.problem_statement:
            table.add_row("Problem", proposal.problem_statement[:120])
        if proposal.evaluation_criteria:
            table.add_row("Criteria", ", ".join(proposal.evaluation_criteria[:3]))
        return table

    def _format_meta_evaluation_result(self, evaluation) -> Table:
        """Format meta-evaluation result as a compact display."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value")

        table.add_row("Success Prob.", f"{evaluation.success_probability:.2f}")
        table.add_row("Confidence", f"{evaluation.confidence:.2f}")
        if evaluation.meta_summary:
            table.add_row("Summary", evaluation.meta_summary[:120])
        if evaluation.system_insights:
            table.add_row("Insights", json.dumps(evaluation.system_insights, ensure_ascii=False)[:160])
        return table

    def _get_buddy_for_task(self, task_type: str = "auto"):
        """Get appropriate JudgeBuddy for the task type."""
        from markscientist.buddy import ReviewerBuddy
        return ReviewerBuddy.for_task_type(task_type)

    def _display_review_with_buddy(self, review, buddy=None, title_prefix: str = "Review", 
                                   task_hint: str = None, collect_feedback: bool = True) -> dict:
        """Display review with JudgeBuddy personality and collect user feedback.
        
        Args:
            review: The ReviewResult object
            buddy: Pre-determined JudgeBuddy (if None, will be inferred from task_type)
            title_prefix: Prefix for the panel title
            task_hint: Optional hint to help infer scenario
            collect_feedback: Whether to collect user feedback
            
        Returns:
            dict with feedback info (if collected)
        """
        from markscientist.buddy import ReviewerBuddy, render_face, get_reaction

        # Get buddy (use provided or infer from task type)
        if buddy is None:
            buddy = ReviewerBuddy.for_task_type(review.task_type)
        
        buddy.eye = buddy.get_mood_eye(review.overall_score)
        buddy_face = render_face(buddy)
        reaction = get_reaction(buddy, review.overall_score)

        # Show buddy introduction with personality
        console.print(f"[{buddy.color}]{buddy_face}[/{buddy.color}] "
                     f"[{buddy.color} bold]{buddy.name}[/{buddy.color} bold] "
                     f"[dim]appears![/dim] "
                     f"[{buddy.color} italic]\"{buddy.catchphrase}\"[/{buddy.color} italic]")
        console.print()

        # Show review panel
        review_table = self._format_review_result(review, buddy)
        console.print(Panel(
            review_table,
            title=f"[bold {buddy.color}]{buddy_face} {title_prefix}: {reaction}[/bold {buddy.color}]",
            border_style=buddy.color
        ))

        feedback = None
        if collect_feedback:
            feedback = self._collect_review_feedback(review, buddy)
            
        return {"buddy": buddy, "review": review, "feedback": feedback}

    def _collect_review_feedback(self, review, buddy) -> dict:
        """Collect user feedback on the review score using arrow key selection."""
        console.print()
        console.print(f"[dim]Your feedback on {buddy.name}'s review (↑↓ to select, Enter to confirm):[/dim]")

        options = [
            ("agree", "👍 Agree", "green"),
            ("disagree", "👎 Disagree", "red"),
            ("too_high", "⬆ Score too high", "yellow"),
            ("too_low", "⬇ Score too low", "yellow"),
            ("skip", "Skip", "dim"),
        ]

        feedback = {
            "score": review.overall_score,
            "task_type": review.task_type,
            "buddy_name": buddy.name,
            "user_reaction": None,
            "adjustment": 0,
        }

        selected = self._arrow_select(options, default=4)

        if selected == 0:
            feedback["user_reaction"] = "agree"
            console.print(f"[green]✓ Thanks! {buddy.name} appreciates your trust.[/green]")
        elif selected == 1:
            feedback["user_reaction"] = "disagree"
            console.print(f"[yellow]✓ Noted. We'll calibrate {buddy.name}'s standards.[/yellow]")
        elif selected == 2:
            feedback["user_reaction"] = "too_high"
            feedback["adjustment"] = -1
            console.print(f"[yellow]✓ Got it. Score should be lower. Calibrating...[/yellow]")
        elif selected == 3:
            feedback["user_reaction"] = "too_low"
            feedback["adjustment"] = 1
            console.print(f"[yellow]✓ Got it. Score should be higher. Calibrating...[/yellow]")
        else:
            console.print(f"[dim]Skipped feedback.[/dim]")

        # Store feedback for taste learning
        if feedback["user_reaction"]:
            self._store_taste_feedback(feedback)

        return feedback

    def _arrow_select(self, options: list[tuple[str, str, str]], default: int = 0) -> int:
        """Arrow key selection menu. Returns 0-based index.

        Args:
            options: List of (key, label, color) tuples
            default: Default selection index (0-based)
        """
        import sys
        from prompt_toolkit.input import create_input
        from prompt_toolkit.keys import Keys

        current = default
        inp = create_input()

        def render():
            # Move cursor up to overwrite previous render
            if hasattr(render, 'rendered'):
                sys.stdout.write(f"\033[{len(options)}A")
            for i, (_, label, color) in enumerate(options):
                if i == current:
                    sys.stdout.write(f"\033[2K  \033[1m→ {label}\033[0m\n")
                else:
                    sys.stdout.write(f"\033[2K    {label}\n")
            sys.stdout.flush()
            render.rendered = True

        render()

        try:
            with inp.raw_mode():
                while True:
                    for key in inp.read_keys():
                        if key.key == Keys.Up or key.data == 'k':
                            current = (current - 1) % len(options)
                            render()
                        elif key.key == Keys.Down or key.data == 'j':
                            current = (current + 1) % len(options)
                            render()
                        elif key.key == Keys.Enter or key.data in ('\r', '\n'):
                            return current
                        elif key.key == Keys.Escape or key.data == 'q':
                            return len(options) - 1  # Return last (skip)
                        elif key.key == Keys.ControlC:
                            raise KeyboardInterrupt
        except (KeyboardInterrupt, EOFError):
            return len(options) - 1  # Default to skip on interrupt

    def _store_taste_feedback(self, feedback: dict) -> None:
        """Store feedback to user's taste profile."""
        import json
        from pathlib import Path
        from datetime import datetime
        
        taste_dir = Path.home() / ".markscientist" / "taste"
        taste_dir.mkdir(parents=True, exist_ok=True)
        taste_file = taste_dir / "feedback_history.jsonl"
        
        record = {
            "timestamp": datetime.now().isoformat(),
            **feedback
        }
        
        with open(taste_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run_solver_with_review(self, user_input: str) -> None:
        """Run Solver with automatic Reviewer review using JudgeBuddy."""
        try:
            payload = self.run_solver_with_review_payload(user_input, show_spinner=True)
            solver_result = payload["solver_result"]
            review = payload["review"]
            judge_buddy = payload.get("judge_buddy")

            console.print(Panel(
                solver_result.output,
                title="[bold blue]Solver Output[/bold blue]",
                border_style="blue"
            ))

            if review is not None:
                console.print()

                # Use JudgeBuddy if available (new system)
                if judge_buddy is not None:
                    buddy_face = judge_buddy.render_face()
                    reaction = judge_buddy.get_reaction(review.overall_score)

                    console.print(f"[{judge_buddy.color}]{buddy_face}[/{judge_buddy.color}] "
                                 f"[{judge_buddy.color} bold]{judge_buddy.name}[/{judge_buddy.color} bold] "
                                 f"[dim]({judge_buddy.role.value})[/dim] "
                                 f"[{judge_buddy.color} italic]\"{judge_buddy.get_catchphrase()}\"[/{judge_buddy.color} italic]")
                    console.print()

                    review_table = self._format_review_result(review)
                    console.print(Panel(
                        review_table,
                        title=f"[bold {judge_buddy.color}]{buddy_face} {judge_buddy.name}: {reaction}[/bold {judge_buddy.color}]",
                        border_style=judge_buddy.color
                    ))

                    # Show skill info
                    console.print(f"[dim]Scenario: {judge_buddy.scenario.value} | "
                                 f"Skill: {judge_buddy.skill.value} | "
                                 f"Strictness: {judge_buddy.strictness}[/dim]")
                else:
                    # Fallback to basic ReviewerBuddy
                    from markscientist.buddy import ReviewerBuddy, render_face

                    review_buddy = ReviewerBuddy.for_task_type(review.task_type)
                    review_buddy.eye = review_buddy.get_mood_eye(review.overall_score)
                    buddy_face = render_face(review_buddy)

                    console.print(f"[{review_buddy.color}]{buddy_face}[/{review_buddy.color}] "
                                 f"[{review_buddy.color} bold]{review_buddy.name}[/{review_buddy.color} bold] "
                                 f"[dim]appears![/dim] "
                                 f"[{review_buddy.color} italic]\"{review_buddy.catchphrase}\"[/{review_buddy.color} italic]")
                    console.print()

                    review_table = self._format_review_result(review, review_buddy)
                    console.print(Panel(
                        review_table,
                        title=f"[bold {review_buddy.color}]{buddy_face} {review_buddy.title}[/bold {review_buddy.color}]",
                        border_style=review_buddy.color
                    ))

                if review.overall_score < 6.0:
                    console.print(
                        f"[dim]Tip: Score is below 6.0. Use [bold]/workflow[/bold] for auto-improvement loop.[/dim]"
                    )

        except Exception as e:
            self._spinner.stop()
            console.print(f"[red]Error:[/red] {str(e)}")

    def run_solver_with_review_payload(self, user_input: str, show_spinner: bool = True) -> dict:
        if show_spinner:
            self._spinner.start("Solver executing...")

        solver = self._get_agent("solver")
        solver_result = solver.run(user_input)

        if show_spinner:
            self._spinner.stop()

        self._last_task = user_input
        self._last_output = solver_result.output
        self._last_review_raw = ""

        if not solver_result.success:
            raise RuntimeError(f"{solver_result.termination_reason}: {solver_result.output}")

        review = None
        judge_buddy = None

        if self._auto_review:
            # Determine scenario from task content (simple heuristics)
            scenario = self._infer_scenario_from_task(user_input)

            # Create JudgeBuddy for this scenario
            judge_buddy = get_judge_for_scenario(scenario)

            if show_spinner:
                console.print()
                buddy_face = judge_buddy.render_face()
                self._spinner.start(f"{buddy_face} {judge_buddy.name} is reviewing...")

            reviewer = self._get_agent("reviewer")

            # Use JudgeBuddy-enhanced review
            review = reviewer.review_with_buddy(
                artifact=solver_result.output,
                scenario=scenario,
                role=judge_buddy.role,
                skill=judge_buddy.skill,
            )

            if show_spinner:
                self._spinner.stop()
            self._last_review_raw = review.raw_output

        return {
            "solver_result": solver_result,
            "review": review,
            "judge_buddy": judge_buddy,
        }

    def _infer_scenario_from_task(self, task: str) -> ResearchScenario:
        """Infer the most appropriate research scenario from task content."""
        task_lower = task.lower()

        # === Priority 1: Rebuttal (very specific, check early) ===
        if any(kw in task_lower for kw in ["rebuttal", "回复审稿", "reviewer comment", "reviewer 2", "reviewer 1"]):
            return ResearchScenario.REBUTTAL

        # === Priority 2: Factual queries about history/attribution (check BEFORE idea generation) ===
        # "Who proposed X" / "谁提出了X" are factual queries, not idea generation
        factual_question_patterns = [
            "谁提出", "who proposed", "who invented", "who created", "who discovered",
            "谁发明", "谁创造", "谁发现",
        ]
        if any(pattern in task_lower for pattern in factual_question_patterns) and len(task) < 200:
            return ResearchScenario.LITERATURE_REVIEW

        # === Priority 3: Novelty check (check BEFORE factual to catch "original", "related work") ===
        if any(kw in task_lower for kw in ["novel", "originality", "original", "prior work", "related work", "新颖", "原创", "查新"]):
            # But NOT if it's asking to "write related work section"
            if not any(kw in task_lower for kw in ["write", "draft", "写"]):
                return ResearchScenario.NOVELTY_CHECK

        # === Priority 4: Idea generation (use specific phrases to avoid matching factual "proposed") ===
        idea_patterns = [
            "idea", "brainstorm", "research direction", "new method", "创意", "想法", "研究方向", "找方向",
            "propose a", "propose an", "propose new", "提出一个", "提出新", "提出方案",
        ]
        if any(kw in task_lower for kw in idea_patterns):
            return ResearchScenario.IDEA_GENERATION

        # === Priority 5: Check for simple factual queries (shortest, most specific) ===
        factual_patterns = [
            "谁", "什么是", "是什么", "哪个", "哪些", "多少", "何时", "为什么", "怎么",
            "who ", "what is", "what are", "which ", "when ", "where ", "how many",
            "define ", "explain ", "describe ", "tell me about",
        ]
        if any(pattern in task_lower for pattern in factual_patterns) and len(task) < 200:
            return ResearchScenario.LITERATURE_REVIEW

        # === Priority 5: Literature review / Survey (check BEFORE figure/table to avoid "图神经网络" matching) ===
        if any(kw in task_lower for kw in ["survey", "文献", "综述", "review paper", "literature"]):
            return ResearchScenario.LITERATURE_REVIEW

        # === Priority 6: Figure/Table (specific keywords, but be careful with Chinese "图") ===
        figure_keywords = ["figure", "plot", "table", "visualization", "visualize", "画图", "表格", "曲线"]
        # For Chinese "图", only match if it's standalone or followed by spaces/punctuation (not part of compound words)
        has_figure_keyword = any(kw in task_lower for kw in figure_keywords)
        has_standalone_tu = "图" in task and not any(compound in task for compound in ["图神经", "图网络", "图学习", "图卷积", "知识图谱"])
        if has_figure_keyword or has_standalone_tu:
            return ResearchScenario.FIGURE_TABLE

        # === Priority 7: Code review (check after idea generation) ===
        if any(kw in task_lower for kw in ["code", "implement", "function", "class", "bug", "debug", "代码", "实现", "函数"]):
            return ResearchScenario.CODE_REVIEW

        # === Priority 8: Claim validation (check before result analysis) ===
        if any(kw in task_lower for kw in ["claim", "evidence", "support", "validate", "验证", "支持"]):
            return ResearchScenario.CLAIM_VALIDATION

        # === Priority 9: Result analysis ===
        if any(kw in task_lower for kw in ["result", "metric", "performance", "benchmark", "结果", "性能", "指标"]):
            # But NOT if combined with "experiment design"
            if not any(kw in task_lower for kw in ["design", "plan", "设计"]):
                return ResearchScenario.RESULT_ANALYSIS

        # === Priority 10: Experiment design ===
        if any(kw in task_lower for kw in ["experiment", "design", "methodology", "ablation", "实验", "消融"]):
            return ResearchScenario.EXPERIMENT_DESIGN

        # === Priority 11: Paper writing (section draft) ===
        if any(kw in task_lower for kw in ["paper", "draft", "write", "section", "abstract", "introduction", "论文", "写"]):
            return ResearchScenario.SECTION_DRAFT

        # === Priority 12: Check for response/reply (could be rebuttal) ===
        if any(kw in task_lower for kw in ["respond", "response", "reply"]):
            return ResearchScenario.REBUTTAL

        # === Default based on content length ===
        if len(task) > 1000:
            return ResearchScenario.FULL_PAPER
        elif len(task) < 100:
            # Short queries are likely factual questions
            return ResearchScenario.LITERATURE_REVIEW
        else:
            return ResearchScenario.IDEA_GENERATION

    def run_proposer(self, topic: str, show_spinner: bool = True):
        if show_spinner:
            self._spinner.start("Proposer generating...")
        proposer = self._get_agent("proposer")
        proposal = proposer.propose(topic=topic)
        if show_spinner:
            self._spinner.stop()
        self._last_proposal_raw = proposal.raw_output
        return proposal

    def run_reviewer(self, artifact: str, show_spinner: bool = True):
        if show_spinner:
            self._spinner.start("Reviewer analyzing...")
        reviewer = self._get_agent("reviewer")
        review = reviewer.review(artifact=artifact, artifact_type="auto")
        if show_spinner:
            self._spinner.stop()
        return review

    def run_meta_evaluation(self, task: str, show_spinner: bool = True):
        if show_spinner:
            self._spinner.start("Running meta-evaluation...")
        reviewer = self._get_agent("reviewer")
        evaluation = reviewer.evaluate(
            original_task=self._last_task or task,
            solver_output=self._last_output,
            proposal_info=self._last_proposal_raw or "No prior proposal available.",
            final_result=self._last_output,
        )
        if show_spinner:
            self._spinner.stop()
        return evaluation

    def run_query(self, user_input: str, agent_type: Optional[str] = None,
                  show_spinner: bool = True) -> str:
        """Run a query with the specified agent (without auto-review)."""
        agent_type = agent_type or self._current_agent

        if show_spinner:
            self._spinner.start(f"Running {agent_type}...")

        try:
            if agent_type == "proposer":
                proposal = self.run_proposer(user_input, show_spinner=show_spinner)
                return json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2)
            if agent_type == "reviewer":
                review = self.run_reviewer(user_input, show_spinner=show_spinner)
                return json.dumps(review.to_dict(), ensure_ascii=False, indent=2)

            agent = self._get_agent(agent_type)
            result = agent.run(user_input)
            if show_spinner:
                self._spinner.stop()
            if result.success:
                return result.output
            return f"[Error] {result.termination_reason}: {result.output}"

        except Exception as e:
            if show_spinner:
                self._spinner.stop()
            return f"[Error] {str(e)}"

    def _is_simple_query(self, task: str) -> bool:
        """Detect if this is a simple factual query that doesn't need full workflow."""
        task_lower = task.lower().strip()

        # Simple factual question patterns (Chinese)
        cn_factual_patterns = [
            "谁", "什么是", "是什么", "哪个", "哪些", "多少", "何时", "为什么",
            "怎么", "如何", "哪年", "哪里", "什么时候", "提出", "发明", "创建",
            "定义", "解释", "介绍", "简述", "概述",
        ]

        # Simple factual question patterns (English)
        en_factual_patterns = [
            "who ", "what is", "what are", "which ", "when ", "where ", "how many",
            "how much", "define ", "explain ", "describe ", "tell me about",
            "what does", "who invented", "who created", "who proposed", "who developed",
        ]

        # Check if it's a short question (likely factual)
        is_short = len(task) < 100

        # Check for question patterns
        has_cn_pattern = any(p in task_lower for p in cn_factual_patterns)
        has_en_pattern = any(p in task_lower for p in en_factual_patterns)

        # Simple query: short + has question pattern
        if is_short and (has_cn_pattern or has_en_pattern):
            return True

        # Very short queries are usually simple
        if len(task) < 50 and ("?" in task or "？" in task):
            return True

        return False

    def run_simple_query(self, task: str) -> None:
        """Run a simple query with Solver + auto Review (with JudgeBuddy)."""
        self._spinner.start("Thinking...")

        try:
            # Step 1: Solver
            solver = self._get_agent("solver")
            result = solver.run(task)
            self._spinner.stop()

            if not result.success:
                console.print(f"[red]Error:[/red] {result.termination_reason}")
                return

            # Display answer
            console.print(Panel(
                result.output,
                title="[bold blue]Answer[/bold blue]",
                border_style="blue"
            ))

            self._last_task = task
            self._last_output = result.output

            # Step 2: Auto Review with JudgeBuddy
            if self._auto_review:
                console.print()
                
                # Determine which buddy will review (before starting)
                from markscientist.buddy import ReviewerBuddy, render_face
                buddy = ReviewerBuddy.for_task_type("factual_qa")  # Default for simple queries
                buddy_face = render_face(buddy)
                
                self._spinner.start(f"{buddy_face} {buddy.name} is coming to review...")
                reviewer = self._get_agent("reviewer")
                review = reviewer.review(artifact=result.output, artifact_type="auto")
                self._spinner.stop()
                
                # Update buddy based on actual task type from review
                buddy = self._get_buddy_for_task(review.task_type)

                self._display_review_with_buddy(review, buddy=buddy, title_prefix="Review")
                self._last_review_raw = review.raw_output

        except Exception as e:
            self._spinner.stop()
            console.print(f"[red]Error:[/red] {str(e)}")

    def run_workflow(self, task: str, enable_proposer: bool = True, interactive: bool = True) -> None:
        """Run the research workflow with optional interactive choices.

        Args:
            task: The research task/topic
            enable_proposer: Whether to use Proposer first
            interactive: Whether to show interactive choice points (default: True)
        """
        console.print()
        console.print(Panel(
            f"[bold]Task:[/bold] {task[:200]}{'...' if len(task) > 200 else ''}",
            title="[bold cyan]Research Workflow[/bold cyan]",
            border_style="cyan"
        ))

        # ===== Interactive: Choose workflow mode =====
        if interactive:
            choice = self._prompt_choice(
                "How would you like to proceed?",
                [
                    ("proposer", "Generate research proposal first (Proposer → Solver → Review)"),
                    ("solver", "Solve directly (Solver → Review)"),
                    ("refine", "Refine/clarify the task first"),
                    ("cancel", "Cancel"),
                ],
                default=1 if enable_proposer else 2
            )

            if choice == 0 or choice == 4:
                console.print("[dim]Workflow cancelled.[/dim]")
                return
            if choice == 3:
                refinement = self._prompt_text("Enter clarification or additional context:")
                if not refinement:
                    return
                task = f"{task}\n\nAdditional context: {refinement}"
                return self.run_workflow(task, enable_proposer, interactive)

            enable_proposer = (choice == 1)

        step_num = 1
        reviews = []
        proposal = None
        solver_output = ""

        try:
            # ===== Proposer Phase =====
            if enable_proposer:
                while True:
                    self._spinner.start(f"Step {step_num}: Proposer generating research plan...")
                    proposer = self._get_agent("proposer")
                    proposal = proposer.propose(topic=task)
                    self._spinner.stop()

                    proposal_table = self._format_proposal_result(proposal)
                    console.print(Panel(
                        proposal_table,
                        title=f"[bold green]Step {step_num}: Research Proposal[/bold green]",
                        border_style="green"
                    ))
                    self._last_proposal = proposal
                    self._last_proposal_raw = proposal.raw_output

                    if not interactive:
                        step_num += 1
                        break

                    # Interactive choice after proposal
                    choice = self._prompt_choice(
                        "What would you like to do with this proposal?",
                        [
                            ("accept", "Accept and proceed to execution"),
                            ("regenerate", "Regenerate proposal"),
                            ("modify", "Modify task and regenerate"),
                            ("skip", "Skip proposal, solve directly"),
                            ("cancel", "Cancel"),
                        ],
                        default=1
                    )

                    if choice == 0 or choice == 5:
                        console.print("[dim]Workflow cancelled.[/dim]")
                        return
                    elif choice == 1:
                        step_num += 1
                        break
                    elif choice == 2:
                        console.print("[yellow]Regenerating proposal...[/yellow]")
                        continue
                    elif choice == 3:
                        modification = self._prompt_text("Enter modification:")
                        if modification:
                            task = f"{task}\n\nModification: {modification}"
                        continue
                    elif choice == 4:
                        enable_proposer = False
                        proposal = None
                        break

                solver_task = self._build_solver_task_from_proposal(proposal) if proposal else task
            else:
                solver_task = task

            # ===== Solver Phase =====
            max_attempts = 3
            attempt = 0

            while attempt < max_attempts:
                attempt += 1
                console.print()
                self._spinner.start(f"Step {step_num}: Solver executing...")
                solver = self._get_agent("solver")
                solver_result = solver.run(solver_task)
                self._spinner.stop()

                if not solver_result.success:
                    console.print(f"[red]Solver Error:[/red] {solver_result.termination_reason}")
                    if interactive:
                        choice = self._prompt_choice(
                            "Solver failed. What to do?",
                            [("retry", "Retry"), ("modify", "Modify and retry"), ("cancel", "Cancel")],
                            default=1
                        )
                        if choice == 0 or choice == 3:
                            return
                        elif choice == 2:
                            mod = self._prompt_text("Enter modification:")
                            if mod:
                                solver_task = f"{solver_task}\n\nNote: {mod}"
                        continue
                    return

                solver_output = solver_result.output
                self._last_output = solver_output
                self._last_task = task

                console.print(Panel(
                    solver_output[:3000] + ("..." if len(solver_output) > 3000 else ""),
                    title=f"[bold blue]Step {step_num}: Solution[/bold blue]",
                    border_style="blue"
                ))
                step_num += 1

                # ===== Review Phase =====
                if self._auto_review:
                    console.print()
                    scenario = self._infer_scenario_from_task(task)
                    judge_buddy = get_judge_for_scenario(scenario)
                    buddy_face = judge_buddy.render_face()

                    self._spinner.start(f"Step {step_num}: {buddy_face} {judge_buddy.name} reviewing...")
                    reviewer = self._get_agent("reviewer")
                    solver_review = reviewer.review_with_buddy(
                        artifact=solver_output,
                        scenario=scenario,
                        role=judge_buddy.role,
                        skill=judge_buddy.skill,
                    )
                    self._spinner.stop()

                    self._display_review_with_buddy(solver_review, buddy=judge_buddy,
                                                   title_prefix=f"Step {step_num}: Review",
                                                   collect_feedback=not interactive)
                    reviews.append(("Solution", solver_review))
                    self._last_review_raw = solver_review.raw_output
                    step_num += 1

                    # Interactive choice based on score
                    if interactive and solver_review.overall_score < 6:
                        console.print(f"\n[yellow]⚠ Score: {solver_review.overall_score:.1f}/10 - Below threshold[/yellow]")
                        choice = self._prompt_choice(
                            "What would you like to do?",
                            [
                                ("improve", "Request improvement based on feedback"),
                                ("accept", "Accept current output"),
                                ("retry", "Retry with modified instructions"),
                                ("cancel", "Cancel"),
                            ],
                            default=1
                        )

                        if choice == 0 or choice == 4:
                            return
                        elif choice == 1:
                            # Build improvement task from weaknesses
                            feedback = self._extract_feedback(solver_review)
                            solver_task = f"""Improve based on feedback:

## Original Output
{solver_output[:2000]}

## Feedback
{feedback}

Provide improved response addressing the feedback."""
                            console.print("[green]Requesting improvement...[/green]")
                            continue
                        elif choice == 2:
                            break
                        elif choice == 3:
                            mod = self._prompt_text("Enter modification:")
                            if mod:
                                solver_task = f"{solver_task}\n\nImportant: {mod}"
                            continue
                    elif interactive:
                        choice = self._prompt_choice(
                            f"Score: {solver_review.overall_score:.1f}/10. What next?",
                            [
                                ("done", "Done - finish workflow"),
                                ("improve", "Request further improvement"),
                                ("export", "Export result to file"),
                            ],
                            default=1
                        )
                        if choice == 2:
                            feedback = self._prompt_text("Enter improvement request:")
                            if feedback:
                                solver_task = f"""Improve:

## Current Output
{solver_output[:2000]}

## Request
{feedback}"""
                                continue
                        elif choice == 3:
                            self._export_result(task, solver_output, reviews)

                break  # Exit solver loop

            # ===== Final Summary =====
            if reviews:
                self._display_workflow_summary(reviews, enable_proposer, step_num - 1)

        except Exception as e:
            self._spinner.stop()
            console.print(f"[red]Error:[/red] {str(e)}")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")

    def _extract_feedback(self, review) -> str:
        """Extract feedback from review weaknesses."""
        if review.weaknesses:
            items = []
            for w in review.weaknesses[:3]:
                if isinstance(w, dict):
                    items.append(f"- {w.get('issue', w.get('description', str(w)))}")
                else:
                    items.append(f"- {w}")
            return "\n".join(items)
        return review.summary or "Please improve the quality."

    def _prompt_choice(self, title: str, options: list[tuple[str, str]], default: int = 1) -> int:
        """Prompt user for a choice. Returns 1-based index of selected option.

        Args:
            title: Title to display
            options: List of (key, description) tuples
            default: Default option (1-based)

        Returns:
            Selected option number (1-based)
        """
        console.print()
        console.print(f"[bold cyan]{title}[/bold cyan]")
        for i, (key, desc) in enumerate(options, 1):
            marker = "[green]→[/green]" if i == default else " "
            console.print(f"  {marker} [bold]{i}[/bold]. {desc}")

        while True:
            try:
                choice = console.input(f"\n[dim]Enter choice (1-{len(options)}) [[bold]{default}[/bold]]: [/dim]").strip()
                if not choice:
                    return default
                num = int(choice)
                if 1 <= num <= len(options):
                    return num
                console.print(f"[yellow]Please enter a number between 1 and {len(options)}[/yellow]")
            except ValueError:
                console.print(f"[yellow]Please enter a number between 1 and {len(options)}[/yellow]")
            except KeyboardInterrupt:
                console.print("\n[dim]Cancelled[/dim]")
                return 0  # 0 means cancelled

    def _prompt_text(self, prompt: str, default: str = "") -> str:
        """Prompt user for text input."""
        try:
            text = console.input(f"[dim]{prompt}[/dim] ").strip()
            return text if text else default
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled[/dim]")
            return ""

    def _display_workflow_summary(self, reviews: list, enable_proposer: bool, total_steps: int) -> None:
        """Display final workflow summary."""
        summary_table = Table(show_header=False, box=None)
        summary_table.add_column("Label", style="dim")
        summary_table.add_column("Value")

        avg_score = sum(r.overall_score for _, r in reviews) / len(reviews) if reviews else 0
        score_color = "green" if avg_score >= 7 else "yellow" if avg_score >= 5 else "red"

        summary_table.add_row("Workflow", "Proposer → Solver" if enable_proposer else "Solver only")
        summary_table.add_row("Steps Completed", str(total_steps))

        for name, review in reviews:
            r_color = "green" if review.overall_score >= 7 else "yellow" if review.overall_score >= 5 else "red"
            summary_table.add_row(f"{name} Score", f"[{r_color}]{review.overall_score:.1f}/10[/{r_color}]")

        summary_table.add_row("", "")
        summary_table.add_row("Final Score", f"[{score_color} bold]{avg_score:.1f}/10[/{score_color} bold]")

        if avg_score >= 7:
            verdict = "[green]✓ Good quality output[/green]"
        elif avg_score >= 5:
            verdict = "[yellow]○ Acceptable, could be improved[/yellow]"
        else:
            verdict = "[red]✗ Needs improvement[/red]"
        summary_table.add_row("Verdict", verdict)

        console.print(Panel(
            summary_table,
            title="[bold cyan]Workflow Summary[/bold cyan]",
            border_style="cyan"
        ))

    def _export_result(self, task: str, output: str, reviews: list) -> None:
        """Export workflow result to a file."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"markscientist_result_{timestamp}.md"

        content = f"""# MarkScientist Workflow Result
Generated: {datetime.now().isoformat()}

## Task
{task}

## Output
{output}

## Reviews
"""
        for name, review in reviews:
            content += f"""
### {name} Review
- Score: {review.overall_score}/10
- Verdict: {review.verdict}
- Summary: {review.summary}
"""

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            console.print(f"[green]Result exported to:[/green] {filename}")
        except Exception as e:
            console.print(f"[red]Export failed:[/red] {str(e)}")

    def _build_solver_task_from_proposal(self, proposal) -> str:
        """Build solver task from proposal."""
        parts = []

        if proposal.problem_statement:
            parts.append(f"## Problem Statement\n{proposal.problem_statement}")

        if proposal.hypothesis:
            parts.append(f"## Hypothesis\n{proposal.hypothesis}")

        if proposal.constraints:
            constraints_str = "\n".join(f"- {c}" for c in proposal.constraints)
            parts.append(f"## Constraints\n{constraints_str}")

        if proposal.evaluation_criteria:
            criteria_str = "\n".join(f"- {c}" for c in proposal.evaluation_criteria)
            parts.append(f"## Evaluation Criteria\n{criteria_str}")

        if proposal.hints:
            hints_str = "\n".join(f"- {h}" for h in proposal.hints)
            parts.append(f"## Hints\n{hints_str}")

        if proposal.expected_approach:
            parts.append(f"## Expected Approach\n{proposal.expected_approach}")

        return "\n\n".join(parts) if parts else proposal.problem_statement or proposal.raw_output

    def handle_command(self, cmd_name: str, cmd_args: str) -> Optional[str]:
        """Handle slash commands. Returns None to continue, string to print."""
        if cmd_name == "help":
            return self._show_help()

        elif cmd_name == "workflow":
            # Full workflow: Proposer → Solver → Reviewer
            self._use_proposer = True
            if cmd_args:
                self.run_workflow(cmd_args, enable_proposer=True)
                return None
            return "[green]Workflow mode (Proposer→Solver→Reviewer).[/green] Enter your research topic."

        elif cmd_name == "solver":
            # Solver-only mode (skip Proposer)
            self._use_proposer = False
            if cmd_args:
                self.run_workflow(cmd_args, enable_proposer=False)
                return None
            return "[green]Solver mode (skip Proposer).[/green] Enter your task directly."

        elif cmd_name == "review":
            self._auto_review = not self._auto_review
            status = "[green]enabled[/green]" if self._auto_review else "[yellow]disabled[/yellow]"
            return f"Auto-review mode: {status}"

        elif cmd_name == "model":
            if cmd_args:
                self.config.model.model_name = cmd_args
                return f"[green]Model switched to:[/green] {cmd_args}"
            return f"[bold]Current model:[/bold] {self.config.model.model_name}"

        elif cmd_name == "config":
            return self._show_config()

        elif cmd_name == "clear":
            self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._last_output = ""
            self._last_proposal_raw = ""
            self._last_review_raw = ""
            self._last_proposal = None
            return "[green]Session cleared.[/green] New session started."

        elif cmd_name in ("exit", "quit"):
            return None  # Signal to exit

        # ===== JudgeBuddy Commands =====
        elif cmd_name == "judge":
            return self._handle_judge_command(cmd_args)

        elif cmd_name == "panel":
            return self._handle_panel_command(cmd_args)

        elif cmd_name == "compare":
            return self._handle_compare_command(cmd_args)

        elif cmd_name == "scenarios":
            return self._show_scenarios()

        elif cmd_name == "roles":
            return self._show_roles()

        elif cmd_name == "skills":
            return self._show_skills()

        else:
            return f"[red]Unknown command:[/red] /{cmd_name}. Type /help for available commands."

    def _show_help(self) -> str:
        auto_status = "[green]ON[/green]" if self._auto_review else "[yellow]OFF[/yellow]"
        mode_status = "[green]Full Workflow[/green]" if self._use_proposer else "[yellow]Solver Only[/yellow]"
        return f"""
[bold cyan]MarkScientist - Automated Research Workflow[/bold cyan]
{'─' * 55}
[bold]Smart Routing:[/bold]
  • Simple questions (e.g. "谁提出了ResNet") → Fast answer
  • Complex tasks → Full workflow (Proposer → Solver → Reviewer)

[bold cyan]Workflow Commands[/bold cyan]
{'─' * 55}
  [bold]/interactive[/bold]  [green]★[/green] Step-by-step with user choices
  [bold]/workflow[/bold]     Auto run full workflow
  [bold]/solver[/bold]       Solver only (skip Proposer)

[bold cyan]General Commands[/bold cyan]
{'─' * 55}
  [bold]/help[/bold]         Show this help message
  [bold]/review[/bold]       Toggle auto-review (currently {auto_status})
  [bold]/model[/bold]        Show or switch model
  [bold]/config[/bold]       Show current configuration
  [bold]/clear[/bold]        Clear session
  [bold]/exit[/bold]         Exit

[bold cyan]JudgeBuddy Commands[/bold cyan]
{'─' * 55}
  [bold]/judge[/bold]        Review with JudgeBuddy (scenario-aware)
  [bold]/panel[/bold]        Multi-judge evaluation panel
  [bold]/compare[/bold]      Pairwise artifact comparison
  [bold]/scenarios[/bold]    List research scenarios

[bold cyan]Current Mode: {mode_status}[/bold cyan]
{'─' * 55}
  [bold]Proposer[/bold]  → Generates research questions & hypotheses
  [bold]Solver[/bold]    → Executes the research task
  [bold]Reviewer[/bold]  → Evaluates output quality (JudgeBuddy)

[dim]Tips: /interactive for guided workflow | Ctrl+C twice to exit[/dim]
"""

    def _show_config(self) -> str:
        auto_status = "[green]ON[/green]" if self._auto_review else "[yellow]OFF[/yellow]"
        return f"""
[bold cyan]Current Configuration[/bold cyan]
{'─' * 40}
[bold]Model:[/bold] {self.config.model.model_name}
[bold]Agent:[/bold] {self._current_agent}
[bold]Auto-review:[/bold] {auto_status}
[bold]Session:[/bold] {self._session_id}
[bold]Workspace:[/bold] {self.config.workspace_root or Path.cwd()}
[bold]Save trajectories:[/bold] {self.config.trajectory.auto_save}
"""

    # =========================================================================
    # JudgeBuddy Command Handlers
    # =========================================================================

    def _handle_judge_command(self, cmd_args: str) -> Optional[str]:
        """Handle /judge command with JudgeBuddy evaluation."""
        if not cmd_args:
            return """[yellow]Usage:[/yellow] /judge <scenario> [role] [skill] -- <content>

[bold]Examples:[/bold]
  /judge idea_generation -- My new research idea about...
  /judge full_paper novelty_critic -- <paper content>
  /judge code_review code_expert geval -- def foo(): ...

[dim]Use /scenarios, /roles, /skills to see available options[/dim]"""

        # Parse: scenario [role] [skill] -- content
        if " -- " in cmd_args:
            config_part, content = cmd_args.split(" -- ", 1)
        else:
            return "[red]Error:[/red] Use ' -- ' to separate options from content.\nExample: /judge idea_generation -- My idea..."

        parts = config_part.strip().split()
        if not parts:
            return "[red]Error:[/red] Please specify a scenario."

        scenario_str = parts[0]
        role_str = parts[1] if len(parts) > 1 else None
        skill_str = parts[2] if len(parts) > 2 else None

        # Validate scenario
        try:
            scenario = ResearchScenario(scenario_str)
        except ValueError:
            scenarios = ", ".join(s.value for s in ResearchScenario)
            return f"[red]Unknown scenario:[/red] {scenario_str}\n[dim]Available: {scenarios}[/dim]"

        # Validate role if provided
        role = None
        if role_str:
            try:
                role = ResearcherRole(role_str)
            except ValueError:
                roles = ", ".join(r.value for r in ResearcherRole)
                return f"[red]Unknown role:[/red] {role_str}\n[dim]Available: {roles}[/dim]"

        # Validate skill if provided
        skill = None
        if skill_str:
            try:
                skill = JudgeSkill(skill_str)
            except ValueError:
                skills = ", ".join(s.value for s in JudgeSkill)
                return f"[red]Unknown skill:[/red] {skill_str}\n[dim]Available: {skills}[/dim]"

        # Create JudgeBuddy and run review
        buddy = get_judge_for_scenario(scenario, role=role, skill=skill)

        self._spinner.start(f"{buddy.render_face()} {buddy.name} is evaluating...")

        try:
            reviewer = self._get_agent("reviewer")
            review = reviewer.review_with_buddy(
                artifact=content.strip(),
                scenario=scenario,
                role=role,
                skill=skill,
            )
            self._spinner.stop()

            # Format output with buddy face
            result_panel = self._format_judge_buddy_result(buddy, review)
            console.print(result_panel)
            return None

        except Exception as e:
            self._spinner.stop()
            return f"[red]Error:[/red] {str(e)}"

    def _handle_panel_command(self, cmd_args: str) -> Optional[str]:
        """Handle /panel command for multi-judge evaluation."""
        if not cmd_args:
            return """[yellow]Usage:[/yellow] /panel <scenario> [num_judges] -- <content>

[bold]Examples:[/bold]
  /panel full_paper -- <paper content>
  /panel idea_generation 3 -- My research idea...
  /panel experiment_design 5 -- Experiment plan..."""

        # Parse: scenario [num_judges] -- content
        if " -- " in cmd_args:
            config_part, content = cmd_args.split(" -- ", 1)
        else:
            return "[red]Error:[/red] Use ' -- ' to separate options from content."

        parts = config_part.strip().split()
        if not parts:
            return "[red]Error:[/red] Please specify a scenario."

        scenario_str = parts[0]
        num_judges = 3
        if len(parts) > 1:
            try:
                num_judges = int(parts[1])
            except ValueError:
                pass

        # Validate scenario
        try:
            scenario = ResearchScenario(scenario_str)
        except ValueError:
            scenarios = ", ".join(s.value for s in ResearchScenario)
            return f"[red]Unknown scenario:[/red] {scenario_str}\n[dim]Available: {scenarios}[/dim]"

        # Create panel
        panel = get_panel_for_scenario(scenario, num_judges)

        self._spinner.start(f"Judge Panel ({num_judges} judges) evaluating...")

        try:
            reviewer = self._get_agent("reviewer")
            result = reviewer.review_with_panel(
                artifact=content.strip(),
                scenario=scenario,
                num_judges=num_judges,
            )
            self._spinner.stop()

            # Format panel output
            result_panel = self._format_panel_result(result)
            console.print(result_panel)
            return None

        except Exception as e:
            self._spinner.stop()
            return f"[red]Error:[/red] {str(e)}"

    def _handle_compare_command(self, cmd_args: str) -> Optional[str]:
        """Handle /compare command for pairwise comparison."""
        if not cmd_args:
            return """[yellow]Usage:[/yellow] /compare <scenario> -- <artifact_a> ||| <artifact_b>

[bold]Examples:[/bold]
  /compare idea_generation -- Idea A text ||| Idea B text
  /compare code_review -- def foo(): ... ||| def foo(): ..."""

        # Parse: scenario -- artifact_a ||| artifact_b
        if " -- " not in cmd_args:
            return "[red]Error:[/red] Use ' -- ' to separate scenario from content."

        config_part, content = cmd_args.split(" -- ", 1)
        scenario_str = config_part.strip()

        if " ||| " not in content:
            return "[red]Error:[/red] Use ' ||| ' to separate the two artifacts."

        artifact_a, artifact_b = content.split(" ||| ", 1)

        # Validate scenario
        try:
            scenario = ResearchScenario(scenario_str)
        except ValueError:
            scenarios = ", ".join(s.value for s in ResearchScenario)
            return f"[red]Unknown scenario:[/red] {scenario_str}\n[dim]Available: {scenarios}[/dim]"

        self._spinner.start("Comparing artifacts...")

        try:
            reviewer = self._get_agent("reviewer")
            result = reviewer.compare_artifacts(
                artifact_a=artifact_a.strip(),
                artifact_b=artifact_b.strip(),
                scenario=scenario,
            )
            self._spinner.stop()

            # Format comparison result
            winner = result.get("winner", "Tie")
            confidence = result.get("confidence", "unknown")
            analysis = result.get("analysis", "")

            winner_color = {"A": "green", "B": "blue", "Tie": "yellow"}.get(winner, "white")

            table = Table(show_header=False, box=None)
            table.add_column(width=15)
            table.add_column()
            table.add_row("[bold]Winner[/bold]", f"[{winner_color}]{winner}[/{winner_color}]")
            table.add_row("[bold]Confidence[/bold]", confidence)
            table.add_row("[bold]Analysis[/bold]", analysis[:200] + "..." if len(analysis) > 200 else analysis)

            console.print(Panel(
                table,
                title="[bold cyan]Pairwise Comparison[/bold cyan]",
                border_style="cyan",
            ))
            return None

        except Exception as e:
            self._spinner.stop()
            return f"[red]Error:[/red] {str(e)}"

    def _show_scenarios(self) -> str:
        """Show available research scenarios."""
        lines = ["[bold cyan]Available Research Scenarios[/bold cyan]", "─" * 50]
        for scenario in ResearchScenario:
            cfg = SCENARIO_CONFIGS.get(scenario, {})
            desc = cfg.get("description", "")
            skill = cfg.get("recommended_skill", "geval")
            lines.append(f"  [bold]{scenario.value}[/bold]")
            lines.append(f"    {desc}")
            lines.append(f"    [dim]Recommended skill: {skill}[/dim]")
        return "\n".join(lines)

    def _show_roles(self) -> str:
        """Show available reviewer roles."""
        lines = ["[bold cyan]Available Reviewer Roles[/bold cyan]", "─" * 50]
        for role in ResearcherRole:
            cfg = RESEARCHER_ROLE_CONFIGS.get(role, {})
            name = cfg.get("name", role.value)
            focus = cfg.get("focus", "")
            species = cfg.get("buddy_species", "owl")
            lines.append(f"  [bold]{role.value}[/bold] ({name})")
            lines.append(f"    Focus: {focus}")
            lines.append(f"    [dim]Buddy: {species}[/dim]")
        return "\n".join(lines)

    def _show_skills(self) -> str:
        """Show available judge skills."""
        lines = ["[bold cyan]Available Judge Skills[/bold cyan]", "─" * 50]
        for skill in JudgeSkill:
            cfg = SKILL_CONFIGS.get(skill, {})
            desc = cfg.get("description", "")
            source = cfg.get("source", "")
            best_for = cfg.get("best_for", [])
            lines.append(f"  [bold]{skill.value}[/bold]")
            lines.append(f"    {desc}")
            lines.append(f"    [dim]Source: {source}[/dim]")
            lines.append(f"    [dim]Best for: {', '.join(best_for)}[/dim]")
        return "\n".join(lines)

    def _format_judge_buddy_result(self, buddy: JudgeBuddy, review) -> Panel:
        """Format JudgeBuddy review result."""
        table = Table(show_header=False, box=None)
        table.add_column(width=18)
        table.add_column()

        # Header with buddy face
        score = review.overall_score
        reaction = buddy.get_reaction(score)
        table.add_row(
            "[bold]Judge[/bold]",
            f"{buddy.render_face()} {buddy.name} ({buddy.title})"
        )
        table.add_row("[bold]Reaction[/bold]", reaction)
        table.add_row("[bold]Scenario[/bold]", buddy.scenario.value)
        table.add_row("[bold]Role[/bold]", buddy.role.value)
        table.add_row("[bold]Skill[/bold]", buddy.skill.value)
        table.add_row("", "")

        # Scores
        score_color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
        table.add_row("[bold]Overall Score[/bold]", f"[{score_color}]{score:.1f}/10[/{score_color}]")

        if review.dimension_scores:
            dims_str = ", ".join(f"{k}: {v:.1f}" for k, v in review.dimension_scores.items())
            table.add_row("[bold]Dimensions[/bold]", dims_str)

        table.add_row("[bold]Verdict[/bold]", review.verdict or "N/A")
        table.add_row("", "")

        # Summary
        if review.summary:
            table.add_row("[bold]Summary[/bold]", review.summary[:300])

        # Strengths
        if review.strengths:
            strengths_str = "\n".join(f"  + {s}" for s in review.strengths[:3])
            table.add_row("[bold]Strengths[/bold]", strengths_str)

        # Weaknesses
        if review.weaknesses:
            weaknesses = review.weaknesses[:3]
            weak_strs = []
            for w in weaknesses:
                if isinstance(w, dict):
                    weak_strs.append(f"  - {w.get('issue', str(w))}")
                else:
                    weak_strs.append(f"  - {w}")
            table.add_row("[bold]Weaknesses[/bold]", "\n".join(weak_strs))

        return Panel(
            table,
            title=f"[bold yellow]{buddy.get_catchphrase()}[/bold yellow]",
            border_style="yellow",
        )

    def _format_panel_result(self, result: dict) -> Panel:
        """Format Judge Panel result."""
        table = Table(show_header=False, box=None)
        table.add_column(width=18)
        table.add_column()

        # Panel info
        table.add_row("[bold]Scenario[/bold]", result.get("scenario", "unknown"))
        table.add_row("[bold]Judges[/bold]", str(result.get("num_judges", 0)))
        table.add_row("", "")

        # Aggregated scores
        agg = result.get("aggregated", {})
        score = agg.get("overall_score", 0)
        variance = agg.get("score_variance", 0)
        score_color = "green" if score >= 7 else "yellow" if score >= 5 else "red"

        table.add_row("[bold]Avg Score[/bold]", f"[{score_color}]{score:.1f}/10[/{score_color}] (variance: {variance:.1f})")
        table.add_row("[bold]Verdict[/bold]", result.get("verdict", "N/A"))
        table.add_row("", "")

        # Individual judge summaries
        table.add_row("[bold]Individual Reviews:[/bold]", "")
        for i, review_data in enumerate(result.get("individual_reviews", []), 1):
            judge = review_data.get("judge", {})
            review = review_data.get("review", {})
            judge_score = review.get("overall_score", 0)
            table.add_row(
                f"  {judge.get('name', f'Judge {i}')}",
                f"Score: {judge_score:.1f} | {judge.get('focus', '')[:30]}"
            )

        return Panel(
            table,
            title="[bold cyan]Judge Panel Results[/bold cyan]",
            border_style="cyan",
        )

    def parse_command(self, user_input: str) -> Optional[Tuple[str, str]]:
        """Parse slash command. Returns (cmd_name, args) or None."""
        if not user_input.startswith("/"):
            return None

        parts = user_input[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""
        return cmd_name, cmd_args


def run_interactive(config: Config, initial_agent: str = "solver") -> None:
    """Run interactive REPL mode.

    Default behavior: Run full workflow (Proposer → Solver → Reviewer)
    Use /solver to skip Proposer and run Solver directly.
    """
    cli = MarkScientistCLI(config)
    cli._current_agent = initial_agent  # Keep for compatibility

    # Welcome banner with Iron Man Mark I logo
    console.print()
    _print_welcome_banner(config)

    # Show taste profile status
    feedback_count = cli._taste_profile.get_total_feedback_count()
    if feedback_count > 0:
        console.print(f"[dim]Taste profile loaded: {feedback_count} feedback points[/dim]")

    session = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        completer=SlashCommandCompleter(),
    )

    last_ctrlc_time = 0.0

    while True:
        try:
            console.print()
            # Show workflow mode in prompt
            if cli._use_proposer:
                prompt_prefix = "[workflow]"
            else:
                prompt_prefix = "[solver]"
            user_input = session.prompt(f"{prompt_prefix} > ").strip()

        except KeyboardInterrupt:
            now = time.monotonic()
            if now - last_ctrlc_time <= _DOUBLE_PRESS_TIMEOUT_MS:
                console.print("\n[dim]Goodbye.[/dim]")
                break
            last_ctrlc_time = now
            console.print("\n[dim yellow]Press Ctrl+C again to exit[/dim yellow]")
            continue

        except EOFError:
            console.print("\n[dim]Goodbye.[/dim]")
            break

        # Reset double-press timer
        last_ctrlc_time = 0.0

        if not user_input:
            continue

        # Handle exit commands
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # Handle slash commands
        cmd = cli.parse_command(user_input)
        if cmd is not None:
            cmd_name, cmd_args = cmd
            if cmd_name in ("exit", "quit"):
                console.print("[dim]Goodbye.[/dim]")
                break
            result = cli.handle_command(cmd_name, cmd_args)
            if result:
                console.print(result)
            continue

        # Smart routing: simple queries use fast path, complex tasks use full workflow
        if cli._is_simple_query(user_input):
            # Simple factual query - use fast path (Solver only)
            cli.run_simple_query(user_input)
        else:
            # Complex task - use full workflow
            cli.run_workflow(user_input, enable_proposer=cli._use_proposer)


def run_once(config: Config, task: str, agent_type: str = "solver",
             workflow: bool = False, json_output: bool = False,
             auto_review: bool = True) -> int:
    """Run a single task and exit."""
    cli = MarkScientistCLI(config)
    cli._auto_review = auto_review

    try:
        if workflow:
            from markscientist.workflow import BasicResearchWorkflow

            if not json_output:
                console.print(f"\n[bold cyan]MarkScientist Workflow[/bold cyan]")
                console.print(f"[dim]Task: {task[:100]}{'...' if len(task) > 100 else ''}[/dim]")

            wf = BasicResearchWorkflow(
                config=config,
                save_dir=config.trajectory.save_dir if config.trajectory.auto_save else None,
            )
            result = wf.run(task)

            if json_output:
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            else:
                console.print(Panel(
                    result.improved_output or result.solver_output,
                    title="[bold blue]Output[/bold blue]",
                    border_style="blue"
                ))
                console.print(f"\n[bold]Score:[/bold] {result.final_score:.1f}/10 | "
                            f"[bold]Success:[/bold] {result.success} | "
                            f"[bold]Iterations:[/bold] {result.iterations}")

        elif agent_type == "solver" and auto_review:
            # Solver with auto-review
            if json_output:
                payload = cli.run_solver_with_review_payload(task, show_spinner=False)
                result = payload["solver_result"]
                review = payload["review"]
                print(json.dumps(
                    {
                        "solver": result.to_dict(),
                        "reviewer": review.to_dict() if review is not None else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ))
            else:
                console.print(f"\n[bold cyan]MarkScientist Solver + Reviewer[/bold cyan]")
                console.print(f"[dim]Task: {task[:100]}{'...' if len(task) > 100 else ''}[/dim]")
                cli.run_solver_with_review(task)

        else:
            # Single agent without review
            if not json_output:
                console.print(f"\n[bold cyan]MarkScientist {agent_type.capitalize()}[/bold cyan]")
                console.print(f"[dim]Task: {task[:100]}{'...' if len(task) > 100 else ''}[/dim]")

            if json_output:
                if agent_type == "proposer":
                    proposal = cli.run_proposer(task, show_spinner=False)
                    print(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2))
                elif agent_type == "reviewer":
                    review = cli.run_reviewer(task, show_spinner=False)
                    print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
                else:
                    output = cli.run_query(task, agent_type, show_spinner=True)
                    print(json.dumps({"output": output}, ensure_ascii=False, indent=2))
            else:
                if agent_type == "proposer":
                    proposal = cli.run_proposer(task, show_spinner=True)
                    console.print(Panel(
                        cli._format_proposal_result(proposal),
                        title="[bold green]Proposer[/bold green]",
                        border_style="green",
                    ))
                elif agent_type == "reviewer":
                    review = cli.run_reviewer(task, show_spinner=True)
                    console.print(Panel(
                        cli._format_review_result(review),
                        title="[bold yellow]Reviewer Feedback[/bold yellow]",
                        border_style="yellow",
                    ))
                else:
                    output = cli.run_query(task, agent_type, show_spinner=True)
                    console.print(Panel(output, title=f"[bold]{agent_type.capitalize()}[/bold]"))

        return 0

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user.[/yellow]")
        return 130

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


def main(argv: Optional[list] = None) -> int:
    """CLI main entry."""
    parser = argparse.ArgumentParser(
        prog="markscientist",
        description="MarkScientist - Self-evolving Research Agent with Scientific Taste",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start interactive REPL (Solver + auto Reviewer)
  markscientist

  # Run a single task (Solver + Reviewer)
  markscientist "Analyze the complexity of this code"

  # Run without auto-review
  markscientist "Analyze code" --no-review

  # Use Proposer to generate hypothesis
  markscientist "Generate research ideas about caching" --agent proposer

  # Use Reviewer only
  markscientist "Evaluate this paper" --agent reviewer

  # Run complete workflow (with improvement loop)
  markscientist "Write a literature review" --workflow
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt to send (optional, starts REPL if not provided)",
    )

    parser.add_argument(
        "-p", "--print",
        action="store_true",
        help="Non-interactive: print response and exit",
    )

    parser.add_argument(
        "--agent",
        choices=["proposer", "solver", "reviewer"],
        default="solver",
        help="Agent type to use (default: solver)",
    )

    parser.add_argument(
        "--workflow",
        action="store_true",
        help="Run complete Proposer-Solver-Reviewer-Improve workflow",
    )

    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Disable auto Reviewer after Solver",
    )

    parser.add_argument(
        "--model",
        help="Model name to use",
    )

    parser.add_argument(
        "--workspace",
        help="Workspace directory",
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Disable trajectory auto-save",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="MarkScientist v0.1.0",
    )

    args = parser.parse_args(argv)

    # Load and update config
    config = Config.from_env()
    if args.model:
        config.model.model_name = args.model
    if args.workspace:
        config.workspace_root = Path(args.workspace)
    if args.no_save:
        config.trajectory.auto_save = False

    set_config(config)

    # Determine mode
    if args.prompt:
        # Non-interactive: run single task
        return run_once(config, args.prompt, args.agent, args.workflow,
                       args.json, auto_review=not args.no_review)
    elif args.print:
        # Read from stdin
        task = sys.stdin.read().strip()
        if not task:
            console.print("[red]No input provided.[/red]")
            return 1
        return run_once(config, task, args.agent, args.workflow,
                       args.json, auto_review=not args.no_review)
    else:
        # Interactive REPL
        run_interactive(config, args.agent)
        return 0


if __name__ == "__main__":
    sys.exit(main())
