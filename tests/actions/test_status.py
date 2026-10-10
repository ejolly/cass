from __future__ import annotations

from cass.actions.config import reset_config
from cass.actions.status import count_pending, project_status


def test_count_pending():
    pending = {"t": {"1": {"a": {}, "b": {}}, "2": {"c": {}}}}
    assert count_pending(pending) == 3


def test_project_status_without_db(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    reset_config()

    status = project_status(project_dir / "cass.toml")

    assert status.course_url == "https://canvas.example.com/courses/1"
    assert status.course_id == 1
    assert status.auth_source is None
    assert status.db_path is None
    assert status.course_name is None
    assert status.counts is None
    assert status.pending_changes is None
