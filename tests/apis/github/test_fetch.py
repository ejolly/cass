"""Tests for GitHub Classroom repo fetch helpers."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
from typing import cast

from cass.apis.github.client import GitHubClient
from cass.apis.github.fetch import pull_gh, remove_gh_classroom_repos
from cass.db.schema import Assignment, Student


class TestPullGH:
    def test_pull_gh_reports_counts_from_shared_fetch_path(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_config",
            lambda: type("Cfg", (), {"root": tmp_path})(),
        )
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_sortable_names",
            lambda: {1: "Smith, Alice"},
        )

        async def fake_repo_map(_client, slug: str):
            return {"alice-gh": f"test-org/{slug}-alice-gh"}

        def fake_clone_or_pull(_repo_url, dest):
            if dest.name == "hw-01":
                return "cloned"
            return "updated"

        monkeypatch.setattr("cass.apis.github.fetch.build_repo_map", fake_repo_map)
        monkeypatch.setattr("cass.apis.github.fetch._clone_or_pull", fake_clone_or_pull)

        students = [Student(canvas_id=1, github_username="alice-gh", name="Alice")]
        assignments = [
            Assignment(slug="hw-01", title="HW 01", gh_assignment_slug="hw-01"),
            Assignment(slug="lab-02", title="Lab 02", gh_assignment_slug="lab-02"),
        ]

        counts = asyncio.run(
            pull_gh(cast(GitHubClient, object()), assignments, students)
        )

        assert counts == {
            "cloned": 1,
            "updated": 1,
            "up_to_date": 0,
            "skipped": 0,
            "errors": 0,
        }

    def test_pull_gh_parallel_students(self, tmp_path, monkeypatch) -> None:
        """Students fetched in parallel; counts aggregate correctly."""
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_config",
            lambda: type("Cfg", (), {"root": tmp_path})(),
        )
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_sortable_names",
            lambda: {1: "Smith, Alice", 2: "Jones, Bob", 3: "Lee, Carol"},
        )

        async def fake_repo_map(_client, slug: str):
            return {
                "alice-gh": f"org/{slug}-alice-gh",
                "bob-gh": f"org/{slug}-bob-gh",
                "carol-gh": f"org/{slug}-carol-gh",
            }

        def fake_clone_or_pull(_repo_url, dest):
            return "cloned"

        monkeypatch.setattr("cass.apis.github.fetch.build_repo_map", fake_repo_map)
        monkeypatch.setattr("cass.apis.github.fetch._clone_or_pull", fake_clone_or_pull)

        students = [
            Student(canvas_id=1, github_username="alice-gh", name="Alice"),
            Student(canvas_id=2, github_username="bob-gh", name="Bob"),
            Student(canvas_id=3, github_username="carol-gh", name="Carol"),
        ]
        assignments = [
            Assignment(slug="hw-01", title="HW 01", gh_assignment_slug="hw-01"),
            Assignment(slug="hw-02", title="HW 02", gh_assignment_slug="hw-02"),
        ]

        progress: list[str] = []
        counts = asyncio.run(
            pull_gh(
                cast(GitHubClient, object()),
                assignments,
                students,
                on_progress=progress.append,
            )
        )

        # 3 students x 2 assignments = 6 clones
        assert counts["cloned"] == 6
        assert counts["errors"] == 0
        # Progress messages received for each student
        assert len([m for m in progress if "cloned" in m]) == 6

    def test_pull_gh_error_isolation(self, tmp_path, monkeypatch) -> None:
        """One student clone error doesn't prevent others from completing."""
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_config",
            lambda: type("Cfg", (), {"root": tmp_path})(),
        )
        monkeypatch.setattr(
            "cass.apis.github.fetch.get_sortable_names",
            lambda: {1: "Smith, Alice", 2: "Jones, Bob"},
        )

        async def fake_repo_map(_client, slug: str):
            return {
                "alice-gh": f"org/{slug}-alice-gh",
                "bob-gh": f"org/{slug}-bob-gh",
            }

        def fake_clone_or_pull(_repo_url, dest):
            if "bob-gh" in _repo_url:
                raise RuntimeError("network error")
            return "cloned"

        monkeypatch.setattr("cass.apis.github.fetch.build_repo_map", fake_repo_map)
        monkeypatch.setattr("cass.apis.github.fetch._clone_or_pull", fake_clone_or_pull)

        students = [
            Student(canvas_id=1, github_username="alice-gh", name="Alice"),
            Student(canvas_id=2, github_username="bob-gh", name="Bob"),
        ]
        assignments = [
            Assignment(slug="hw-01", title="HW 01", gh_assignment_slug="hw-01"),
        ]

        counts = asyncio.run(
            pull_gh(cast(GitHubClient, object()), assignments, students)
        )

        assert counts["cloned"] == 1
        assert counts["errors"] == 1


class TestRemoveRepos:
    def test_remove_gh_classroom_repos_uses_project_root(self, tmp_path) -> None:
        gh_dir = tmp_path / "gh-classroom"
        (gh_dir / "alice" / "hw-01").mkdir(parents=True)
        (gh_dir / "bob" / "hw-01").mkdir(parents=True)

        removed = remove_gh_classroom_repos(tmp_path)

        assert removed == 2
        assert list(gh_dir.iterdir()) == []
