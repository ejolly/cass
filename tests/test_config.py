"""Tests for cass.config — config discovery and properties."""

import pytest

from cass.config import (
    CanvasModuleSpec,
    Config,
    find_project_root,
    reset_config,
    write_config,
)


@pytest.fixture(autouse=True)
def _reset():
    """Clear cached config after every test."""
    yield
    reset_config()


def test_find_project_root(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (tmp_path / "cass.toml").write_text('[classroom]\nid = 1\norg = "x"\n')
    assert find_project_root(start=nested) == tmp_path


def test_find_project_root_not_found(tmp_path):
    isolated = tmp_path / "empty"
    isolated.mkdir()
    with pytest.raises(SystemExit):
        find_project_root(start=isolated)


def test_write_config_classroom(tmp_path):
    path = tmp_path / "cass.toml"
    write_config(path, classroom_id=42, org="my-org")
    content = path.read_text()
    assert "[classroom]" in content
    assert "id = 42" in content
    assert 'org = "my-org"' in content
    assert "[canvas]" not in content


def test_write_config_both(tmp_path):
    path = tmp_path / "cass.toml"
    write_config(
        path,
        classroom_id=42,
        org="my-org",
        canvas_base_url="https://canvas.example.com",
        canvas_course_id=999,
    )
    content = path.read_text()
    assert "[classroom]" in content
    assert "[canvas]" in content
    assert 'base_url = "https://canvas.example.com"' in content
    assert "course_id = 999" in content


@pytest.mark.parametrize(
    "classroom_id, org, expected",
    [
        (42, "my-org", True),
        (0, "my-org", False),
        (42, "", False),
        (0, "", False),
    ],
    ids=["both-set", "no-id", "no-org", "neither"],
)
def test_has_classroom(classroom_id, org, expected, tmp_path):
    cfg = Config(root=tmp_path, classroom_id=classroom_id, org=org)
    assert cfg.has_classroom is expected


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
def test_has_canvas(base_url, course_id, expected, tmp_path):
    cfg = Config(root=tmp_path, canvas_base_url=base_url, canvas_course_id=course_id)
    assert cfg.has_canvas is expected


# --- Config-as-data (canvas.modules / canvas.assignments) ---


def test_load_canvas_modules(tmp_path, monkeypatch):
    """Parse [[canvas.modules]] from cass.toml."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
        '[[canvas.modules]]\nname = "Week 1"\npublished = false\n\n'
        '[[canvas.modules]]\nname = "Week 2"\npublished = true\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.config import _load_config

    cfg = _load_config()
    assert len(cfg.canvas_modules) == 2
    assert cfg.canvas_modules[0] == CanvasModuleSpec(name="Week 1", published=False)
    assert cfg.canvas_modules[1] == CanvasModuleSpec(name="Week 2", published=True)


def test_load_canvas_assignments(tmp_path, monkeypatch):
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
    from cass.config import _load_config

    cfg = _load_config()
    assert len(cfg.canvas_assignments) == 1
    spec = cfg.canvas_assignments[0]
    assert spec.name == "HW1"
    assert spec.points == 10.0
    assert spec.submission_types == ["online_url"]
    assert spec.published is True
    assert spec.group == "Homework"


def test_load_no_declarations(tmp_path, monkeypatch):
    """Config without [[canvas.modules/assignments]] has empty lists."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.config import _load_config

    cfg = _load_config()
    assert cfg.canvas_modules == []
    assert cfg.canvas_assignments == []


# --- MotherDuck ---


def test_has_motherduck(tmp_path):
    cfg = Config(root=tmp_path, canvas_base_url="https://c.edu", canvas_course_id=1)
    assert cfg.has_motherduck is False

    cfg = Config(
        root=tmp_path,
        canvas_base_url="https://c.edu",
        canvas_course_id=1,
        motherduck_db="cass",
    )
    assert cfg.has_motherduck is True


def test_load_motherduck(tmp_path, monkeypatch):
    """Parse [database] motherduck from cass.toml."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n\n'
        '[database]\nmotherduck = "my_cass_db"\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.config import _load_config

    cfg = _load_config()
    assert cfg.motherduck_db == "my_cass_db"
    assert cfg.has_motherduck is True


def test_load_no_database_section(tmp_path, monkeypatch):
    """Config without [database] defaults to local."""
    toml = tmp_path / "cass.toml"
    toml.write_text(
        '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
    )
    monkeypatch.chdir(tmp_path)
    reset_config()
    from cass.config import _load_config

    cfg = _load_config()
    assert cfg.motherduck_db == ""
    assert cfg.has_motherduck is False
