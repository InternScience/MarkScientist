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

from markscientist.config import Config, get_config, set_config

console = Console()
_HISTORY_FILE = Path.home() / ".markscientist_history"

# Double-press timeout for Ctrl+C exit
_DOUBLE_PRESS_TIMEOUT_MS = 0.8


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands."""

    COMMANDS: list[tuple[str, str]] = [
        ('help', 'Show available commands'),
        ('solver', 'Run prompt with Solver agent (with auto-review)'),
        ('judge', 'Review content with Judge agent'),
        ('evaluator', 'Meta-evaluate with Evaluator agent'),
        ('workflow', 'Run full research workflow'),
        ('review', 'Toggle auto-review mode on/off'),
        ('model', 'Show or switch model'),
        ('config', 'Show current configuration'),
        ('clear', 'Clear conversation history'),
        ('exit', 'Exit the REPL'),
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
    """Interactive CLI for MarkScientist."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._current_agent = "solver"
        self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._spinner = SpinnerManager(console)
        self._auto_review = True  # Auto-review mode enabled by default
        self._last_prompt = ""
        self._last_output = ""  # Store last solver output for reference
        self._last_review_raw = ""

    def _get_agent(self, agent_type: str):
        """Get agent instance by type."""
        from markscientist.agents import SolverAgent, JudgeAgent, EvaluatorAgent

        workspace_root = self.config.workspace_root or Path.cwd()
        trace_dir = (
            self.config.trajectory.save_dir / self._session_id / agent_type
            if self.config.trajectory.auto_save
            else None
        )

        if agent_type == "solver":
            return SolverAgent(
                config=self.config,
                workspace_root=workspace_root,
                trace_dir=trace_dir,
            )
        elif agent_type == "judge":
            return JudgeAgent(
                config=self.config,
                workspace_root=workspace_root,
                trace_dir=trace_dir,
            )
        elif agent_type == "evaluator":
            return EvaluatorAgent(
                config=self.config,
                workspace_root=workspace_root,
                trace_dir=trace_dir,
            )
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

    def _format_review_result(self, review, buddy=None) -> Table:
        """Format Judge review result as a compact display."""
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

    def _format_evaluator_result(self, evaluation) -> Table:
        """Format Evaluator result as a compact display."""
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

    def run_solver_with_review(self, prompt: str) -> None:
        """Run Solver with automatic Judge review."""
        try:
            payload = self.run_solver_with_review_payload(prompt, show_spinner=True)
            solver_result = payload["solver_result"]
            review = payload["review"]

            console.print(Panel(
                solver_result.output,
                title="[bold blue]Solver Output[/bold blue]",
                border_style="blue"
            ))

            if review is not None:
                console.print()
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

    def run_solver_with_review_payload(self, prompt: str, show_spinner: bool = True) -> dict:
        if show_spinner:
            self._spinner.start("Solver executing...")

        solver = self._get_agent("solver")
        solver_result = solver.run(prompt)

        if show_spinner:
            self._spinner.stop()

        self._last_prompt = prompt
        self._last_output = solver_result.output
        self._last_review_raw = ""

        if not solver_result.success:
            raise RuntimeError(f"{solver_result.termination_reason}: {solver_result.output}")

        review = None
        if self._auto_review:
            if show_spinner:
                console.print()
                from markscientist.buddy import ReviewerBuddy, render_face, REVIEWER_SPECIES

                all_faces = " ".join([render_face(ReviewerBuddy.from_species(s)) for s in REVIEWER_SPECIES[:4]])
                self._spinner.start(f"{all_faces} Summoning reviewer...")

            judge = self._get_agent("judge")
            from markscientist.agents.judge import _build_review_prompt, _parse_review_output

            judge_result = judge.run(_build_review_prompt(solver_result.output, artifact_type="auto"))
            review = _parse_review_output(judge_result.output)
            review.termination_reason = judge_result.termination_reason
            review.metadata = dict(judge_result.metadata)

            if show_spinner:
                self._spinner.stop()
            self._last_review_raw = review.raw_output

        return {
            "solver_result": solver_result,
            "review": review,
        }

    def run_judge_review(self, prompt: str, show_spinner: bool = True):
        if show_spinner:
            self._spinner.start("Running judge...")
        from markscientist.agents.judge import _build_review_prompt, _parse_review_output

        judge = self._get_agent("judge")
        judge_result = judge.run(_build_review_prompt(prompt, artifact_type="auto"))
        review = _parse_review_output(judge_result.output)
        review.termination_reason = judge_result.termination_reason
        review.metadata = dict(judge_result.metadata)
        if show_spinner:
            self._spinner.stop()
        return review

    def run_evaluator_assessment(self, prompt: str, show_spinner: bool = True):
        if show_spinner:
            self._spinner.start("Running evaluator...")
        from markscientist.agents.evaluator import _build_evaluation_prompt, _parse_evaluation_output

        evaluator = self._get_agent("evaluator")
        evaluator_result = evaluator.run(
            _build_evaluation_prompt(
                original_prompt=self._last_prompt or prompt,
                solver_output=self._last_output,
                judge_review=self._last_review_raw or "No prior judge review available.",
                final_result=self._last_output,
            )
        )
        evaluation = _parse_evaluation_output(evaluator_result.output)
        evaluation.termination_reason = evaluator_result.termination_reason
        evaluation.metadata = dict(evaluator_result.metadata)
        if show_spinner:
            self._spinner.stop()
        return evaluation

    def run_query(self, prompt: str, agent_type: Optional[str] = None,
                  show_spinner: bool = True) -> str:
        """Run a query with the specified agent (without auto-review)."""
        agent_type = agent_type or self._current_agent

        if show_spinner:
            self._spinner.start(f"Running {agent_type}...")

        try:
            if agent_type == "judge":
                review = self.run_judge_review(prompt, show_spinner=show_spinner)
                return json.dumps(review.to_dict(), ensure_ascii=False, indent=2)
            if agent_type == "evaluator":
                evaluation = self.run_evaluator_assessment(prompt, show_spinner=show_spinner)
                return json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2)

            agent = self._get_agent(agent_type)
            result = agent.run(prompt)
            if show_spinner:
                self._spinner.stop()
            if result.success:
                return result.output
            return f"[Error] {result.termination_reason}: {result.output}"

        except Exception as e:
            if show_spinner:
                self._spinner.stop()
            return f"[Error] {str(e)}"

    def run_workflow(self, prompt: str) -> None:
        """Run the full research workflow."""
        from markscientist.workflow import BasicResearchWorkflow

        self._spinner.start("Running workflow...")

        try:
            workflow = BasicResearchWorkflow(
                config=self.config,
                save_dir=self.config.trajectory.save_dir if self.config.trajectory.auto_save else None,
            )
            result = workflow.run(prompt)

            self._spinner.stop()

            # Display workflow result
            console.print(Panel(
                result.solver_output[:2000] + ("..." if len(result.solver_output) > 2000 else ""),
                title="[bold blue]Final Output[/bold blue]",
                border_style="blue"
            ))

            # Summary table
            summary_table = Table(show_header=False, box=None)
            summary_table.add_column("Label", style="dim")
            summary_table.add_column("Value")

            status = "[green]Success[/green]" if result.success else "[red]Failed[/red]"
            score_color = "green" if result.final_score >= 7 else "yellow" if result.final_score >= 5 else "red"

            summary_table.add_row("Status", status)
            summary_table.add_row("Final Score", f"[{score_color} bold]{result.final_score:.1f}/10[/{score_color} bold]")
            summary_table.add_row("Iterations", str(result.iterations))

            if result.judge_review and result.judge_review.verdict:
                summary_table.add_row("Verdict", result.judge_review.verdict)

            console.print(Panel(
                summary_table,
                title="[bold green]Workflow Complete[/bold green]",
                border_style="green"
            ))

        except Exception as e:
            self._spinner.stop()
            console.print(f"[red]Error:[/red] {str(e)}")

    def handle_command(self, cmd_name: str, cmd_args: str) -> Optional[str]:
        """Handle slash commands. Returns None to continue, string to print."""
        if cmd_name == "help":
            return self._show_help()

        elif cmd_name == "solver":
            self._current_agent = "solver"
            if cmd_args:
                self.run_solver_with_review(cmd_args)
                return None  # Already printed
            return "[green]Switched to Solver agent (auto-review enabled).[/green]"

        elif cmd_name == "judge":
            self._current_agent = "judge"
            if cmd_args:
                review = self.run_judge_review(cmd_args, show_spinner=True)
                console.print(Panel(
                    self._format_review_result(review),
                    title="[bold yellow]Judge Review[/bold yellow]",
                    border_style="yellow",
                ))
                return None
            return "[green]Switched to Judge agent.[/green] Enter content to review."

        elif cmd_name == "evaluator":
            self._current_agent = "evaluator"
            if cmd_args:
                evaluation = self.run_evaluator_assessment(cmd_args, show_spinner=True)
                console.print(Panel(
                    self._format_evaluator_result(evaluation),
                    title="[bold magenta]Evaluator[/bold magenta]",
                    border_style="magenta",
                ))
                return None
            return "[green]Switched to Evaluator agent.[/green] Enter an evaluation prompt."

        elif cmd_name == "workflow":
            if cmd_args:
                self.run_workflow(cmd_args)
                return None
            return "[yellow]Usage:[/yellow] /workflow <prompt>"

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
            return "[green]Session cleared.[/green] New session started."

        elif cmd_name in ("exit", "quit"):
            return None  # Signal to exit

        else:
            return f"[red]Unknown command:[/red] /{cmd_name}. Type /help for available commands."

    def _show_help(self) -> str:
        auto_status = "[green]ON[/green]" if self._auto_review else "[yellow]OFF[/yellow]"
        return f"""
[bold cyan]MarkScientist Commands[/bold cyan]
{'─' * 50}
  [bold]/help[/bold]        Show this help message
  [bold]/solver[/bold]      Switch to Solver (with auto-review)
  [bold]/judge[/bold]       Switch to Judge agent
  [bold]/evaluator[/bold]   Switch to Evaluator agent
  [bold]/workflow[/bold]    Run full Solver→Judge→Improve→Evaluate loop
  [bold]/review[/bold]      Toggle auto-review mode (currently {auto_status})
  [bold]/model[/bold]       Show or switch model
  [bold]/config[/bold]      Show current configuration
  [bold]/clear[/bold]       Clear session
  [bold]/exit[/bold]        Exit

[bold cyan]How it works[/bold cyan]
{'─' * 50}
  [bold]Solver[/bold]    - Executes research tasks using tools
  [bold]Judge[/bold]     - Reviews output quality (auto after Solver)
  [bold]Evaluator[/bold] - Meta-evaluates system performance
  [bold]Workflow[/bold]  - Full loop with auto-improvement if score < 6

[dim]Tips: Ctrl+C twice to exit | Direct input goes to current agent[/dim]
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
[bold]Workspace Root:[/bold] {self.config.workspace_root or Path.cwd()}
[bold]Save trajectories:[/bold] {self.config.trajectory.auto_save}
"""

    def parse_command(self, prompt: str) -> Optional[Tuple[str, str]]:
        """Parse slash command. Returns (cmd_name, args) or None."""
        if not prompt.startswith("/"):
            return None

        parts = prompt[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""
        return cmd_name, cmd_args


def run_interactive(config: Config, initial_agent: str = "solver") -> None:
    """Run interactive REPL mode."""
    cli = MarkScientistCLI(config)
    cli._current_agent = initial_agent

    # Welcome message
    console.print()
    console.print("[bold cyan]MarkScientist[/bold cyan]  "
                  f"[dim]{config.model.model_name}[/dim]")
    console.print(f"[dim]Auto-review: ON | Type /help for commands | Ctrl+C twice to exit[/dim]")

    session = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        completer=SlashCommandCompleter(),
    )

    last_ctrlc_time = 0.0

    while True:
        try:
            console.print()
            prompt_prefix = f"[{cli._current_agent}]"
            if cli._auto_review and cli._current_agent == "solver":
                prompt_prefix = f"[{cli._current_agent}+judge]"
            prompt = session.prompt(f"{prompt_prefix} > ").strip()

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

        if not prompt:
            continue

        # Handle exit commands
        if prompt.lower() in ("exit", "quit", "/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # Handle slash commands
        cmd = cli.parse_command(prompt)
        if cmd is not None:
            cmd_name, cmd_args = cmd
            if cmd_name in ("exit", "quit"):
                console.print("[dim]Goodbye.[/dim]")
                break
            result = cli.handle_command(cmd_name, cmd_args)
            if result:
                console.print(result)
            continue

        # Regular query - use auto-review for solver
        if cli._current_agent == "solver" and cli._auto_review:
            cli.run_solver_with_review(prompt)
        else:
            if cli._current_agent == "judge":
                review = cli.run_judge_review(prompt, show_spinner=True)
                console.print(Panel(
                    cli._format_review_result(review),
                    title="[bold yellow]Judge Review[/bold yellow]",
                    border_style="yellow",
                ))
            elif cli._current_agent == "evaluator":
                evaluation = cli.run_evaluator_assessment(prompt, show_spinner=True)
                console.print(Panel(
                    cli._format_evaluator_result(evaluation),
                    title="[bold magenta]Evaluator[/bold magenta]",
                    border_style="magenta",
                ))
            else:
                result = cli.run_query(prompt)
                agent_color = {"solver": "blue", "judge": "yellow", "evaluator": "magenta"}.get(cli._current_agent, "white")
                console.print(Panel(
                    result,
                    title=f"[bold {agent_color}]{cli._current_agent.capitalize()}[/bold {agent_color}]",
                    border_style=agent_color
                ))


def run_once(config: Config, prompt: str, agent_type: str = "solver",
             workflow: bool = False, json_output: bool = False,
             auto_review: bool = True) -> int:
    """Run a single prompt and exit."""
    cli = MarkScientistCLI(config)
    cli._auto_review = auto_review

    try:
        if workflow:
            from markscientist.workflow import BasicResearchWorkflow

            if not json_output:
                console.print(f"\n[bold cyan]MarkScientist Workflow[/bold cyan]")
                console.print(f"[dim]Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}[/dim]")

            wf = BasicResearchWorkflow(
                config=config,
                save_dir=config.trajectory.save_dir if config.trajectory.auto_save else None,
            )
            result = wf.run(prompt)

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
                payload = cli.run_solver_with_review_payload(prompt, show_spinner=False)
                result = payload["solver_result"]
                review = payload["review"]
                print(json.dumps(
                    {
                        "solver": result.to_dict(),
                        "judge": review.to_dict() if review is not None else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ))
            else:
                console.print(f"\n[bold cyan]MarkScientist Solver + Judge[/bold cyan]")
                console.print(f"[dim]Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}[/dim]")
                cli.run_solver_with_review(prompt)

        else:
            # Single agent without review
            if not json_output:
                console.print(f"\n[bold cyan]MarkScientist {agent_type.capitalize()}[/bold cyan]")
                console.print(f"[dim]Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}[/dim]")

            if json_output:
                if agent_type == "judge":
                    review = cli.run_judge_review(prompt, show_spinner=False)
                    print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
                elif agent_type == "evaluator":
                    evaluation = cli.run_evaluator_assessment(prompt, show_spinner=False)
                    print(json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2))
                else:
                    output = cli.run_query(prompt, agent_type, show_spinner=True)
                    print(json.dumps({"output": output}, ensure_ascii=False, indent=2))
            else:
                if agent_type == "judge":
                    review = cli.run_judge_review(prompt, show_spinner=True)
                    console.print(Panel(
                        cli._format_review_result(review),
                        title="[bold yellow]Judge Review[/bold yellow]",
                        border_style="yellow",
                    ))
                elif agent_type == "evaluator":
                    evaluation = cli.run_evaluator_assessment(prompt, show_spinner=True)
                    console.print(Panel(
                        cli._format_evaluator_result(evaluation),
                        title="[bold magenta]Evaluator[/bold magenta]",
                        border_style="magenta",
                    ))
                else:
                    output = cli.run_query(prompt, agent_type, show_spinner=True)
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
  # Start interactive REPL (Solver + auto Judge review)
  markscientist

  # Run a single prompt (Solver + Judge review)
  markscientist "Analyze the complexity of this code"

  # Run without auto-review
  markscientist "Analyze code" --no-review

  # Use Judge only
  markscientist "Evaluate this paper" --agent judge

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
        choices=["solver", "judge", "evaluator"],
        default="solver",
        help="Agent type to use (default: solver)",
    )

    parser.add_argument(
        "--workflow",
        action="store_true",
        help="Run complete Solver-Judge-Improve-Evaluate workflow",
    )

    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Disable auto Judge review after Solver",
    )

    parser.add_argument(
        "--model",
        help="Model name to use",
    )

    parser.add_argument(
        "--workspace-root",
        help="Workspace root",
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
    if args.workspace_root:
        config.workspace_root = Path(args.workspace_root)
    if args.no_save:
        config.trajectory.auto_save = False

    set_config(config)

    # Determine mode
    if args.prompt:
        # Non-interactive: run single prompt
        return run_once(config, args.prompt, args.agent, args.workflow,
                       args.json, auto_review=not args.no_review)
    elif args.print:
        # Read from stdin
        prompt = sys.stdin.read().strip()
        if not prompt:
            console.print("[red]No input provided.[/red]")
            return 1
        return run_once(config, prompt, args.agent, args.workflow,
                       args.json, auto_review=not args.no_review)
    else:
        # Interactive REPL
        run_interactive(config, args.agent)
        return 0


if __name__ == "__main__":
    sys.exit(main())
