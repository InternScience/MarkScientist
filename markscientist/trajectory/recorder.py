from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from markscientist.trajectory.schema import WorkflowTraceRecord


class WorkflowTrajectoryRecorder:
    """Secondary workflow-level wrapper around per-agent ResearchHarness traces."""

    def __init__(
        self,
        *,
        prompt: str,
        model_name: str,
        workspace_root: str,
        save_dir: Optional[Path] = None,
    ):
        self.record = WorkflowTraceRecord(
            prompt=prompt,
            workspace_root=str(workspace_root),
            model_name=model_name,
        )
        self.save_dir = Path(save_dir) if save_dir else None

    def trace_dir_for(self, agent_type: str) -> Optional[Path]:
        if self.save_dir is None:
            return None
        return self.save_dir / self.record.workflow_id / agent_type

    def capture_agent_result(self, agent_type: str, result) -> None:
        trace_path = str(getattr(result, "trace_path", "") or "")
        self.record.set_agent_trace(
            agent_type=agent_type,
            trace_path=trace_path,
            termination=str(getattr(result, "termination_reason", "")),
            output=str(getattr(result, "output", "")),
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
            workflow_dir = self.save_dir / self.record.workflow_id
            workflow_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            path = workflow_dir / f"workflow_{timestamp}_{self.record.workflow_id[:12]}.json"
            path.write_text(json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return self.record
