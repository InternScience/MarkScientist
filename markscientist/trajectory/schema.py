from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4


def _preview(text: str, limit: int = 500) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


@dataclass
class AgentTraceRef:
    agent_type: str
    trace_path: str = ""
    termination: str = ""
    output_preview: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowTraceRecord:
    workflow_id: str = field(default_factory=lambda: uuid4().hex)
    version: str = "0.2"
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    completed_at: Optional[str] = None
    task: str = ""
    workspace_root: str = ""
    model_name: str = ""
    solver: Optional[AgentTraceRef] = None
    judge: Optional[AgentTraceRef] = None
    evaluator: Optional[AgentTraceRef] = None
    final_output_preview: str = ""
    quality_scores: Dict[str, float] = field(default_factory=dict)
    success: bool = False
    iterations: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def set_agent_trace(
        self,
        *,
        agent_type: str,
        trace_path: str = "",
        termination: str = "",
        output: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ref = AgentTraceRef(
            agent_type=agent_type,
            trace_path=trace_path,
            termination=termination,
            output_preview=_preview(output),
            metadata=metadata or {},
        )
        setattr(self, agent_type, ref)

    def complete(
        self,
        *,
        final_output: str,
        success: bool,
        iterations: int,
        quality_scores: Optional[Dict[str, float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.final_output_preview = _preview(final_output)
        self.success = success
        self.iterations = iterations
        self.quality_scores = quality_scores or {}
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data
