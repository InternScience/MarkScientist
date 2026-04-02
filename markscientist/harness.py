from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_harness_root() -> Path:
    return project_root() / "vendor" / "ResearchHarness"


def fallback_harness_root() -> Path:
    return project_root().parent / "ResearchHarness"


def resolve_harness_root(configured_path: Optional[str | Path] = None) -> Path:
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser().resolve())
    candidates.append(default_harness_root().resolve())
    candidates.append(fallback_harness_root().resolve())
    for candidate in candidates:
        if (candidate / "agent_base").exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate ResearchHarness. Expected a git submodule at "
        f"{default_harness_root()} or a sibling checkout at {fallback_harness_root()}."
    )


def ensure_harness_on_path(configured_path: Optional[str | Path] = None) -> Path:
    root = resolve_harness_root(configured_path)
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
