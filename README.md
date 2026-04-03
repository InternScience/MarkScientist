<div align="center">

# 🔬 MarkScientist

**Self-evolving Research Agent with Built-in Scientific Taste**

**Challenger prepares → Solver researches → Judge reviews**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Built On](https://img.shields.io/badge/Built%20On-ResearchHarness-2563eb.svg)](https://github.com/black-yt/ResearchHarness)
[![Workflow](https://img.shields.io/badge/Workflow-Challenger%20Solver%20Judge-4f46e5.svg)](#-how-it-works)
[![Trace](https://img.shields.io/badge/Trace-Workflow%20Summary-0f766e.svg)](#-how-it-works)
[![Scope](https://img.shields.io/badge/Scope-Scientific%20Workflow-orange.svg)](#-architecture-boundary)

</div>

MarkScientist is a higher-layer framework for turning a user request into a **research project workspace**, executing that project, and reviewing the resulting report on top of ResearchHarness.

Unlike a standalone execution harness, this project is intentionally centered on:

- Challenger, Solver, and Judge role separation
- project-first research workflows
- review-driven improvement loops
- workflow-level traces layered on top of per-agent harness traces
- higher-level orchestration and evaluation policies
- a CLI that exposes the full research loop across multiple agents

The point is not to replace ResearchHarness. The point is to build a **scientific workflow layer** that reuses the lower-layer runtime while adding project setup, role structure, review pressure, and orchestration logic.

---

## 📚 Table of Contents

- [✨ Highlights](#-highlights)
- [⚡ Quick Start](#-quick-start)
- [🧠 How It Works](#-how-it-works)
- [🗂 Project Model](#-project-model)
- [🧭 Architecture Boundary](#-architecture-boundary)
- [💬 Usage](#-usage)
- [📋 Commands](#-commands)
- [⚙️ Config](#️-config)
- [🧪 Testing](#-testing)
- [🪪 License](#-license)

---

## ✨ Highlights

- **Built on ResearchHarness**
  ResearchHarness owns SDK calls, tool calling, and the ReAct loop; MarkScientist owns multi-agent roles and workflow orchestration.
- **Three-role research loop**
  Challenger prepares the project, Solver performs the research, and Judge scores the resulting report.
- **Project-first execution**
  The workflow is built around a concrete workspace with instructions, checklist, code, outputs, and `report/report.md`.
- **Review-driven improvement**
  The workflow can iteratively improve outputs based on Judge feedback instead of stopping at one draft.
- **Conditional re-challenge**
  Judge can send the workflow back to Challenger when the project definition itself is too weak, not just the report.
- **Workflow-level traces**
  MarkScientist preserves per-agent ResearchHarness traces and adds a higher-level workflow summary.
- **Checklist-based judging**
  Judge scores the report against an explicit challenge brief and checklist rather than vague style preferences.

### At a Glance

| Area | What MarkScientist focuses on |
| --- | --- |
| Runtime dependency | Reuses ResearchHarness for execution |
| Roles | Challenger, Solver, Judge |
| Core artifact | A prepared research project workspace |
| Review model | Score, critique, and improve the report |
| Trace model | Workflow summary plus per-agent traces |
| UX | Interactive multi-agent CLI |
| Scope | Scientific workflow layer, not execution harness |

## 🚀 Quick Start

```bash
git submodule update --init --recursive
pip install -e .
markscientist
```

`MarkScientist` currently assumes a source checkout with the `ResearchHarness` git submodule available. Wheel-only installs are not a supported standalone distribution mode.

## 🧠 How It Works

`MarkScientist` is not a second execution harness. It is a higher-layer framework built on top of `ResearchHarness`.

```mermaid
flowchart TD
    U[User Prompt] --> WF[Workflow Scheduler]
    WF --> C[Challenger]
    C --> P[Prepared Project Workspace]
    P --> S[Solver]
    S --> R[report/report.md]
    R --> J[Judge]
    J --> F{Next Action}
    F -->|solver_revision| S
    F -->|rechallenge| C
    F -->|accept| DONE[Workflow Complete]
    WF --> T[Workflow Trace Summary]
```

The lower-layer execution details live in `ResearchHarness`, and `MarkScientist` connects to them like this:

```mermaid
flowchart TD
    subgraph MS[MarkScientist]
        WF[Workflow / Scheduling] --> AG[Challenger / Solver / Judge]
        AG --> RP[Role Prompts]
        WF --> WR[Workflow Trajectory Wrapper]
    end

    subgraph RH[ResearchHarness]
        AB[BaseAgent / MultiTurnReactAgent]
        LOOP[ReAct Runtime]
        TOOLS[Tool Registry + Execution]
        TRACE[FlatTraceWriter]
    end

    AG --> AB
    AB --> LOOP
    LOOP --> TOOLS
    LOOP --> TRACE
    WR --> TRACE
```

## 🗂 Project Model

The workflow prepares and executes a project workspace inspired by benchmark-style research tasks.

Expected layout:

```text
workspace_root/
  INSTRUCTIONS.md
  challenge/
    brief.md
    checklist.json
  data/
  related_work/
  code/
  outputs/
  report/
    report.md
    images/
```

Role responsibilities:

- `Challenger` prepares `INSTRUCTIONS.md`, `challenge/brief.md`, and `challenge/checklist.json`.
- `Solver` reads the prepared project, performs the research, and must finish with `report/report.md`.
- `Judge` reads the brief, checklist, and report, then returns strict JSON scoring feedback plus the next workflow action.

## 🧭 Architecture Boundary

- `ResearchHarness` is the execution layer:
  - OpenAI-compatible SDK calls
  - native tool calling
  - ReAct loop
  - tool registry and execution
  - flat per-agent trace writing
- `MarkScientist` is the orchestration layer:
  - Challenger / Solver / Judge roles
  - project preparation and workflow scheduling
  - solver/judge improvement loops
  - role-specific prompt addenda
  - workflow-level trajectory summaries

`MarkScientist` agents inherit the ResearchHarness agent base instead of reimplementing the lower-layer execution stack.

## 💬 Usage

### Interactive REPL

```bash
markscientist
```

Default mode runs the full research workflow.

```
[workflow] > Analyze the attached dataset and produce a research report.

╭──────────────── Final Report ────────────────╮
│ # Research Report                            │
│ ...                                          │
╰──────────────────────────────────────────────╯

╭──────────── Workflow Summary ────────────────╮
│ Status      Success                          │
│ Score       7.5/10                           │
│ Iterations  2                                │
╰──────────────────────────────────────────────╯
```

Switch to a single role when needed:

```
[workflow] > /challenger
[challenger] > Prepare a project for reproducing the core claim.

[challenger] > /solver
[solver] > Execute the prepared project and write the report.

[solver] > /judge
[judge] > Score the current report against the project checklist.
```

### CLI One-Shot Commands

```bash
# Full Challenger -> Solver -> Judge workflow
markscientist "Study whether the benchmark result is reproducible"

# Challenger only
markscientist "Prepare a project for evaluating the dataset" --agent challenger

# Solver only
markscientist "Execute the prepared project" --agent solver

# Judge only
markscientist "Review the current report" --agent judge

# JSON output
markscientist "Review the current report" --agent judge --json
```

### Python API

```python
from pathlib import Path

from markscientist.config import Config, set_config

config = Config.from_env()
config.workspace_root = Path("./workspace")
set_config(config)

from markscientist.agents import ChallengerAgent, JudgeAgent, SolverAgent
from markscientist.workflow import ResearchWorkflow

challenger = ChallengerAgent(config=config, workspace_root=config.workspace_root)
challenger.run("Prepare a research project for the current prompt.", workspace_root=config.workspace_root)

solver = SolverAgent(config=config, workspace_root=config.workspace_root)
solver_result = solver.run("Execute the prepared project.", workspace_root=config.workspace_root)

judge = JudgeAgent(config=config, workspace_root=config.workspace_root)
judge_result = judge.run("Review the current report strictly.", workspace_root=config.workspace_root)

workflow = ResearchWorkflow(config=config)
workflow_result = workflow.run("Write a research report", workspace_root=config.workspace_root)
print(workflow_result.final_score)
print(workflow_result.metadata["report_path"])
```

## 📋 Commands

```
/help        Show commands       /workflow    Full workflow
/challenger  Challenger mode     /solver      Solver mode
/judge       Judge mode          /model       Switch model
/config      Show config         /clear       New session
/exit        Exit
```

## ⚙️ Config

```bash
# .env
API_KEY=your-key
API_BASE=https://your-openai-compatible-endpoint/v1
MODEL_NAME=gpt-5.4
```

Agent runtime defaults and trajectory defaults live in code. Override them programmatically on `Config(...)` when needed.

If you need a non-default workspace root or `ResearchHarness` checkout, set `config.workspace_root` or `config.harness_path` before creating agents.

## 🧪 Testing

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider tests/test_agents.py tests/test_workflow.py tests/test_cli.py
```

The test suite checks:

- role agents inheriting the ResearchHarness base agent
- the Challenger -> Solver -> Judge workflow loop
- CLI JSON output and single-agent entry points

## 🪪 License

This project is released under the [MIT License](LICENSE).
