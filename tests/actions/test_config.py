"""Tests for cass.config — config discovery and properties."""

__docformat__ = "google"

import pytest

from cass.actions.config import (
    CanvasModuleSpec,
    Config,
    find_project_root,
    parse_canvas_course_url,
    parse_classroom_url,
    reset_config,
    update_config,
    write_config,
)


@pytest.fixture(autouse=True)
def _reset():
    """Clear cached config after every test."""
    yield
    reset_config()


class TestFindProjectRoot:
    def test_found(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        assert find_project_root(start=nested) == tmp_path

    def test_not_found(self, tmp_path):
        isolated = tmp_path / "empty"
        isolated.mkdir()
        with pytest.raises(SystemExit):
            find_project_root(start=isolated)


class TestWriteConfig:
    def test_canvas_required(self, tmp_path, monkeypatch):
        path = tmp_path / "cass.toml"
        write_config(
            path,
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            classroom_gh_id=4200,
            org="my-org",
        )
        monkeypatch.chdir(tmp_path)

        from cass.actions.config import load_config

        with pytest.raises(SystemExit, match="must have a \\[canvas\\] section"):
            load_config()

    def test_both(self, tmp_path):
        path = tmp_path / "cass.toml"
        write_config(
            path,
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            classroom_gh_id=4200,
            org="my-org",
            canvas_base_url="https://canvas.example.com",
            canvas_course_id=999,
        )
        content = path.read_text()
        assert "[classroom]" in content
        assert "[canvas]" in content
        assert 'base_url = "https://canvas.example.com"' in content
        assert "course_id = 999" in content

    def test_update_preserves_existing_sections(self, tmp_path):
        path = tmp_path / "cass.toml"
        path.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
            '[[canvas.assignments]]\nname = "HW1"\npoints = 10\n\n'
            '[database]\nmotherduck = "cass_prod"\n'
        )

        update_config(
            path,
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            classroom_gh_id=4200,
            org="test-org",
        )

        content = path.read_text()
        assert 'name = "HW1"' in content
        assert 'motherduck = "cass_prod"' in content
        assert "[classroom]" in content
        assert "gh_id = 4200" in content
        assert 'org = "test-org"' in content

    def test_update_preserves_partial_classroom(self, tmp_path):
        path = tmp_path / "cass.toml"
        path.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )

        update_config(
            path,
            classroom_url="https://classroom.github.com/classrooms/42-course",
            classroom_url_id=42,
            classroom_gh_id=0,
            org="",
        )

        content = path.read_text()
        assert "[classroom]" in content
        assert 'url = "https://classroom.github.com/classrooms/42-course"' in content
        assert "url_id = 42" in content
        assert "gh_id = 0" in content
        assert 'org = ""' in content


class TestSetupParsing:
    def test_parse_canvas_course_url(self):
        assert parse_canvas_course_url("https://canvas.example.com/courses/123") == (
            "https://canvas.example.com",
            123,
        )
        assert parse_canvas_course_url(
            "https://canvas.example.com/courses/123?foo=bar"
        ) == ("https://canvas.example.com", 123)
        assert parse_canvas_course_url("https://canvas.example.com/course/123") is None

    def test_parse_classroom_url(self):
        assert parse_classroom_url("https://classroom.github.com/classrooms/456") == 456
        assert (
            parse_classroom_url(
                "https://classroom.github.com/classrooms/232475786-201b-w26"
            )
            == 232475786
        )
        assert (
            parse_classroom_url(
                "https://classroom.github.com/classrooms/456/assignments"
            )
            == 456
        )


class TestConfigProperties:
    @pytest.mark.parametrize(
        "classroom_url, classroom_url_id, expected",
        [
            ("https://classroom.github.com/classrooms/42-course", 42, True),
            ("", 0, False),
        ],
        ids=["present", "missing"],
    )
    def test_has_classroom_url(
        self, classroom_url, classroom_url_id, expected, tmp_path
    ):
        cfg = Config(
            root=tmp_path,
            classroom_url=classroom_url,
            classroom_url_id=classroom_url_id,
            org="",
        )
        assert cfg.has_classroom_url is expected

    @pytest.mark.parametrize(
        "classroom_url, classroom_url_id, classroom_gh_id, expected",
        [
            ("https://classroom.github.com/classrooms/42-course", 42, 4200, True),
            ("", 0, 4200, False),
            ("https://classroom.github.com/classrooms/42-course", 42, 0, False),
            ("", 0, 0, False),
        ],
        ids=["resolved", "no-url", "no-gh-id", "neither"],
    )
    def test_has_classroom(
        self, classroom_url, classroom_url_id, classroom_gh_id, expected, tmp_path
    ):
        cfg = Config(
            root=tmp_path,
            classroom_url=classroom_url,
            classroom_url_id=classroom_url_id,
            classroom_gh_id=classroom_gh_id,
        )
        assert cfg.has_classroom is expected

    @pytest.mark.parametrize(
        "classroom_url, classroom_url_id, classroom_gh_id, expected",
        [
            ("https://classroom.github.com/classrooms/42-course", 42, 0, True),
            ("https://classroom.github.com/classrooms/42-course", 42, 4200, False),
            ("", 0, 0, False),
        ],
        ids=["pending", "configured", "missing"],
    )
    def test_classroom_needs_resolution(
        self, classroom_url, classroom_url_id, classroom_gh_id, expected, tmp_path
    ):
        cfg = Config(
            root=tmp_path,
            classroom_url=classroom_url,
            classroom_url_id=classroom_url_id,
            classroom_gh_id=classroom_gh_id,
        )
        assert cfg.classroom_needs_resolution is expected

    @pytest.mark.parametrize(
        "base_url, course_id, expected",
        [
            ("https://canvas.example.com", 999, True),
            ("", 999, False),
            ("https://canvas.example.com", 0, False),
            ("", 0, False),
        ],
        ids=["both-set", "no-url", "no-course", "neither"],
    )
    def test_has_canvas(self, base_url, course_id, expected, tmp_path):
        cfg = Config(
            root=tmp_path, canvas_base_url=base_url, canvas_course_id=course_id
        )
        assert cfg.has_canvas is expected


class TestCanvasDeclarations:
    def test_modules(self, tmp_path, monkeypatch):
        """Parse [[canvas.modules]] from cass.toml."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
            '[[canvas.modules]]\nname = "Week 1"\npublished = false\n\n'
            '[[canvas.modules]]\nname = "Week 2"\npublished = true\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert len(cfg.canvas_modules) == 2
        assert cfg.canvas_modules[0] == CanvasModuleSpec(name="Week 1", published=False)
        assert cfg.canvas_modules[1] == CanvasModuleSpec(name="Week 2", published=True)

    def test_assignments(self, tmp_path, monkeypatch):
        """Parse [[canvas.assignments]] from cass.toml."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
            '[[canvas.assignments]]\nname = "HW1"\npoints = 10\n'
            'submission_types = ["online_url"]\ndue_at = "2026-01-20T23:59:59-08:00"\n'
            'published = true\ngroup = "Homework"\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert len(cfg.canvas_assignments) == 1
        spec = cfg.canvas_assignments[0]
        assert spec.name == "HW1"
        assert spec.points == 10.0
        assert spec.submission_types == ["online_url"]
        assert spec.published is True
        assert spec.group == "Homework"

    def test_no_declarations(self, tmp_path, monkeypatch):
        """Config without [[canvas.modules/assignments]] has empty lists."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert cfg.canvas_modules == []
        assert cfg.canvas_assignments == []


class TestMotherDuck:
    def test_has_motherduck(self, tmp_path):
        cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
        assert cfg.has_motherduck is False

        cfg = Config(
            root=tmp_path,
            canvas_base_url="https://c.edu",
            canvas_course_id=1,
            motherduck_db="cass",
        )
        assert cfg.has_motherduck is True

    def test_load(self, tmp_path, monkeypatch):
        """Parse [database] motherduck from cass.toml."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
            '[database]\nmotherduck = "my_cass_db"\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert cfg.motherduck_db == "my_cass_db"
        assert cfg.has_motherduck is True

    def test_no_database_section(self, tmp_path, monkeypatch):
        """Config without [database] defaults to local."""
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert cfg.motherduck_db == ""
        assert cfg.has_motherduck is False
