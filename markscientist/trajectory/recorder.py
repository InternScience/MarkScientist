from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from markscientist.trajectory.schema import WorkflowTraceRecord


class WorkflowTrajectoryRecorder:
    """Secondary workflow-level wrapper around per-agent ResearchHarness traces."""

    def __init__(
        self,
        *,
        task: str,
        model_name: str,
        workspace_root: str,
        save_dir: Optional[Path] = None,
    ):
        self.record = WorkflowTraceRecord(
            task=task,
            workspace_root=str(workspace_root),
            model_name=model_name,
        )
        self.save_dir = Path(save_dir) if save_dir else None

    def trace_path_for(self, agent_type: str) -> Optional[Path]:
        if self.save_dir is None:
            return None
        return self.save_dir / f"{self.record.workflow_id}_{agent_type}.jsonl"

    def capture_agent_result(self, agent_type: str, result) -> None:
        metadata = dict(getattr(result, "metadata", {}) or {})
        trace_path = metadata.get("trace_path", "")
        self.record.set_agent_trace(
            agent_type=agent_type,
            trace_path=str(trace_path or ""),
            termination=str(getattr(result, "termination_reason", "")),
            output=str(getattr(result, "output", "")),
            metadata=metadata,
        )

    def complete(
        self,
        *,
        final_output: str,
        success: bool,
        iterations: int,
        quality_scores: Optional[Dict[str, float]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> WorkflowTraceRecord:
        self.record.complete(
            final_output=final_output,
            success=success,
            iterations=iterations,
            quality_scores=quality_scores,
            metadata=metadata,
        )
        if self.save_dir is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            path = self.save_dir / f"{self.record.workflow_id}_workflow.json"
            path.write_text(json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return self.record

    def get_record(self) -> WorkflowTraceRecord:
        return self.record
