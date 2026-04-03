from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    workspace_root: Path
    challenge_dir: Path
    code_dir: Path
    outputs_dir: Path
    report_dir: Path
    report_images_dir: Path
    instructions_path: Path
    challenge_brief_path: Path
    checklist_path: Path
    report_path: Path


def resolve_project_paths(workspace_root: Path | str) -> ProjectPaths:
    root = Path(workspace_root).expanduser().resolve()
    challenge_dir = root / "challenge"
    report_dir = root / "report"
    return ProjectPaths(
        workspace_root=root,
        challenge_dir=challenge_dir,
        code_dir=root / "code",
        outputs_dir=root / "outputs",
        report_dir=report_dir,
        report_images_dir=report_dir / "images",
        instructions_path=root / "INSTRUCTIONS.md",
        challenge_brief_path=challenge_dir / "brief.md",
        checklist_path=challenge_dir / "checklist.json",
        report_path=report_dir / "report.md",
    )


def ensure_project_layout(workspace_root: Path | str) -> ProjectPaths:
    paths = resolve_project_paths(workspace_root)
    paths.workspace_root.mkdir(parents=True, exist_ok=True)
    paths.challenge_dir.mkdir(parents=True, exist_ok=True)
    paths.code_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    paths.report_images_dir.mkdir(parents=True, exist_ok=True)
    (paths.workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (paths.workspace_root / "related_work").mkdir(parents=True, exist_ok=True)
    return paths


def read_text_if_exists(path: Path, *, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8").strip()


def load_checklist_text(path: Path) -> str:
    if not path.exists():
        return "[]"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path.read_text(encoding="utf-8").strip()
    return json.dumps(payload, ensure_ascii=False, indent=2)
