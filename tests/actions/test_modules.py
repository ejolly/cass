"""Tests for module sync."""

from __future__ import annotations

__docformat__ = "google"

from unittest.mock import MagicMock

from cass.actions.config import CanvasModuleSpec
from cass.actions.modules import sync_modules
from cass.apis.canvas.schema import CanvasModule


def test_sync_modules_creates_updates_and_skips_by_name():
    client = MagicMock()
    client.list_modules.return_value = [
        CanvasModule(id=5, name="Week 1", published=False),
        CanvasModule(id=6, name="Week 2", published=True),
    ]
    client.create_module.return_value = CanvasModule(id=9, name="Week 3")
    specs = [
        CanvasModuleSpec(name="week 1", published=True),
        CanvasModuleSpec(name="Week 2", published=True),
        CanvasModuleSpec(name="Week 3", published=True),
    ]

    rows, module_ids = sync_modules(client, specs)

    assert rows == [
        ("update", "module", "week 1 (published: True)"),
        ("skip", "module", "Week 2"),
        ("create", "module", "Week 3"),
    ]
    assert module_ids == {"week 1": 5, "Week 2": 6, "Week 3": 9}
    assert client.publish.call_args_list == [(("modules", 5),), (("modules", 9),)]
    client.unpublish.assert_not_called()


def test_sync_modules_leaves_published_alone_when_omitted():
    client = MagicMock()
    client.list_modules.return_value = [
        CanvasModule(id=5, name="Week 1", published=True),
        CanvasModule(id=6, name="Week 2", published=False),
    ]
    client.create_module.return_value = CanvasModule(id=9, name="Week 3")
    specs = [
        CanvasModuleSpec(name="Week 1"),
        CanvasModuleSpec(name="Week 2"),
        CanvasModuleSpec(name="Week 3"),
    ]

    rows, _ = sync_modules(client, specs)

    assert rows == [
        ("skip", "module", "Week 1"),
        ("skip", "module", "Week 2"),
        ("create", "module", "Week 3"),
    ]
    client.publish.assert_not_called()
    client.unpublish.assert_not_called()
