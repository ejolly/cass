"""Tests for the pure quiz question planner and its rendering."""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from urllib.parse import parse_qsl

import httpx
import pytest

from cass.actions.quiz_plan import (
    QuestionApplyError,
    QuestionChange,
    apply_question_plan,
    format_question_plan,
    plan_quiz_questions,
    plan_summary,
    question_plan_warning,
    question_update_fields,
)
from cass.actions.quizzes import (
    AnswerSpec,
    GroupSpec,
    QuestionSpec,
    QuizSpec,
    QuizState,
    dump_quiz_file,
    load_quiz_file,
    ordered_questions,
    quiz_spec_from_canvas,
)
from cass.apis.canvas.schema import (
    CanvasQuiz,
    CanvasQuizAnswer,
    CanvasQuizGroup,
    CanvasQuizQuestion,
)

LA = "America/Los_Angeles"
QUIZ = CanvasQuiz(id=20, title="Survey", quiz_type="survey")
ANSWER_MARKER = "(answers replaced: existing responses may lose their answer link)"


def _live(
    qid: int,
    position: int,
    *,
    name: str = "Question",
    group_id: int | None = None,
    question_type: str = "essay_question",
    answers: list[CanvasQuizAnswer] | None = None,
) -> CanvasQuizQuestion:
    return CanvasQuizQuestion(
        id=qid,
        question_name=name,
        question_text=f"<p>{qid}</p>",
        question_type=question_type,
        points_possible=0.0,
        position=position,
        answers=answers or [],
        quiz_group_id=group_id,
    )


def _group(gid: int, name: str, position: int, pick_count: int = 1) -> CanvasQuizGroup:
    return CanvasQuizGroup(
        id=gid,
        quiz_id=20,
        name=name,
        pick_count=pick_count,
        question_points=0.0,
        position=position,
    )


def _state(questions, groups=(), student_attempts: int = 0) -> QuizState:
    questions = list(questions)
    groups = list(groups)
    return QuizState(
        quiz=QUIZ,
        questions=ordered_questions(questions, groups),
        groups=groups,
        student_attempts=student_attempts,
    )


def _spec(questions, groups=()) -> QuizSpec:
    return QuizSpec(
        title="Survey",
        quiz_type="survey",
        groups=list(groups),
        questions=list(questions),
    )


def _actions(plan) -> list[str]:
    return [change.action for change in plan.questions]


def _live_ids(plan) -> list[int | None]:
    return [change.live.id if change.live else None for change in plan.questions]


def test_matches_by_id():
    state = _state([_live(11, 1), _live(12, 2)])
    spec = _spec(
        [QuestionSpec(text="<p>12</p>", id=12), QuestionSpec(text="changed", id=11)]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _live_ids(plan) == [12, 11]
    assert _actions(plan) == ["keep", "update"]
    assert plan.questions[1].changed == ["text"]
    assert plan.order_changed is True


def test_renamed_question_matched_by_id():
    state = _state([_live(11, 1, name="First"), _live(12, 2, name="Old")])
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", name="First", id=11),
            QuestionSpec(text="<p>12</p>", name="Second", id=12),
        ]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "update"]
    assert plan.questions[1].changed == ["name"]


def test_unknown_id_raises():
    state = _state([_live(11, 1)])
    spec = _spec([QuestionSpec(text="x", id=999)])
    with pytest.raises(RuntimeError, match="id 999"):
        plan_quiz_questions(spec, state, prune=False)


def test_matches_by_unique_name():
    state = _state(
        [
            _live(11, 1, name="Intro"),
            _live(12, 2, name="Question 2"),
            _live(13, 3, name="Outro"),
        ]
    )
    spec = _spec(
        [
            QuestionSpec(text="<p>13</p>", name="Outro"),
            QuestionSpec(text="<p>12</p>"),
            QuestionSpec(text="<p>11</p>", name="Intro"),
        ]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _live_ids(plan) == [13, 12, 11]
    assert _actions(plan) == ["keep", "keep", "keep"]
    assert plan.order_changed is True


def test_duplicate_names_fall_back_to_order():
    state = _state([_live(11, 1, name="Same"), _live(12, 2, name="Same")])
    spec = _spec(
        [
            QuestionSpec(text="<p>12</p>", name="Same"),
            QuestionSpec(text="<p>11</p>", name="Different"),
        ]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _live_ids(plan) == [11, 12]
    assert plan.questions[0].changed == ["text"]
    assert plan.questions[1].changed == ["text", "name"]


def test_matches_remaining_by_relative_order_and_leftovers():
    state = _state([_live(11, 1), _live(12, 2)])
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>"),
            QuestionSpec(text="<p>12</p>"),
            QuestionSpec(text="new"),
        ]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "keep", "add"]
    assert _live_ids(plan) == [11, 12, None]

    state = _state([_live(11, 1), _live(12, 2), _live(13, 3)])
    spec = _spec([QuestionSpec(text="<p>11</p>"), QuestionSpec(text="<p>12</p>")])
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "keep", "extra"]
    assert plan.questions[2].live.id == 13
    plan = plan_quiz_questions(spec, state, prune=True)
    assert _actions(plan) == ["keep", "keep", "delete"]
    assert plan.questions[2].spec is None


def test_insert_in_middle_with_ids_is_one_add():
    state = _state([_live(11, 1), _live(12, 2), _live(13, 3)])
    spec = quiz_spec_from_canvas(QUIZ, state.questions, "", LA)
    spec.questions.insert(1, QuestionSpec(text="new"))
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "add", "keep", "keep"]
    assert plan.order_changed is True


def test_exported_file_plans_all_keep(tmp_path):
    choice_answers = [
        CanvasQuizAnswer(id=1, text="Yes", weight=100.0),
        CanvasQuizAnswer(id=2, text="No", weight=0.0),
    ]
    group = CanvasQuizGroup(
        id=5, quiz_id=20, name="Pair", pick_count=1, question_points=2.0, position=2
    )
    questions = [
        _live(11, 1, name="Intro"),
        _live(13, 2, group_id=5),
        _live(12, 1, group_id=5),
        _live(
            14,
            3,
            question_type="multiple_choice_question",
            answers=choice_answers,
        ),
    ]
    state = _state(questions, [group])
    spec = quiz_spec_from_canvas(QUIZ, questions, "", LA, groups=[group])
    path = tmp_path / "quiz.toml"
    dump_quiz_file(spec, path)
    plan = plan_quiz_questions(load_quiz_file(path), state, prune=False)
    assert _actions(plan) == ["keep", "keep", "keep", "keep"]
    assert [g.action for g in plan.groups] == ["keep"]
    assert plan.order_changed is False
    assert plan.reordered_groups == []
    assert plan.has_changes is False
    assert plan_summary(plan) == "0 added, 0 updated, 0 deleted, 4 kept, 0 extra"


def test_group_add_and_move():
    state = _state([_live(11, 1), _live(12, 2), _live(13, 3)])
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12, group="Pair"),
            QuestionSpec(text="<p>13</p>", id=13),
        ],
        [GroupSpec("Pair")],
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert [g.action for g in plan.groups] == ["add"]
    assert plan.questions[1].action == "update"
    assert plan.questions[1].changed == ["group"]
    assert plan.reordered_groups == ["Pair"]
    assert plan.order == [("question", 0), ("group", "Pair"), ("question", 2)]
    assert plan.group_members == {"Pair": [1]}
    assert plan.has_changes is True


def _paired_state() -> QuizState:
    """Q11 (pos 1), then group 5 "Pair" (pos 2) holding Q12 and Q13."""
    return _state(
        [_live(11, 1), _live(12, 1, group_id=5), _live(13, 2, group_id=5)],
        [_group(5, "Pair", 2)],
    )


def test_prune_deletes_emptied_group():
    spec = _spec(
        [QuestionSpec(text="<p>11</p>", id=11), QuestionSpec(text="<p>12</p>", id=12)]
    )
    plan = plan_quiz_questions(spec, _paired_state(), prune=True)
    assert _actions(plan) == ["keep", "update", "delete"]
    assert plan.questions[1].changed == ["group"]
    assert plan.questions[2].live.id == 13
    assert plan.questions[2].group == "Pair"
    assert [g.action for g in plan.groups] == ["delete"]

    plan = plan_quiz_questions(spec, _paired_state(), prune=False)
    assert _actions(plan) == ["keep", "update", "extra"]
    assert [g.action for g in plan.groups] == ["extra"]
    assert plan.order == [("question", 0), ("question", 1), ("group", "Pair")]
    assert plan.group_members == {"Pair": [2]}
    assert plan_summary(plan) == "0 added, 1 updated, 0 deleted, 1 kept, 1 extra"


def test_emptied_extra_group_is_not_reordered():
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12),
            QuestionSpec(text="<p>13</p>", id=13),
        ]
    )
    plan = plan_quiz_questions(spec, _paired_state(), prune=False)
    assert [g.action for g in plan.groups] == ["extra"]
    assert plan.reordered_groups == []
    assert plan.order_changed is True


def test_extra_question_stays_in_its_matched_group():
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12, group="Pair"),
        ],
        [GroupSpec("Pair", points_per_item=0.0)],
    )
    plan = plan_quiz_questions(spec, _paired_state(), prune=False)
    assert _actions(plan) == ["keep", "keep", "extra"]
    assert [g.action for g in plan.groups] == ["keep"]
    assert plan.group_members == {"Pair": [1, 2]}
    assert plan.order_changed is False
    assert plan.reordered_groups == []
    assert plan.has_changes is False


def test_group_settings_change():
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12, group="Pair"),
            QuestionSpec(text="<p>13</p>", id=13, group="Pair"),
        ],
        [GroupSpec("Pair", pick_count=2)],
    )
    plan = plan_quiz_questions(spec, _paired_state(), prune=False)
    assert [g.action for g in plan.groups] == ["update"]
    assert plan.groups[0].changed == ["pick_count"]
    assert _actions(plan) == ["keep", "keep", "keep"]
    assert plan.has_changes is True
    assert plan_summary(plan) == (
        "0 added, 0 updated, 0 deleted, 3 kept, 0 extra; groups: 1 updated"
    )


def test_duplicate_live_group_names_raise():
    state = _state(
        [_live(11, 1, group_id=5), _live(12, 1, group_id=6)],
        [_group(5, "Pair", 1), _group(6, "Pair", 2)],
    )
    spec = _spec([QuestionSpec(text="x")])
    with pytest.raises(RuntimeError, match="two question groups named 'Pair'"):
        plan_quiz_questions(spec, state, prune=False)


def test_settings_only_file_marks_everything_extra():
    state = _state([_live(11, 1), _live(12, 2)])
    plan = plan_quiz_questions(_spec([]), state, prune=False)
    assert _actions(plan) == ["extra", "extra"]
    assert plan.order_changed is False
    assert plan.has_changes is False
    assert plan_summary(plan) == "0 added, 0 updated, 0 deleted, 0 kept, 2 extra"


def test_empty_file_name_never_reported():
    state = _state([_live(11, 1, name="Question 4"), _live(12, 2, name="Custom")])
    spec = _spec(
        [QuestionSpec(text="<p>11</p>", id=11), QuestionSpec(text="<p>12</p>", id=12)]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "keep"]
    assert all("name" not in change.changed for change in plan.questions)


def test_default_file_name_built_in_code_is_not_a_change():
    state = _state([_live(11, 1, name="Custom")])
    spec = _spec([QuestionSpec(text="<p>11</p>", id=11, name="Question 2")])
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep"]


def test_unchanged_partial_weight_answers_keep():
    live = _live(
        11,
        1,
        question_type="multiple_answers_question",
        answers=[
            CanvasQuizAnswer(id=1, text="A", weight=50.0),
            CanvasQuizAnswer(id=2, text="B", weight=50.0),
            CanvasQuizAnswer(id=3, text="C", weight=0.0),
        ],
    )
    spec = _spec(
        [
            QuestionSpec(
                text="<p>11</p>",
                id=11,
                type="multiple_answers_question",
                answers=[
                    AnswerSpec("A", correct=True),
                    AnswerSpec("B", correct=True),
                    AnswerSpec("C"),
                ],
            )
        ]
    )
    plan = plan_quiz_questions(spec, _state([live]), prune=False)
    assert _actions(plan) == ["keep"]


def _answer_change(student_attempts: int):
    live = _live(
        11,
        1,
        question_type="multiple_choice_question",
        answers=[
            CanvasQuizAnswer(id=1, text="A", weight=100.0),
            CanvasQuizAnswer(id=2, text="B", weight=0.0),
        ],
    )
    spec = _spec(
        [
            QuestionSpec(
                text="<p>11</p>",
                id=11,
                type="multiple_choice_question",
                answers=[AnswerSpec("A"), AnswerSpec("B", correct=True)],
            )
        ]
    )
    state = _state([live], student_attempts=student_attempts)
    return plan_quiz_questions(spec, state, prune=False)


def test_format_marks_answer_changes_when_students_attempted():
    plan = _answer_change(student_attempts=2)
    assert plan.questions[0].changed == ["answers"]
    lines = format_question_plan(plan)
    assert lines[0].startswith("update question 11")
    assert lines[0].endswith(ANSWER_MARKER)
    warning = question_plan_warning(plan)
    assert warning is not None
    assert "2 finished student attempt(s)" in warning

    plan = _answer_change(student_attempts=0)
    lines = format_question_plan(plan)
    assert not any(ANSWER_MARKER in line for line in lines)
    assert lines[0].endswith("(answers)")
    assert question_plan_warning(plan) is None


def test_format_lines_start_with_action():
    entry = re.compile(r"^(add|update|delete|keep|extra|reorder) ")
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11, group="New"),
            QuestionSpec(text="<p>Brand <b>new</b></p>"),
        ],
        [GroupSpec("New")],
    )
    for prune in (False, True):
        plan = plan_quiz_questions(spec, _paired_state(), prune=prune)
        lines = format_question_plan(plan)
        assert all(entry.match(line) for line in lines), lines
        assert lines[-1] == "reorder  questions"

    plan = plan_quiz_questions(spec, _paired_state(), prune=False)
    lines = format_question_plan(plan)
    assert lines[0] == "update question 11      11  (group)  [group 'New']"
    assert lines[1] == "update question 12      Brand new  (text, group)"
    assert lines[2] == (
        "extra  question 13      13  (not in file; kept — --prune deletes it)"
    )
    assert "add    group    'New'  (pick 1, 0 pts each)" in lines
    assert "extra  group    'Pair'  (pick 1, 0 pts each)" in lines


def test_long_text_is_cut_to_sixty_characters():
    state = _state([])
    spec = _spec([QuestionSpec(text="<p>" + "x" * 100 + "</p>")])
    plan = plan_quiz_questions(spec, state, prune=False)
    assert format_question_plan(plan)[0] == "add    question         " + "x" * 60


# --- Applying ---

BASE = "/api/v1/courses/1/quizzes/20"


def _apply_client(fail_path: str | None = None):
    """A real CanvasClient over a transport that records every request."""
    from cass.apis.canvas.client import CanvasClient

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == fail_path:
            return httpx.Response(500, json={"errors": "boom"})
        if request.method == "POST" and path.endswith("/groups"):
            return httpx.Response(
                200, json={"quiz_groups": [{"id": 50, "name": "Pair"}]}
            )
        if request.method == "POST" and path.endswith("/questions"):
            return httpx.Response(200, json={"id": 900})
        if request.method == "PUT" and "/questions/" in path:
            return httpx.Response(200, json={"id": int(path.rsplit("/", 1)[1])})
        return httpx.Response(200, json={})

    client = CanvasClient(
        "https://canvas.example.com",
        token="test-token",
        course_id=1,
        transport=httpx.MockTransport(handler),
        time_zone=LA,
    )
    return client, requests


def _pair_plan():
    """Update 11, move 12 and a new question into new group "Pair", delete 13."""
    state = _state([_live(11, 1), _live(12, 2)])
    spec = _spec(
        [
            QuestionSpec(text="<p>new 11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12, group="Pair"),
            QuestionSpec(text="<p>fresh</p>", group="Pair"),
        ],
        [GroupSpec("Pair")],
    )
    plan = plan_quiz_questions(spec, state, prune=True)
    # A file question always claims a leftover live one, so a plan never holds
    # an add and a delete together; append the delete to cover both.
    plan.questions.append(QuestionChange("delete", None, _live(13, 3)))
    return plan


def test_apply_request_sequence():
    client, requests = _apply_client()
    applied = apply_question_plan(client, 20, _pair_plan())
    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", f"{BASE}/groups"),
        ("PUT", f"{BASE}/questions/11"),
        ("PUT", f"{BASE}/questions/12"),
        ("POST", f"{BASE}/questions"),
        ("DELETE", f"{BASE}/questions/13"),
        ("POST", f"{BASE}/reorder"),
        ("POST", f"{BASE}/groups/50/reorder"),
        ("PUT", BASE),
    ]
    assert applied == [
        "create group 'Pair'",
        "update question 11 (text)",
        "update question 12 (group)",
        "create question 3",
        "delete question 13",
        "reorder quiz",
        "reorder group 'Pair'",
        "re-save quiz",
    ]
    assert json.loads(requests[1].content) == {
        "question": {"question_text": "<p>new 11</p>"}
    }
    assert json.loads(requests[2].content) == {"question": {"quiz_group_id": 50}}
    assert json.loads(requests[3].content)["question"]["quiz_group_id"] == 50
    reorder = parse_qsl(requests[5].content.decode())
    assert ("order[][type]", "group") in reorder
    assert ("order[][id]", "50") in reorder
    group_reorder = parse_qsl(requests[6].content.decode())
    assert [v for k, v in group_reorder if k == "order[]" or k == "order[][id]"] == [
        "12",
        "900",
    ]
    assert ("quiz[notify_of_update]", "false") in parse_qsl(
        requests[7].content.decode()
    )


def test_apply_failure_in_questions_stops():
    client, requests = _apply_client(fail_path=f"{BASE}/questions/12")
    with pytest.raises(QuestionApplyError) as excinfo:
        apply_question_plan(client, 20, _pair_plan())
    assert excinfo.value.applied == [
        "create group 'Pair'",
        "update question 11 (text)",
    ]
    assert "Stopped; applied before the failure:" in str(excinfo.value)
    assert [(r.method, r.url.path) for r in requests][-1] == (
        "PUT",
        f"{BASE}/questions/12",
    )
    assert not any(r.url.path.endswith("/reorder") for r in requests)


def test_apply_failure_before_any_change_says_so():
    client, _ = _apply_client(fail_path=f"{BASE}/groups")
    with pytest.raises(QuestionApplyError, match="Stopped before any change"):
        apply_question_plan(client, 20, _pair_plan())


def test_apply_all_keep_sends_nothing(tmp_path):
    question = _live(11, 1, name="Intro")
    state = _state([question])
    spec = quiz_spec_from_canvas(QUIZ, [question], "", LA)
    path = tmp_path / "quiz.toml"
    dump_quiz_file(spec, path)
    plan = plan_quiz_questions(load_quiz_file(path), state, prune=False)
    client, requests = _apply_client()
    assert apply_question_plan(client, 20, plan) == []
    assert requests == []


def test_update_fields_leave_group_sends_null():
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>x</p>", id=11),
        _live(11, 1, group_id=5),
        changed=["group"],
    )
    assert question_update_fields(change, "survey", None) == {"quiz_group_id": None}


def test_update_fields_never_sends_empty_name():
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>x</p>", name="", id=11),
        _live(11, 1),
        changed=["text"],
    )
    assert question_update_fields(change, "survey", None) == {
        "question_text": "<p>x</p>"
    }
