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

- Solver / Judge / Evaluator role definitions
- role-specific prompt addenda
- workflow orchestration
- improvement loops
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
- Judge and Evaluator are tool-free agents built on the same lower-layer base class
- workflow trace files now wrap per-agent ResearchHarness traces instead of redefining the full flat-trace format
