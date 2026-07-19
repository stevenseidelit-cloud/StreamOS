#!/usr/bin/env python3
"""Validate multi-agent task reservations using only the Python stdlib."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
AGENT_RE = TASK_ID_RE
ACTIVE_STATUSES = {"in_progress", "blocked", "review"}
ALL_STATUSES = {"queued", *ACTIVE_STATUSES, "done", "cancelled"}
ALLOWED_FIELDS = {
    "task_id",
    "title",
    "agent",
    "branch",
    "status",
    "issue",
    "pull_request",
    "exclusive_paths",
    "updated_at",
    "handoff",
}
REQUIRED_FIELDS = {"task_id", "title", "agent", "branch", "status", "exclusive_paths"}
FORBIDDEN_PATH_CHARS = set("*?[]{}!\\\0")


class DuplicateKeyError(ValueError):
    pass


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class Reservation:
    file: Path
    task_id: str
    agent: str
    branch: str
    status: str
    paths: tuple[str, ...]


def normalize_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("exclusive path must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise ValueError(f"path is not NFC-normalized: {value!r}")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"path must be repository-relative: {value!r}")
    if value == "." or "//" in value or any(char in value for char in FORBIDDEN_PATH_CHARS):
        raise ValueError(f"path contains forbidden syntax: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"path contains an unsafe segment: {value!r}")
    if parts[0].casefold() == ".git":
        raise ValueError("the .git directory cannot be reserved")
    return value.rstrip("/")


def validate_branch(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("branch must be a non-empty string")
    if not value.startswith("agent/"):
        raise ValueError("branch must start with 'agent/'")
    if value.startswith("/") or value.endswith("/") or "//" in value:
        raise ValueError("branch contains an invalid slash sequence")
    if ".." in value or "@{" in value or "\\" in value or any(c.isspace() for c in value):
        raise ValueError("branch contains forbidden syntax")
    return value


def paths_overlap(left: str, right: str) -> bool:
    left_key = unicodedata.normalize("NFC", left).casefold()
    right_key = unicodedata.normalize("NFC", right).casefold()
    return (
        left_key == right_key
        or left_key.startswith(right_key + "/")
        or right_key.startswith(left_key + "/")
    )


def load_task(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        if path.stat().st_size > 65536:
            return None, ["task file exceeds 64 KiB"]
        with path.open("r", encoding="utf-8") as handle:
            task = json.load(handle, object_pairs_hook=no_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        return None, [f"cannot read valid JSON: {exc}"]

    if not isinstance(task, dict):
        return None, ["task root must be a JSON object"]
    missing = REQUIRED_FIELDS - task.keys()
    unknown = task.keys() - ALLOWED_FIELDS
    if missing:
        errors.append(f"missing fields: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"unknown fields: {', '.join(sorted(unknown))}")

    task_id = task.get("task_id")
    agent = task.get("agent")
    status = task.get("status")
    title = task.get("title")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        errors.append("task_id must match ^[a-z0-9][a-z0-9._-]{0,63}$")
    if not isinstance(agent, str) or not AGENT_RE.fullmatch(agent):
        errors.append("agent must match ^[a-z0-9][a-z0-9._-]{0,63}$")
    if status not in ALL_STATUSES:
        errors.append(f"invalid status: {status!r}")
    if not isinstance(title, str) or not title.strip():
        errors.append("title must be a non-empty string")
    try:
        validate_branch(task.get("branch"))
    except ValueError as exc:
        errors.append(str(exc))

    raw_paths = task.get("exclusive_paths")
    normalized_paths: list[str] = []
    if not isinstance(raw_paths, list) or not raw_paths or len(raw_paths) > 100:
        errors.append("exclusive_paths must contain 1 to 100 paths")
    else:
        for raw_path in raw_paths:
            try:
                normalized_paths.append(normalize_path(raw_path))
            except ValueError as exc:
                errors.append(str(exc))
        keys = [path.casefold() for path in normalized_paths]
        if len(keys) != len(set(keys)):
            errors.append("exclusive_paths contains duplicate paths")

    for field in ("issue", "pull_request"):
        value = task.get(field)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            errors.append(f"{field} must be a positive integer or null")
    if "handoff" in task and not isinstance(task["handoff"], dict):
        errors.append("handoff must be an object")
    return task, errors


def validate_directory(tasks_dir: Path) -> list[str]:
    errors: list[str] = []
    reservations: list[Reservation] = []
    seen_ids: dict[str, Path] = {}
    seen_active_branches: dict[str, Path] = {}

    for path in sorted(tasks_dir.glob("*.json")):
        task, task_errors = load_task(path)
        errors.extend(f"{path}: {message}" for message in task_errors)
        if task is None or task_errors:
            continue
        task_id = task["task_id"]
        if task_id in seen_ids:
            errors.append(f"{path}: duplicate task_id also used by {seen_ids[task_id]}")
        else:
            seen_ids[task_id] = path
        if task["status"] in ACTIVE_STATUSES:
            branch_key = task["branch"].casefold()
            if branch_key in seen_active_branches:
                errors.append(f"{path}: active branch also used by {seen_active_branches[branch_key]}")
            else:
                seen_active_branches[branch_key] = path
            reservations.append(
                Reservation(
                    file=path,
                    task_id=task_id,
                    agent=task["agent"],
                    branch=task["branch"],
                    status=task["status"],
                    paths=tuple(normalize_path(item) for item in task["exclusive_paths"]),
                )
            )

    for index, left in enumerate(reservations):
        for right in reservations[index + 1 :]:
            for left_path in left.paths:
                for right_path in right.paths:
                    if paths_overlap(left_path, right_path):
                        errors.append(
                            f"{right.file}: path {right_path!r} conflicts with "
                            f"task {left.task_id!r} path {left_path!r} in {left.file}"
                        )
    return errors


def find_branch_task(
    tasks_dir: Path, branch: str, *, allow_missing: bool = False
) -> tuple[Reservation | None, list[str]]:
    matches: list[Reservation] = []
    errors: list[str] = []
    for path in sorted(tasks_dir.glob("*.json")):
        task, task_errors = load_task(path)
        errors.extend(f"{path}: {message}" for message in task_errors)
        if task is None or task_errors:
            continue
        if task["branch"].casefold() == branch.casefold():
            matches.append(
                Reservation(
                    file=path,
                    task_id=task["task_id"],
                    agent=task["agent"],
                    branch=task["branch"],
                    status=task["status"],
                    paths=tuple(normalize_path(item) for item in task["exclusive_paths"]),
                )
            )
    if not matches and allow_missing:
        return None, errors
    if len(matches) != 1:
        errors.append(
            f"branch {branch!r} must have exactly one task; found {len(matches)}"
        )
        return None, errors
    return matches[0], errors


def validate_changed_files(
    tasks_dir: Path,
    branch: str,
    changed_files: Path,
    base_tasks_dir: Path | None = None,
) -> list[str]:
    reservation, errors = find_branch_task(tasks_dir, branch)
    if reservation is None:
        return errors
    try:
        raw_files = changed_files.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [f"cannot read changed-files list: {exc}"]

    own_task_file = reservation.file.as_posix()
    try:
        own_task_file = reservation.file.relative_to(Path.cwd()).as_posix()
    except ValueError:
        pass

    normalized_changed: list[str] = []
    for raw_path in raw_files:
        raw_path = raw_path.lstrip("\ufeff")
        if not raw_path:
            continue
        try:
            changed_path = normalize_path(raw_path)
        except ValueError as exc:
            errors.append(f"changed path {raw_path!r} is invalid: {exc}")
            continue
        normalized_changed.append(changed_path)

    base_reservation: Reservation | None = None
    if base_tasks_dir is not None:
        base_reservation, base_errors = find_branch_task(
            base_tasks_dir, branch, allow_missing=True
        )
        if base_reservation is None:
            non_task_changes = [
                path for path in normalized_changed if path.casefold() != own_task_file.casefold()
            ]
            if non_task_changes:
                errors.append(
                    "a new reservation must be merged before implementation files are changed"
                )
        else:
            if (
                reservation.task_id != base_reservation.task_id
                or reservation.agent != base_reservation.agent
                or reservation.branch != base_reservation.branch
                or tuple(path.casefold() for path in reservation.paths)
                != tuple(path.casefold() for path in base_reservation.paths)
            ):
                errors.append(
                    "task_id, agent, branch, and exclusive_paths cannot change after reservation merge"
                )
        errors.extend(base_errors)

    for changed_path in normalized_changed:
        if changed_path.startswith(".coordination/tasks/"):
            if changed_path == ".coordination/tasks/.gitkeep":
                continue
            if changed_path.casefold() != own_task_file.casefold():
                errors.append(
                    f"branch {branch!r} may only change its own task file "
                    f"{own_task_file!r}, not {changed_path!r}"
                )
            continue
        if reservation.status not in ACTIVE_STATUSES:
            errors.append(
                f"task {reservation.task_id!r} with status {reservation.status!r} "
                "may only change its own task file"
            )
            continue
        if not any(
            changed_path.casefold() == prefix.casefold()
            or changed_path.casefold().startswith(prefix.casefold() + "/")
            for prefix in reservation.paths
        ):
            errors.append(
                f"changed file {changed_path!r} is outside task "
                f"{reservation.task_id!r} exclusive_paths"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "tasks_dir",
        nargs="?",
        type=Path,
        default=Path(".coordination/tasks"),
    )
    parser.add_argument("--branch")
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--base-tasks-dir", type=Path)
    args = parser.parse_args(argv)
    errors = validate_directory(args.tasks_dir)
    if bool(args.branch) != bool(args.changed_files):
        errors.append("--branch and --changed-files must be supplied together")
    elif args.branch and args.changed_files:
        errors.extend(
            validate_changed_files(
                args.tasks_dir,
                args.branch,
                args.changed_files,
                args.base_tasks_dir,
            )
        )
    if errors:
        for error in errors:
            print(f"::error::{error}")
        print(f"coordination validation failed with {len(errors)} error(s)")
        return 1
    print("coordination validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
