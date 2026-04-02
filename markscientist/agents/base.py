from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from markscientist.config import Config, get_config
from markscientist.harness import ensure_harness_on_path

ensure_harness_on_path(get_config().harness_path)

from agent_base.react_agent import MultiTurnReactAgent


@dataclass
class AgentResult:
    output: str
    success: bool
    termination_reason: str = "completed"
    session: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "success": self.success,
            "termination_reason": self.termination_reason,
            "metadata": self.metadata,
        }


class BaseScientistAgent(MultiTurnReactAgent):
    """MarkScientist base agent built on top of ResearchHarness."""

    agent_type: str = "agent"

    def __init__(
        self,
        *,
        config: Optional[Config] = None,
        role_prompt: Optional[str] = None,
        function_list: Optional[Sequence[str]] = None,
        trace_path: Optional[Path | str] = None,
        workspace_root: Optional[Path | str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = config or get_config()
        self.harness_root = ensure_harness_on_path(self.config.harness_path)
        self.default_workspace_root = Path(workspace_root) if workspace_root else self.config.workspace_root
        self.on_event = on_event
        super().__init__(
            function_list=self.resolve_function_list(function_list),
            llm=self._build_llm_config(self.config),
            trace_path=str(trace_path) if trace_path else None,
            role_prompt=role_prompt,
            max_llm_calls=self.config.agent.max_llm_calls,
            max_runtime_seconds=self.config.agent.max_runtime_seconds,
        )

    @staticmethod
    def _build_llm_config(config: Config) -> Dict[str, Any]:
        return {
            "model": config.model.model_name,
            "api_key": config.model.api_key,
            "api_base": config.model.api_base,
            "generate_cfg": {
                "max_input_tokens": config.agent.max_input_tokens,
                "max_output_tokens": config.agent.max_output_tokens,
                "max_retries": config.agent.max_retries,
                "temperature": config.agent.temperature,
                "top_p": config.agent.top_p,
                "presence_penalty": config.agent.presence_penalty,
            },
        }

    def build_task_input(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        parts = [task.strip()]
        if context:
            parts.insert(0, "Context:\n" + json.dumps(context, ensure_ascii=False, indent=2))
        return "\n\n".join(part for part in parts if part.strip())

    def run(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        workspace_dir: Optional[Path | str] = None,
    ) -> AgentResult:
        task_input = self.build_task_input(task, context)
        workspace_root = workspace_dir or self.default_workspace_root
        session = self._run_session(
            task_input,
            workspace_dir=str(workspace_root) if workspace_root else None,
            event_callback=self.on_event,
        )
        termination = str(session.get("termination", ""))
        return AgentResult(
            output=str(session.get("result_text", "")),
            success=termination == "result",
            termination_reason=termination,
            session=session,
            metadata={
                "agent_type": self.agent_type,
                "harness_root": str(self.harness_root),
                "workspace_root": str(workspace_root) if workspace_root else None,
                "trace_path": str(self.trace_path) if self.trace_path else None,
            },
        )
