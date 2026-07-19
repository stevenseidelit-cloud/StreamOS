import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_coordination import (
    normalize_path,
    paths_overlap,
    validate_changed_files,
    validate_directory,
)


def task(task_id, path, *, status="in_progress", agent=None, branch=None):
    return {
        "task_id": task_id,
        "title": task_id,
        "agent": agent or f"agent-{task_id}",
        "branch": branch or f"agent/{task_id}",
        "status": status,
        "issue": None,
        "pull_request": None,
        "exclusive_paths": [path],
    }


class CoordinationValidatorTests(unittest.TestCase):
    def validate(self, *tasks):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, value in enumerate(tasks):
                (root / f"task-{index}.json").write_text(json.dumps(value), encoding="utf-8")
            return validate_directory(root)

    def test_disjoint_paths_are_valid(self):
        self.assertEqual([], self.validate(task("one", "src/auth"), task("two", "ui")))

    def test_equal_paths_conflict_case_insensitively(self):
        errors = self.validate(task("one", "Src/UI"), task("two", "src/ui"))
        self.assertTrue(any("conflicts" in error for error in errors))

    def test_parent_child_paths_conflict(self):
        errors = self.validate(task("one", "src"), task("two", "src/auth.py"))
        self.assertTrue(any("conflicts" in error for error in errors))

    def test_sibling_prefixes_do_not_conflict(self):
        self.assertFalse(paths_overlap("src/api", "src/api-v2"))

    def test_completed_task_releases_path(self):
        self.assertEqual(
            [],
            self.validate(task("one", "src", status="done"), task("two", "src/auth.py")),
        )

    def test_blocked_task_keeps_path(self):
        errors = self.validate(task("one", "src", status="blocked"), task("two", "src/auth.py"))
        self.assertTrue(any("conflicts" in error for error in errors))

    def test_duplicate_active_branch_is_rejected(self):
        errors = self.validate(
            task("one", "src", branch="agent/shared"),
            task("two", "ui", branch="agent/shared"),
        )
        self.assertTrue(any("active branch" in error for error in errors))

    def test_unsafe_paths_are_rejected(self):
        for value in ("../secret", "a/../b", "/etc", "C:/temp", "a\\b", "a//b", "."):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_path(value)

    def test_malformed_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.json").write_text("{broken", encoding="utf-8")
            self.assertTrue(validate_directory(root))

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "duplicate.json").write_text(
                '{"task_id":"one","task_id":"two"}', encoding="utf-8"
            )
            self.assertTrue(validate_directory(root))

    def test_changed_files_must_be_inside_branch_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            current = task("one", "src/auth", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text("src/auth/login.py\nui/app.js\n", encoding="utf-8")
            errors = validate_changed_files(tasks, "agent/one", changed)
            self.assertEqual(1, sum("outside task" in error for error in errors))

    def test_branch_may_only_change_own_task_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text(".coordination/tasks/two.json\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                errors = validate_changed_files(tasks, "agent/one", changed)
            finally:
                os.chdir(old_cwd)
            self.assertTrue(any("own task file" in error for error in errors))

    def test_branch_can_change_own_task_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text(".coordination/tasks/one.json\nsrc/main.py\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                errors = validate_changed_files(tasks, "agent/one", changed)
            finally:
                os.chdir(old_cwd)
            self.assertEqual([], errors)

    def test_gitkeep_and_utf8_bom_are_harmless(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            current = task("one", ".coordination", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text(
                "\ufeff.coordination/README.md\n.coordination/tasks/.gitkeep\n",
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                errors = validate_changed_files(tasks, "agent/one", changed)
            finally:
                os.chdir(old_cwd)
            self.assertEqual([], errors)

    def test_new_reservation_pr_cannot_include_implementation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            base_tasks = root / "base" / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            base_tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text(
                ".coordination/tasks/one.json\nsrc/main.py\n", encoding="utf-8"
            )
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                errors = validate_changed_files(tasks, "agent/one", changed, base_tasks)
            finally:
                os.chdir(old_cwd)
            self.assertTrue(any("must be merged" in error for error in errors))

    def test_new_reservation_only_pr_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            base_tasks = root / "base" / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            base_tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text(".coordination/tasks/one.json\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                errors = validate_changed_files(tasks, "agent/one", changed, base_tasks)
            finally:
                os.chdir(old_cwd)
            self.assertEqual([], errors)

    def test_merged_reservation_cannot_expand_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            base_tasks = root / "base" / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            base_tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one")
            original = task("one", "src/auth", branch="agent/one")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            (base_tasks / "one.json").write_text(json.dumps(original), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text("src/main.py\n", encoding="utf-8")
            errors = validate_changed_files(tasks, "agent/one", changed, base_tasks)
            self.assertTrue(any("cannot change" in error for error in errors))

    def test_completed_task_can_only_update_own_task_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".coordination" / "tasks"
            tasks.mkdir(parents=True)
            current = task("one", "src", branch="agent/one", status="done")
            (tasks / "one.json").write_text(json.dumps(current), encoding="utf-8")
            changed = root / "changed.txt"
            changed.write_text("src/main.py\n", encoding="utf-8")
            errors = validate_changed_files(tasks, "agent/one", changed)
            self.assertTrue(any("may only change" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
