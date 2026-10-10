"""Combined Canvas JSON records for ``--json`` output."""

from __future__ import annotations

__docformat__ = "google"

from cass.actions.canvas_records import (
    file_tree_records,
    module_detail_record,
    quiz_detail_record,
)
from cass.apis.canvas.schema import (
    CanvasFile,
    CanvasFolder,
    CanvasModule,
    CanvasModuleItem,
    CanvasQuiz,
    CanvasQuizQuestion,
)


def test_file_tree_records_kinds_and_canvas_names() -> None:
    records = file_tree_records(
        [CanvasFolder(id=2, name="course files")],
        [CanvasFile(id=15, display_name="notes.txt", content_type="text/plain")],
    )
    assert [r["kind"] for r in records] == ["folder", "file"]
    assert records[0]["name"] == "course files"
    assert records[1]["content-type"] == "text/plain"


def test_quiz_detail_record_sources() -> None:
    quiz = CanvasQuiz(id=3, title="Quiz A")
    text = '<p>What are you <b>hoping</b>?</p><img src="x.png">'
    questions = [CanvasQuizQuestion(id=1, question_text=text)]
    plain = quiz_detail_record(quiz, questions, from_statistics=False)
    stats = quiz_detail_record(quiz, questions, from_statistics=True)
    assert plain["questions_source"] == "questions"
    assert stats["questions_source"] == "statistics"
    assert plain["questions"][0]["question_text"] == text
    assert plain["title"] == "Quiz A"


def test_module_detail_record_has_items() -> None:
    record = module_detail_record(
        CanvasModule(id=5, name="Week 1", items_count=1),
        [CanvasModuleItem(id=8, title="Read")],
    )
    assert record["name"] == "Week 1"
    assert record["items"][0]["title"] == "Read"
