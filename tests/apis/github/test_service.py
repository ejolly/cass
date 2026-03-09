"""Tests for shared gh-classroom service helpers."""

from __future__ import annotations

__docformat__ = "google"

from pathlib import Path

import pytest

from cass.apis.github.service import (
    GitHubServiceError,
    assignment_grades,
    list_assignments,
    list_classrooms,
    resolve_classroom_from_url_sync,
)


class TestResolveClassroom:
    def test_resolves_hidden_gh_id_from_classroom_list(self, monkeypatch):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )

        def fake_run(args: list[str]) -> str:
            if args[:2] == ["classroom", "list"]:
                return (
                    "ID  NAME         URL\n"
                    "4200  Test Course  "
                    "https://classroom.github.com/classrooms/123456-test-course\n"
                )
            if args[:2] == ["classroom", "view"]:
                return (
                    "ID: 4200\n"
                    "URL: https://classroom.github.com/classrooms/123456-test-course\n"
                    "Slug: test-course\n"
                    "Title: Test Course\n"
                    "Organization: test-org\n"
                )
            raise AssertionError(args)

        monkeypatch.setattr("cass.apis.github.service._run_gh", fake_run)

        resolved = resolve_classroom_from_url_sync(
            "https://classroom.github.com/classrooms/123456-test-course"
        )

        assert resolved.url_id == 123456
        assert resolved.gh_id == 4200
        assert resolved.slug == "test-course"
        assert resolved.title == "Test Course"
        assert resolved.org == "test-org"

    def test_raises_when_url_does_not_match_owned_classroom(self, monkeypatch):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )
        monkeypatch.setattr(
            "cass.apis.github.service._run_gh",
            lambda args: (
                "ID  NAME         URL\n"
                "4200  Other Course  "
                "https://classroom.github.com/classrooms/111111-other-course\n"
                "4300  Stats Course  "
                "https://classroom.github.com/classrooms/222222-stats-course\n"
            ),
        )

        with pytest.raises(GitHubServiceError, match="no owned classroom matched"):
            resolve_classroom_from_url_sync(
                "https://classroom.github.com/classrooms/123456-test-course"
            )

    def test_raises_when_list_output_has_no_url_column(self, monkeypatch):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )
        monkeypatch.setattr(
            "cass.apis.github.service._run_gh",
            lambda args: "ID  NAME\n4200  Test Course\n",
        )

        with pytest.raises(GitHubServiceError, match="URL column"):
            resolve_classroom_from_url_sync(
                "https://classroom.github.com/classrooms/123456-test-course"
            )


class TestListing:
    def test_list_classrooms_parses_tabular_output(self, monkeypatch):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )
        monkeypatch.setattr(
            "cass.apis.github.service._run_gh",
            lambda args: (
                "ID  NAME         URL\n"
                "4200  Test Course  "
                "https://classroom.github.com/classrooms/123456-test-course\n"
                "4300  Stats Course  "
                "https://classroom.github.com/classrooms/654321-stats-course\n"
            ),
        )

        classrooms = list_classrooms()

        assert [c.gh_id for c in classrooms] == [4200, 4300]
        assert (
            classrooms[0].url
            == "https://classroom.github.com/classrooms/123456-test-course"
        )

    def test_list_assignments_parses_list_and_details(self, monkeypatch):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )

        def fake_run(args: list[str]) -> str:
            if args[:2] == ["classroom", "assignments"]:
                return "ID  TITLE\n7001  Homework 01\n"
            if args[:2] == ["classroom", "assignment"]:
                return (
                    "ID: 7001\n"
                    "Slug: hw-01\n"
                    "Title: Homework 01\n"
                    "Deadline: 2026-01-15T23:59:00Z\n"
                    "Accepted: 12\n"
                    "Submissions: 10\n"
                    "Passing: 8\n"
                    "Starter Code Repository: test-org/hw-01-starter\n"
                )
            raise AssertionError(args)

        monkeypatch.setattr("cass.apis.github.service._run_gh", fake_run)

        assignments = list_assignments(4200)

        assert len(assignments) == 1
        assert assignments[0].id == 7001
        assert assignments[0].slug == "hw-01"
        assert assignments[0].accepted == 12


class TestGrades:
    def test_assignment_grades_parses_csv(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "cass.apis.github.service._preflight",
            lambda: None,
        )

        def fake_run(args: list[str]) -> str:
            file_arg = Path(args[args.index("--file-name") + 1])
            file_arg.write_text(
                "github_username,roster_identifier,student_repository_name,"
                "student_repository_url,submission_timestamp,points_awarded,"
                "points_available\n"
                "alice,Alice Smith,test-org/hw-01-alice,"
                "https://github.com/test-org/hw-01-alice,2026-01-15T23:59:00Z,"
                "10,10\n",
                encoding="utf-8",
            )
            return ""

        monkeypatch.setattr("cass.apis.github.service._run_gh", fake_run)

        rows = assignment_grades(7001)

        assert len(rows) == 1
        assert rows[0].github_username == "alice"
        assert rows[0].student_repository_name == "test-org/hw-01-alice"
