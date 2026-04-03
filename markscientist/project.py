from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    public_root: Path
    judge_dir: Path
    challenge_dir: Path
    code_dir: Path
    outputs_dir: Path
    report_dir: Path
    report_images_dir: Path
    instructions_path: Path
    challenge_brief_path: Path
    checklist_path: Path
    report_path: Path
    judge_notes_path: Path
    judge_checklist_path: Path
    judge_feedback_path: Path


def resolve_project_paths(project_root: Path | str) -> ProjectPaths:
    root = Path(project_root).expanduser().resolve()
    public_root = root / "public"
    judge_dir = root / "judge"
    challenge_dir = public_root / "challenge"
    report_dir = public_root / "report"
    return ProjectPaths(
        project_root=root,
        public_root=public_root,
        judge_dir=judge_dir,
        challenge_dir=challenge_dir,
        code_dir=public_root / "code",
        outputs_dir=public_root / "outputs",
        report_dir=report_dir,
        report_images_dir=report_dir / "images",
        instructions_path=public_root / "INSTRUCTIONS.md",
        challenge_brief_path=challenge_dir / "brief.md",
        checklist_path=challenge_dir / "checklist.json",
        report_path=report_dir / "report.md",
        judge_notes_path=judge_dir / "notes.md",
        judge_checklist_path=judge_dir / "checklist.json",
        judge_feedback_path=judge_dir / "feedback_history.jsonl",
    )


def ensure_project_layout(project_root: Path | str) -> ProjectPaths:
    paths = resolve_project_paths(project_root)
    paths.project_root.mkdir(parents=True, exist_ok=True)
    paths.public_root.mkdir(parents=True, exist_ok=True)
    paths.judge_dir.mkdir(parents=True, exist_ok=True)
    paths.challenge_dir.mkdir(parents=True, exist_ok=True)
    paths.code_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    paths.report_images_dir.mkdir(parents=True, exist_ok=True)
    (paths.public_root / "data").mkdir(parents=True, exist_ok=True)
    (paths.public_root / "related_work").mkdir(parents=True, exist_ok=True)
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


def _format_workspace_listing(root: Path, subdir: str) -> str:
    base = root / subdir
    if not base.exists():
        return f"- `{subdir}/` is missing."
    file_paths = sorted(path for path in base.rglob("*") if path.is_file())
    if not file_paths:
        return f"- `{subdir}/` exists but contains no files."
    lines: list[str] = []
    for path in file_paths[:50]:
        rel_path = path.relative_to(root).as_posix()
        size_bytes = path.stat().st_size
        if size_bytes < 1024:
            size_text = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_text = f"{size_bytes / 1024:.1f} KB"
        else:
            size_text = f"{size_bytes / (1024 * 1024):.1f} MB"
        lines.append(f"- `{rel_path}` ({size_text})")
    if len(file_paths) > 50:
        lines.append(f"- ... and {len(file_paths) - 50} more files under `{subdir}/`.")
    return "\n".join(lines)


def describe_workspace_inputs(workspace_root: Path | str) -> dict[str, str]:
    root = Path(workspace_root).expanduser().resolve()
    return {
        "data_inventory": _format_workspace_listing(root, "data"),
        "related_work_inventory": _format_workspace_listing(root, "related_work"),
    }


def load_judge_materials_text(paths: ProjectPaths) -> str:
    blocks: list[str] = []
    if paths.judge_notes_path.exists():
        blocks.append("## Judge Notes\n" + paths.judge_notes_path.read_text(encoding="utf-8").strip())
    if paths.judge_checklist_path.exists():
        blocks.append("## Judge Checklist\n" + load_checklist_text(paths.judge_checklist_path))
    return "\n\n".join(block for block in blocks if block.strip())


def missing_public_contract_files(paths: ProjectPaths) -> list[str]:
    required = [
        paths.instructions_path,
        paths.challenge_brief_path,
        paths.checklist_path,
    ]
    missing: list[str] = []
    for path in required:
        if not path.exists():
            missing.append(path.relative_to(paths.public_root).as_posix())
            continue
        if not path.read_text(encoding="utf-8").strip():
            missing.append(path.relative_to(paths.public_root).as_posix())
    return missing


def snapshot_solver_owned_files(paths: ProjectPaths) -> Dict[str, Tuple[int, int]]:
    snapshot: Dict[str, Tuple[int, int]] = {}

    def _record_tree(root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel_path = path.relative_to(paths.public_root).as_posix()
                stat = path.stat()
                snapshot[rel_path] = (stat.st_mtime_ns, stat.st_size)

    _record_tree(paths.code_dir)
    _record_tree(paths.outputs_dir)
    _record_tree(paths.report_images_dir)
    if paths.report_path.exists():
        stat = paths.report_path.stat()
        snapshot[paths.report_path.relative_to(paths.public_root).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def detect_solver_owned_file_changes(
    before: Dict[str, Tuple[int, int]],
    after: Dict[str, Tuple[int, int]],
) -> list[str]:
    changed: set[str] = set()
    for rel_path, fingerprint in after.items():
        if before.get(rel_path) != fingerprint:
            changed.add(rel_path)
    for rel_path in before:
        if rel_path not in after:
            changed.add(rel_path)
    return sorted(changed)
