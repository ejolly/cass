"""Tests for cass.config — config discovery and properties."""

import pytest

from cass.config import Config, find_project_root, reset_config, write_config


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


def test_find_project_root_classroom_toml(tmp_path):
    (tmp_path / "classroom.toml").write_text('[classroom]\nid = 1\norg = "x"\n')
    assert find_project_root(start=tmp_path) == tmp_path


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
