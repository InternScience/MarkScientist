<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="version">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license">
</p>

<h1 align="center">🔬 MarkScientist</h1>

<p align="center">
  <b>Self-evolving Research Agent with Built-in Scientific Taste</b>
</p>

<p align="center">
  <code>Solver</code> executes → <code>Judge</code> reviews → <code>Evaluator</code> improves
</p>

---

## ✨ Features

- **🧱 Built on ResearchHarness** — ResearchHarness owns SDK calls, tool calling, and the ReAct loop; MarkScientist owns multi-agent roles and workflow orchestration
- **🤖 Three-Agent System** — Solver, Judge, Evaluator working together
- **🎯 Auto-Review** — Judge automatically scores Solver's output
- **🐾 Reviewer Buddies** — Fun ASCII characters for different task types
- **📊 8 Task Types** — Each with appropriate scoring dimensions
- **💾 Workflow-Level Traces** — Preserve per-agent ResearchHarness traces and a higher-level workflow summary

## 🚀 Quick Start

```bash
git submodule update --init --recursive
pip install -e .
markscientist
```

## 🧠 How It Works

`MarkScientist` is not a second execution harness. It is a higher-layer framework built on top of `ResearchHarness`.

```mermaid
flowchart TD
    U[User Task] --> MS[MarkScientist Workflow Layer]
    MS --> S[Solver Agent]
    MS --> J[Judge Agent]
    MS --> E[Evaluator Agent]
    S --> RH[ResearchHarness Execution Layer]
    J --> RH
    E --> RH
    RH --> P[Base System Prompt]
    RH --> R[ReAct Loop]
    RH --> T[Native Tool Calling]
    RH --> X[Per-Agent Flat Traces]
    MS --> W[Workflow Scheduling]
    MS --> A[Role-Specific Prompt Addenda]
    MS --> Y[Workflow-Level Trace Summary]
```

The internal `MarkScientist` design is intentionally layered:

```mermaid
flowchart TD
    subgraph MS[MarkScientist]
        CLI[CLI / Entry Points] --> WF[Workflow]
        WF --> AG[Role Agents]
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

## 🧭 Architecture Boundary

- `ResearchHarness` is the execution layer:
  - OpenAI-compatible SDK calls
  - native tool calling
  - ReAct loop
  - tool registry and execution
  - flat per-agent trace writing
- `MarkScientist` is the orchestration layer:
  - Solver / Judge / Evaluator agent roles
  - workflow scheduling and improvement loops
  - role-specific prompt addenda
  - workflow-level trajectory summaries

`MarkScientist` agents inherit the ResearchHarness agent base instead of reimplementing the lower-layer execution stack.

## 💬 Usage

### Interactive REPL

```bash
markscientist          # Start REPL (Solver + auto Judge review)
```

### 1. Solver Mode (Default, with Auto-Review)

```
[solver+judge] > What is the transformer architecture?

╭──────────────── Solver Output ────────────────╮
│ The Transformer was proposed in "Attention   │
│ Is All You Need" by Vaswani et al. in 2017...│
╰──────────────────────────────────────────────╯

((•)(•)) =•ω•= [•=•] /• •\ Summoning reviewer...

[•=•] EVAL-9000 appears! "Computing evaluation scores..."

╭─────────── The Objective Analyzer ───────────╮
│  Reaction   ✓ Excellent!                     │
│  Type       factual_query                    │
│  Score      8.5/10                           │
╰──────────────────────────────────────────────╯
```

### 2. Judge Mode (Review Artifacts)

```
[solver+judge] > /judge

[judge] > Review this code:
def fib(n): return fib(n-1)+fib(n-2) if n>1 else n

╭──────────────── Judge Review ─────────────────╮
│  Type       code_analysis                     │
│  Score      5.5/10                            │
│  Details    correctness: 7.0 | efficiency: 3.0│
│  Issues     No memoization; O(2^n) complexity │
╰───────────────────────────────────────────────╯
```

### 3. Evaluator Mode (Meta-Evaluation)

Evaluates the performance of Solver and Judge themselves.

```
[judge] > /evaluator

[evaluator] > Evaluate the system's performance on the last task

╭────────────── Meta Evaluation ────────────────╮
│  Solver Assessment                            │
│    task_completion: 0.85                      │
│    efficiency: 0.70                           │
│    reasoning_quality: 0.80                    │
│                                               │
│  Judge Assessment                             │
│    scoring_accuracy: 0.90                     │
│    issue_coverage: 0.75                       │
│    suggestion_actionability: 0.80             │
│                                               │
│  System Insights                              │
│    bottleneck: Solver lacks systematic testing│
│    suggestion: Add auto test case generation  │
│                                               │
│  Success Probability: 0.78                    │
╰───────────────────────────────────────────────╯
```

### 4. Workflow Mode (Full Pipeline)

Runs Solver → Judge → Auto-Improve loop until score >= 6.0

```
[solver+judge] > /workflow Write a literature review on RL for robotics

⠋ Running workflow...

╭──────────────── Final Output ─────────────────╮
│ # Literature Review: RL for Robotics          │
│ ## 1. Introduction ...                        │
│ ## 2. Key Methods ...                         │
╰───────────────────────────────────────────────╯

╭─────────── Workflow Complete ─────────────────╮
│  Status      Success                          │
│  Final Score 7.8/10                           │
│  Iterations  2                                │
│  Verdict     ACCEPT                           │
╰───────────────────────────────────────────────╯
```

### CLI One-Shot Commands

```bash
# Solver + Judge (default)
markscientist "Explain quicksort algorithm"

# Solver only (no auto-review)
markscientist "Explain quicksort" --no-review

# Judge only
markscientist "Review this code..." --agent judge

# Evaluator only
markscientist "Assess system performance" --agent evaluator

# Full workflow with improvement loop
markscientist "Write a research proposal" --workflow

# JSON output
markscientist "Analyze this data" --json
```

### Python API

```python
from pathlib import Path

from markscientist.agents import EvaluatorAgent, JudgeAgent, SolverAgent
from markscientist.config import Config

config = Config.from_env()
config.workspace_root = Path("./workspace")

solver = SolverAgent(config=config)
result = solver.run("Implement binary search")
print(result.output)

judge = JudgeAgent(config=config)
review = judge.review(artifact=result.output, artifact_type="code_analysis")
print(f"Score: {review.overall_score}/10")
print(f"Issues: {review.weaknesses}")

evaluator = EvaluatorAgent(config=config)
meta = evaluator.evaluate(
    original_task="Implement binary search",
    solver_output=result.output,
    judge_review=review.raw_output,
)
print(f"Success Probability: {meta.success_probability}")
print(f"System Insights: {meta.system_insights}")
```

## 🐾 Reviewer Buddies

| Buddy | Name | Focus |
|:-----:|------|-------|
| `((•)(•))` | Professor Owl | Methodology |
| `=•ω•=` | Dr. Whiskers | Details |
| `[•=•]` | EVAL-9000 | Metrics |
| `<•~•>` | Elder Dragon | Big Picture |
| `/• •\` | The Specter | Hidden Issues |
| `~(••)~` | Dr. Tentacle | Multi-angle |

## 📋 Commands

```
/help       Show commands        /workflow   Full pipeline
/solver     Solver mode          /review     Toggle auto-review
/judge      Judge mode           /model      Switch model
/evaluator  Evaluator mode       /clear      New session
```

## 🎯 Task Types

| Type | Scoring Dimensions |
|------|-------------------|
| `factual_query` | accuracy, completeness, clarity |
| `idea_proposal` | novelty, rigor, feasibility |
| `code_analysis` | correctness, depth, clarity |
| `literature_review` | coverage, synthesis, organization |
| `experiment_design` | methodology, validity, reproducibility |
| `writing_draft` | structure, clarity, coherence |
| `data_analysis` | accuracy, interpretation, visualization |
| `problem_solving` | correctness, efficiency, explanation |

## ⚙️ Config

```bash
# .env
API_KEY=your-key
API_BASE=https://your-openai-compatible-endpoint/v1
MODEL_NAME=gpt-5.4
RESEARCHHARNESS_PATH=./vendor/ResearchHarness
```

## 🗺️ Roadmap

- [x] v0.1 — Three agents, multi-type Judge, Buddies
- [ ] v0.2 — Enhanced data collection
- [ ] v0.3 — Workflow optimization
- [ ] v1.0 — Stronger workflow policies, richer evaluation, better high-level testing

## 📄 License

MIT
