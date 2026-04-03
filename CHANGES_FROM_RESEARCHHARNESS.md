# MarkScientist and ResearchHarness Boundary

This document describes the current relationship between the two repositories.

## ResearchHarness Owns

- OpenAI-compatible SDK calls
- native tool calling
- the ReAct execution loop
- tool registration and execution
- flat per-agent JSONL traces
- the base system prompt for lower-layer execution behavior

## MarkScientist Owns

- Challenger / Solver / Judge role definitions
- role-specific prompt addenda
- research-project preparation
- workflow orchestration
- solver/judge improvement loops
- workflow-level trace summaries
- higher-level tests for multi-agent coordination

## Implementation Rule

`MarkScientist` must not reimplement the lower-layer `agent_base` stack from `ResearchHarness`.

Instead:

- import `ResearchHarness` through a git submodule
- subclass the ResearchHarness agent base
- pass role-specific prompt blocks into the lower-layer agent
- use ResearchHarness traces directly, or wrap them with a higher-level workflow record

## Current Refactor Notes

- `MarkScientist` no longer maintains its own model-backend abstraction layer
- all agent execution flows go through ResearchHarness
- Challenger, Solver, and Judge all subclass the same lower-layer ResearchHarness base agent
- Challenger prepares `INSTRUCTIONS.md`, `challenge/brief.md`, and `challenge/checklist.json`
- Solver is responsible for producing `report/report.md`
- Judge reviews the report against the prepared checklist and returns JSON scoring feedback
- workflow trace files now wrap per-agent ResearchHarness traces instead of redefining the full flat-trace format
