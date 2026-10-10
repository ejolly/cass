"""Tests for cass.config — config discovery and properties."""

__docformat__ = "google"

import pytest

from cass.actions.config import (
    CanvasModuleSpec,
    Config,
    ModuleItemSpec,
    find_project_root,
    load_config,
    parse_canvas_course_url,
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
        write_config(path)
        monkeypatch.chdir(tmp_path)

        from cass.actions.config import load_config

        with pytest.raises(SystemExit, match="must have a \\[canvas\\] section"):
            load_config()

    def test_canvas_only(self, tmp_path):
        path = tmp_path / "cass.toml"
        write_config(
            path,
            canvas_base_url="https://canvas.example.com",
            canvas_course_id=999,
        )
        content = path.read_text()
        assert "[classroom]" not in content
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

        update_config(path, canvas_course_id=2)

        content = path.read_text()
        assert 'name = "HW1"' in content
        assert 'motherduck = "cass_prod"' in content
        assert "course_id = 2" in content
        assert "[classroom]" not in content

    def test_update_drops_stale_classroom_section(self, tmp_path):
        path = tmp_path / "cass.toml"
        path.write_text(
            "[classroom]\n"
            'url = "https://classroom.github.com/classrooms/42-course"\n'
            "url_id = 42\ngh_id = 4200\n\n"
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
        )

        update_config(path)

        content = path.read_text()
        assert "[classroom]" not in content
        assert "course_id = 1" in content


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


class TestConfigProperties:
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

    def test_load_ignores_classroom_section(self, tmp_path, monkeypatch):
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[classroom]\nurl = "https://classroom.github.com/classrooms/42"\n\n'
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 5\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert cfg.canvas_course_id == 5
        assert not hasattr(cfg, "classroom_url")


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


class TestExplicitConfigPath:
    def test_find_project_root_with_explicit_file(self, tmp_path):
        other = tmp_path / "f25" / "cass_f25.toml"
        other.parent.mkdir()
        other.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 5\n')
        assert find_project_root(config_path=other) == other.parent

    def test_explicit_missing_file_exits_with_path(self, tmp_path):
        missing = tmp_path / "nope.toml"
        with pytest.raises(SystemExit, match=r"nope\.toml"):
            find_project_root(config_path=missing)

    def test_set_config_path_drives_load_config(self, tmp_path, monkeypatch):
        from cass.actions.config import config_file, load_config, set_config_path

        other = tmp_path / "f25" / "cass_f25.toml"
        other.parent.mkdir()
        other.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 5\n')
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        set_config_path(other)
        try:
            assert config_file() == other.resolve()
            cfg = load_config()
            assert cfg.canvas_course_id == 5
            assert cfg.root == other.parent.resolve()
        finally:
            set_config_path(None)

    def test_cass_config_env_drives_load_config(self, tmp_path, monkeypatch):
        from cass.actions.config import config_file, load_config

        other = tmp_path / "f25" / "cass_f25.toml"
        other.parent.mkdir()
        other.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 5\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CASS_CONFIG", str(other))
        assert config_file() == other.resolve()
        assert load_config().canvas_course_id == 5
        assert find_project_root() == other.parent.resolve()

    def test_load_explicit_path_leaves_project_config(self, tmp_path, monkeypatch):
        from cass.actions.config import get_config, load_config

        (tmp_path / "cass.toml").write_text(
            '[canvas]\nbase_url = "https://c.edu"\ncourse_id = 1\n'
        )
        other = tmp_path / "f25" / "cass_f25.toml"
        other.parent.mkdir()
        other.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 5\n')
        monkeypatch.chdir(tmp_path)
        assert load_config(other).canvas_course_id == 5
        assert get_config().canvas_course_id == 1


class TestTimeZoneAndQuizRefs:
    def test_time_zone_and_quizzes(self, tmp_path, monkeypatch):
        toml = tmp_path / "cass.toml"
        toml.write_text(
            '[canvas]\nbase_url = "https://canvas.example.com"\ncourse_id = 1\n'
            'time_zone = "America/Los_Angeles"\n\n'
            '[[canvas.quizzes]]\nfile = "quizzes/09-25.toml"\n'
        )
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        cfg = load_config()
        assert cfg.canvas_time_zone == "America/Los_Angeles"
        assert (
            cfg.canvas_quizzes[0].file
            == (tmp_path / "quizzes" / "09-25.toml").resolve()
        )

    def test_time_zone_defaults_empty(self, tmp_path, monkeypatch):
        toml = tmp_path / "cass.toml"
        toml.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 1\n')
        monkeypatch.chdir(tmp_path)
        reset_config()
        from cass.actions.config import load_config

        assert load_config().canvas_time_zone == ""
        assert load_config().canvas_quizzes == []

    def test_update_writes_time_zone(self, tmp_path):
        path = tmp_path / "cass.toml"
        path.write_text('[canvas]\nbase_url = "https://c.edu"\ncourse_id = 1\n')
        update_config(path, canvas_time_zone="America/Los_Angeles")
        assert 'time_zone = "America/Los_Angeles"' in path.read_text()


HEADER = '[canvas]\nbase_url = "https://c.edu"\ncourse_id = 1\n\n'


def _write(tmp_path, body: str):
    path = tmp_path / "cass.toml"
    path.write_text(HEADER + body)
    return path


class TestModuleItems:
    def test_loads_each_item_type(self, tmp_path):
        path = _write(
            tmp_path,
            """[[canvas.modules]]
name = "Week 1"

[[canvas.modules.items]]
type = "Assignment"
title = "HW 1"

[[canvas.modules.items]]
type = "Quiz"
title = "Quiz 1"

[[canvas.modules.items]]
type = "Page"
title = "Overview"

[[canvas.modules.items]]
type = "File"
file = "readings/w1.pdf"
source = "readings/w1.pdf"
title = "Reading"
indent = 1
published = false

[[canvas.modules.items]]
type = "ExternalUrl"
url = "https://example.com"
title = "Link"

[[canvas.modules.items]]
type = "SubHeader"
title = "Extras"
""",
        )
        items = load_config(path).canvas_modules[0].items
        assert items == [
            ModuleItemSpec(type="Assignment", title="HW 1"),
            ModuleItemSpec(type="Quiz", title="Quiz 1"),
            ModuleItemSpec(type="Page", title="Overview"),
            ModuleItemSpec(
                type="File",
                title="Reading",
                file="readings/w1.pdf",
                source=(tmp_path / "readings/w1.pdf").resolve(),
                indent=1,
                published=False,
            ),
            ModuleItemSpec(type="ExternalUrl", url="https://example.com", title="Link"),
            ModuleItemSpec(type="SubHeader", title="Extras"),
        ]
        assert items is not None
        assert items[0].published is None
        assert items[0].indent == 0

    def test_type_is_case_insensitive(self, tmp_path):
        path = _write(
            tmp_path,
            '[[canvas.modules]]\nname = "W"\n\n'
            '[[canvas.modules.items]]\ntype = "subheader"\ntitle = "X"\n',
        )
        items = load_config(path).canvas_modules[0].items
        assert items is not None
        assert items[0].type == "SubHeader"

    def test_module_without_items_key_has_none(self, tmp_path):
        path = _write(tmp_path, '[[canvas.modules]]\nname = "W"\n')
        assert load_config(path).canvas_modules[0].items is None

    def test_empty_items_list(self, tmp_path):
        path = _write(tmp_path, '[[canvas.modules]]\nname = "W"\nitems = []\n')
        assert load_config(path).canvas_modules[0].items == []

    def test_file_path_is_normalized(self, tmp_path):
        path = _write(
            tmp_path,
            '[[canvas.modules]]\nname = "W"\n\n'
            '[[canvas.modules.items]]\ntype = "File"\nfile = "/readings//w1.pdf"\n',
        )
        items = load_config(path).canvas_modules[0].items
        assert items is not None
        assert items[0].file == "readings/w1.pdf"

    @pytest.mark.parametrize(
        ("bad_item", "message"),
        [
            ('title = "x"', ": missing 'type'"),
            ('type = "Discussion"', ": unknown type 'Discussion' (expected one of:"),
            ('type = "Page"', " (Page): missing required key 'title'"),
            (
                'type = "ExternalUrl"\ntitle = "t"',
                " (ExternalUrl): missing required key 'url'",
            ),
            ('type = "File"', " (File): missing required key 'file'"),
            (
                'type = "Page"\ntitle = "t"\npublish = true',
                " (Page): unknown key 'publish'",
            ),
            (
                'type = "Page"\ntitle = "t"\nindent = -1',
                " (Page): indent must be a whole number",
            ),
            (
                'type = "Page"\ntitle = "t"\npublished = "yes"',
                " (Page): published must be true or false",
            ),
            ('type = "File"\nfile = ""', " (File): file must be a non-empty string"),
            ('type = "Page"\ntitle = 5', " (Page): title must be a non-empty string"),
            (
                'type = "File"\nfile = "a.pdf"\nsource = ""',
                " (File): source must be a non-empty string",
            ),
            (
                'type = "ExternalUrl"\ntitle = "t"\nurl = "example.com/x"',
                " (ExternalUrl): url must start with http:// or https://",
            ),
            (
                'type = "ExternalUrl"\ntitle = "t"\nurl = "ftp://example.com"',
                " (ExternalUrl): url must start with http:// or https://",
            ),
        ],
    )
    def test_invalid_item_fails_naming_module_and_index(
        self, tmp_path, bad_item, message
    ):
        path = _write(
            tmp_path,
            '[[canvas.modules]]\nname = "Week 1"\n\n'
            '[[canvas.modules.items]]\ntype = "SubHeader"\ntitle = "ok"\n\n'
            f"[[canvas.modules.items]]\n{bad_item}\n",
        )
        with pytest.raises(SystemExit) as exc:
            load_config(path)
        text = str(exc.value)
        assert "module 'Week 1' item 2" in text
        assert message in text

    def test_items_that_are_not_tables_fail_naming_the_item(self, tmp_path):
        path = _write(tmp_path, '[[canvas.modules]]\nname = "W"\nitems = [1]\n')
        with pytest.raises(SystemExit, match=r"module 'W' item 1: must be a table"):
            load_config(path)

    def test_items_that_are_not_a_list_fail(self, tmp_path):
        path = _write(tmp_path, '[[canvas.modules]]\nname = "W"\nitems = "x"\n')
        with pytest.raises(SystemExit, match=r"module 'W': items must be a list"):
            load_config(path)
