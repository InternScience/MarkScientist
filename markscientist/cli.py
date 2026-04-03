from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

from markscientist.config import Config, get_config, set_config
from markscientist.project import ensure_project_layout, load_checklist_text, read_text_if_exists

console = Console()
_HISTORY_FILE = Path.home() / ".markscientist_history"
_DOUBLE_PRESS_TIMEOUT_SECONDS = 0.8


class SlashCommandCompleter(Completer):
    COMMANDS: list[tuple[str, str]] = [
        ("help", "Show available commands"),
        ("workflow", "Run Challenger -> Solver -> Judge"),
        ("challenger", "Run the Challenger only"),
        ("solver", "Run the Solver only"),
        ("judge", "Run the Judge only"),
        ("model", "Show or switch model"),
        ("config", "Show current configuration"),
        ("clear", "Start a new session"),
        ("exit", "Exit the REPL"),
    ]

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        query = text[1:].lower()
        for name, desc in self.COMMANDS:
            if not query or name.startswith(query):
                yield Completion(
                    f"/{name}",
                    start_position=-len(text),
                    display=f"/{name}",
                    display_meta=desc,
                )


class SpinnerManager:
    def __init__(self, con: Console):
        self._console = con
        self._live: Optional[Live] = None
        self._spinner: Optional[Spinner] = None

    def start(self, message: str):
        self.stop()
        self._spinner = Spinner("dots", text=f"[dim]{message}[/dim]")
        self._live = Live(self._spinner, console=self._console, refresh_per_second=10)
        self._live.start()

    def stop(self):
        if self._live is not None:
            self._live.stop()
            self._live = None
            self._spinner = None


class MarkScientistCLI:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._mode = "workflow"
        self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._spinner = SpinnerManager(console)

    def _workspace_root(self) -> Path:
        return (self.config.workspace_root or Path.cwd()).expanduser().resolve()

    def _trace_dir(self, agent_type: str) -> Optional[Path]:
        if not self.config.trajectory.auto_save:
            return None
        return self.config.trajectory.save_dir / self._session_id / agent_type

    def _get_agent(self, agent_type: str):
        from markscientist.agents import ChallengerAgent, JudgeAgent, SolverAgent

        workspace_root = self._workspace_root()
        if agent_type == "challenger":
            return ChallengerAgent(config=self.config, workspace_root=workspace_root, trace_dir=self._trace_dir(agent_type))
        if agent_type == "solver":
            return SolverAgent(config=self.config, workspace_root=workspace_root, trace_dir=self._trace_dir(agent_type))
        if agent_type == "judge":
            return JudgeAgent(config=self.config, workspace_root=workspace_root, trace_dir=self._trace_dir(agent_type))
        raise ValueError(f"Unknown agent type: {agent_type}")

    def _format_review_result(self, review) -> Table:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value")
        score_color = "green" if review.overall_score >= 7 else "yellow" if review.overall_score >= 5 else "red"
        table.add_row("Score", f"[{score_color} bold]{review.overall_score:.1f}/10[/{score_color} bold]")
        table.add_row("Verdict", review.verdict or "Unspecified")
        if review.summary:
            table.add_row("Summary", review.summary[:160])
        if review.suggestions:
            table.add_row("Suggestions", " | ".join(review.suggestions[:3]))
        return table

    def _show_config(self) -> str:
        return (
            "[bold cyan]Current Configuration[/bold cyan]\n"
            f"{'─' * 40}\n"
            f"[bold]Model:[/bold] {self.config.model.model_name}\n"
            f"[bold]Mode:[/bold] {self._mode}\n"
            f"[bold]Workspace Root:[/bold] {self._workspace_root()}\n"
            f"[bold]Save trajectories:[/bold] {self.config.trajectory.auto_save}\n"
            f"[bold]Trajectory dir:[/bold] {self.config.trajectory.save_dir}\n"
        )

    def run_challenger(self, prompt: str, show_spinner: bool = True):
        from markscientist.prompts import CHALLENGE_REQUEST_TEMPLATE

        workspace_root = self._workspace_root()
        ensure_project_layout(workspace_root)
        if show_spinner:
            self._spinner.start("Challenger preparing project...")
        try:
            result = self._get_agent("challenger").run(
                CHALLENGE_REQUEST_TEMPLATE.format(original_prompt=prompt),
                workspace_root=workspace_root,
            )
            return result
        finally:
            if show_spinner:
                self._spinner.stop()

    def run_solver(self, prompt: str, additional_guidance: str = "", show_spinner: bool = True):
        from markscientist.prompts import SOLVER_REQUEST_TEMPLATE

        workspace_root = self._workspace_root()
        ensure_project_layout(workspace_root)
        if show_spinner:
            self._spinner.start("Solver executing project...")
        try:
            result = self._get_agent("solver").run(
                SOLVER_REQUEST_TEMPLATE.format(
                    original_prompt=prompt,
                    additional_guidance=additional_guidance or "Complete the prepared project end-to-end.",
                ),
                workspace_root=workspace_root,
            )
            return result
        finally:
            if show_spinner:
                self._spinner.stop()

    def run_judge(self, prompt: str, show_spinner: bool = True):
        from markscientist.agents.judge import _build_review_prompt, _parse_review_output

        workspace_root = self._workspace_root()
        paths = ensure_project_layout(workspace_root)
        challenge_brief = read_text_if_exists(paths.challenge_brief_path, default="challenge/brief.md is missing.")
        checklist_text = load_checklist_text(paths.checklist_path)
        report_text = read_text_if_exists(paths.report_path, default="report/report.md is missing.")
        if show_spinner:
            self._spinner.start("Judge reviewing report...")
        try:
            result = self._get_agent("judge").run(
                _build_review_prompt(
                    original_prompt=prompt,
                    challenge_brief=challenge_brief,
                    checklist_text=checklist_text,
                    report_text=report_text,
                ),
                workspace_root=workspace_root,
            )
            review = _parse_review_output(result.output)
            review.termination_reason = result.termination_reason
            review.trace_path = result.trace_path
            return review
        finally:
            if show_spinner:
                self._spinner.stop()

    def run_workflow(self, prompt: str, show_spinner: bool = True):
        from markscientist.workflow import ResearchWorkflow

        if show_spinner:
            self._spinner.start("Running Challenger -> Solver -> Judge...")
        try:
            workflow = ResearchWorkflow(
                config=self.config,
                save_dir=self.config.trajectory.save_dir if self.config.trajectory.auto_save else None,
            )
            return workflow.run(prompt, workspace_root=self._workspace_root())
        finally:
            if show_spinner:
                self._spinner.stop()

    def parse_command(self, prompt: str) -> Optional[Tuple[str, str]]:
        if not prompt.startswith("/"):
            return None
        parts = prompt[1:].split(maxsplit=1)
        return parts[0].lower(), parts[1] if len(parts) > 1 else ""

    def handle_command(self, command: str, args: str) -> Optional[str]:
        if command == "help":
            return self._show_help()
        if command == "workflow":
            self._mode = "workflow"
            if args:
                self._print_workflow(self.run_workflow(args))
                return None
            return "[green]Switched to workflow mode.[/green]"
        if command == "challenger":
            self._mode = "challenger"
            if args:
                self._print_agent_result("Challenger", self.run_challenger(args))
                return None
            return "[green]Switched to challenger mode.[/green]"
        if command == "solver":
            self._mode = "solver"
            if args:
                self._print_agent_result("Solver", self.run_solver(args))
                return None
            return "[green]Switched to solver mode.[/green]"
        if command == "judge":
            self._mode = "judge"
            if args:
                self._print_review(self.run_judge(args))
                return None
            return "[green]Switched to judge mode.[/green]"
        if command == "model":
            if args:
                self.config.model.model_name = args
                return f"[green]Model switched to:[/green] {args}"
            return f"[bold]Current model:[/bold] {self.config.model.model_name}"
        if command == "config":
            return self._show_config()
        if command == "clear":
            self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
            return "[green]Session cleared.[/green]"
        if command in {"exit", "quit"}:
            return None
        return f"[red]Unknown command:[/red] /{command}"

    def _show_help(self) -> str:
        return (
            "[bold cyan]MarkScientist Commands[/bold cyan]\n"
            f"{'─' * 50}\n"
            "  [bold]/workflow[/bold]    Run Challenger -> Solver -> Judge\n"
            "  [bold]/challenger[/bold]  Run the Challenger only\n"
            "  [bold]/solver[/bold]      Run the Solver only\n"
            "  [bold]/judge[/bold]       Run the Judge only\n"
            "  [bold]/model[/bold]       Show or switch model\n"
            "  [bold]/config[/bold]      Show current configuration\n"
            "  [bold]/clear[/bold]       Start a new session\n"
            "  [bold]/exit[/bold]        Exit\n"
        )

    def _print_agent_result(self, title: str, result) -> None:
        border = "blue" if result.success else "red"
        console.print(Panel(result.output, title=f"[bold {border}]{title}[/bold {border}]", border_style=border))

    def _print_review(self, review) -> None:
        console.print(Panel(self._format_review_result(review), title="[bold yellow]Judge Review[/bold yellow]", border_style="yellow"))

    def _print_workflow(self, result) -> None:
        console.print(Panel(result.solver_output, title="[bold blue]report/report.md[/bold blue]", border_style="blue"))
        summary = Table(show_header=False, box=None, padding=(0, 1))
        summary.add_column("Label", style="dim")
        summary.add_column("Value")
        status = "[green]Success[/green]" if result.success else "[red]Needs Improvement[/red]"
        summary.add_row("Status", status)
        summary.add_row("Score", f"{result.final_score:.1f}/10")
        summary.add_row("Iterations", str(result.iterations))
        summary.add_row("Workspace", result.workspace_root)
        summary.add_row("Report", result.metadata.get("report_path", ""))
        console.print(Panel(summary, title="[bold green]Workflow Summary[/bold green]", border_style="green"))


def run_interactive(config: Config) -> None:
    cli = MarkScientistCLI(config)
    console.print()
    console.print(f"[bold cyan]MarkScientist[/bold cyan]  [dim]{config.model.model_name}[/dim]")
    console.print("[dim]Default mode: workflow | Type /help for commands | Ctrl+C twice to exit[/dim]")

    session = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        completer=SlashCommandCompleter(),
    )
    last_ctrlc = 0.0

    while True:
        try:
            console.print()
            prompt = session.prompt(f"[{cli._mode}] > ").strip()
        except KeyboardInterrupt:
            now = time.monotonic()
            if now - last_ctrlc <= _DOUBLE_PRESS_TIMEOUT_SECONDS:
                console.print("\n[dim]Goodbye.[/dim]")
                break
            last_ctrlc = now
            console.print("\n[dim yellow]Press Ctrl+C again to exit[/dim yellow]")
            continue
        except EOFError:
            console.print("\n[dim]Goodbye.[/dim]")
            break

        last_ctrlc = 0.0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit", "/exit", "/quit"}:
            console.print("[dim]Goodbye.[/dim]")
            break
        command = cli.parse_command(prompt)
        if command is not None:
            command_name, command_args = command
            if command_name in {"exit", "quit"}:
                console.print("[dim]Goodbye.[/dim]")
                break
            result = cli.handle_command(command_name, command_args)
            if result is not None:
                console.print(result)
            continue

        if cli._mode == "challenger":
            cli._print_agent_result("Challenger", cli.run_challenger(prompt))
        elif cli._mode == "solver":
            cli._print_agent_result("Solver", cli.run_solver(prompt))
        elif cli._mode == "judge":
            cli._print_review(cli.run_judge(prompt))
        else:
            cli._print_workflow(cli.run_workflow(prompt))


def run_once(config: Config, prompt: str, agent_type: Optional[str] = None, json_output: bool = False) -> int:
    cli = MarkScientistCLI(config)
    try:
        if agent_type == "challenger":
            result = cli.run_challenger(prompt, show_spinner=not json_output)
            payload = result.to_dict()
        elif agent_type == "solver":
            result = cli.run_solver(prompt, show_spinner=not json_output)
            payload = result.to_dict()
        elif agent_type == "judge":
            review = cli.run_judge(prompt, show_spinner=not json_output)
            payload = review.to_dict()
        else:
            workflow_result = cli.run_workflow(prompt, show_spinner=not json_output)
            payload = workflow_result.to_dict()

        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if agent_type == "judge":
                cli._print_review(review)
            elif agent_type in {"challenger", "solver"}:
                cli._print_agent_result(agent_type.capitalize(), result)
            else:
                cli._print_workflow(workflow_result)
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        return 130
    except Exception as exc:
        console.print(f"\n[red]Error:[/red] {exc}")
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="markscientist",
        description="MarkScientist - Challenger, Solver, and Judge on top of ResearchHarness",
    )
    parser.add_argument("prompt", nargs="?", help="Prompt to send. Starts the REPL if omitted.")
    parser.add_argument(
        "--agent",
        choices=["challenger", "solver", "judge"],
        help="Run a single role only. If omitted, run the full Challenger -> Solver -> Judge workflow.",
    )
    parser.add_argument("--model", help="Model name to use.")
    parser.add_argument("--workspace-root", help="Workspace root.")
    parser.add_argument("--no-save", action="store_true", help="Disable trajectory auto-save.")
    parser.add_argument("--json", action="store_true", help="Output JSON and exit.")
    parser.add_argument("--version", action="version", version="MarkScientist 0.1.0")
    args = parser.parse_args(argv)

    config = Config.from_env()
    if args.model:
        config.model.model_name = args.model
    if args.workspace_root:
        config.workspace_root = Path(args.workspace_root)
    if args.no_save:
        config.trajectory.auto_save = False
    set_config(config)

    if args.prompt:
        return run_once(config, args.prompt, agent_type=args.agent, json_output=args.json)

    run_interactive(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
