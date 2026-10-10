"""Tests for the pure quiz question planner and its rendering."""

from __future__ import annotations

__docformat__ = "google"


import json
import re
from urllib.parse import parse_qsl

import httpx
import msgspec
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
# Question-level feedback every update resends; empty on the mocks
COMMENTS = {
    "correct_comments": "",
    "incorrect_comments": "",
    "neutral_comments": "",
    "correct_comments_html": "",
    "incorrect_comments_html": "",
    "neutral_comments_html": "",
}


def _live(
    qid: int,
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
    state = _state([_live(11), _live(12)])
    spec = _spec(
        [QuestionSpec(text="<p>12</p>", id=12), QuestionSpec(text="changed", id=11)]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _live_ids(plan) == [12, 11]
    assert _actions(plan) == ["keep", "update"]
    assert plan.questions[1].changed == ["text"]
    assert plan.order_changed is True


def test_renamed_question_matched_by_id():
    state = _state([_live(11, name="First"), _live(12, name="Old")])
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
    state = _state([_live(11)])
    spec = _spec([QuestionSpec(text="x", id=999)])
    with pytest.raises(RuntimeError, match="id 999"):
        plan_quiz_questions(spec, state, prune=False)


def test_matches_by_unique_name():
    state = _state(
        [
            _live(11, name="Intro"),
            _live(12, name="Question 2"),
            _live(13, name="Outro"),
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
    state = _state([_live(11, name="Same"), _live(12, name="Same")])
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
    state = _state([_live(11), _live(12)])
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

    state = _state([_live(11), _live(12), _live(13)])
    spec = _spec([QuestionSpec(text="<p>11</p>"), QuestionSpec(text="<p>12</p>")])
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "keep", "extra"]
    assert plan.questions[2].live.id == 13
    plan = plan_quiz_questions(spec, state, prune=True)
    assert _actions(plan) == ["keep", "keep", "delete"]
    assert plan.questions[2].spec is None


def test_insert_in_middle_with_ids_is_one_add():
    state = _state([_live(11), _live(12), _live(13)])
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
        _live(11, name="Intro"),
        _live(12, group_id=5),
        _live(13, group_id=5),
        _live(
            14,
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
    state = _state([_live(11), _live(12), _live(13)])
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
        [_live(11), _live(12, group_id=5), _live(13, group_id=5)],
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
        [_live(11, group_id=5), _live(12, group_id=6)],
        [_group(5, "Pair", 1), _group(6, "Pair", 2)],
    )
    spec = _spec([QuestionSpec(text="x")])
    with pytest.raises(RuntimeError, match="two question groups named 'Pair'"):
        plan_quiz_questions(spec, state, prune=False)


def test_leaving_a_group_forces_quiz_reorder():
    # 12 moves from group A to group B; the top-level layout [A, B] is unchanged.
    state = _state(
        [
            _live(12, group_id=5),
            _live(13, group_id=5),
            _live(14, group_id=6),
        ],
        [_group(5, "A", 1), _group(6, "B", 2)],
    )
    spec = _spec(
        [
            QuestionSpec(text="<p>13</p>", id=13, group="A"),
            QuestionSpec(text="<p>12</p>", id=12, group="B"),
            QuestionSpec(text="<p>14</p>", id=14, group="B"),
        ],
        [GroupSpec("A", points_per_item=0.0), GroupSpec("B", points_per_item=0.0)],
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert plan.questions[1].changed == ["group"]
    assert plan.order == [("group", "A"), ("group", "B")]
    assert plan.order_changed is True


def test_question_leaving_pruned_group_is_top_level_in_order():
    spec = _spec(
        [QuestionSpec(text="<p>11</p>", id=11), QuestionSpec(text="<p>12</p>", id=12)]
    )
    plan = plan_quiz_questions(spec, _paired_state(), prune=True)
    assert plan.questions[1].changed == ["group"]
    assert plan.order == [("question", 0), ("question", 1)]
    assert plan.order_changed is True


def test_settings_only_file_marks_everything_extra():
    state = _state([_live(11), _live(12)])
    plan = plan_quiz_questions(_spec([]), state, prune=False)
    assert _actions(plan) == ["extra", "extra"]
    assert plan.order_changed is False
    assert plan.has_changes is False
    assert plan_summary(plan) == "0 added, 0 updated, 0 deleted, 0 kept, 2 extra"


def test_empty_file_name_never_reported():
    state = _state([_live(11, name="Question 4"), _live(12, name="Custom")])
    spec = _spec(
        [QuestionSpec(text="<p>11</p>", id=11), QuestionSpec(text="<p>12</p>", id=12)]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep", "keep"]
    assert all("name" not in change.changed for change in plan.questions)


def test_default_file_name_built_in_code_is_not_a_change():
    state = _state([_live(11, name="Custom")])
    spec = _spec([QuestionSpec(text="<p>11</p>", id=11, name="Question 2")])
    plan = plan_quiz_questions(spec, state, prune=False)
    assert _actions(plan) == ["keep"]


def test_unchanged_partial_weight_answers_keep():
    live = _live(
        11,
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


def _answer_change(student_attempts: int, answers=None):
    """Live A (correct), B; the file flips correctness unless *answers* is given."""
    live = _live(
        11,
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
                answers=answers or [AnswerSpec("A"), AnswerSpec("B", correct=True)],
            )
        ]
    )
    state = _state([live], student_attempts=student_attempts)
    return plan_quiz_questions(spec, state, prune=False)


def test_format_marks_answer_changes_when_students_attempted():
    reworded = [AnswerSpec("A", correct=True), AnswerSpec("B, reworded")]
    plan = _answer_change(student_attempts=2, answers=reworded)
    assert plan.questions[0].changed == ["answers"]
    lines = format_question_plan(plan)
    assert lines[0].startswith("update question 11")
    assert lines[0].endswith(ANSWER_MARKER)
    warning = question_plan_warning(plan)
    assert warning is not None
    assert "2 finished student attempt(s)" in warning

    plan = _answer_change(student_attempts=0, answers=reworded)
    lines = format_question_plan(plan)
    assert not any(ANSWER_MARKER in line for line in lines)
    assert lines[0].endswith("(answers)")
    assert question_plan_warning(plan) is None


def test_marker_skips_correctness_flip_but_flags_dropped_answer():
    # Flipping which answer is correct keeps every answer id
    plan = _answer_change(student_attempts=2)
    assert plan.questions[0].changed == ["answers"]
    assert not plan.questions[0].relinks_answers
    assert ANSWER_MARKER not in format_question_plan(plan)[0]

    # Dropping a live answer unlinks its responses
    plan = _answer_change(student_attempts=2, answers=[AnswerSpec("A", correct=True)])
    assert plan.questions[0].relinks_answers
    assert format_question_plan(plan)[0].endswith(ANSWER_MARKER)


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
        if request.method == "PUT" and "/groups/" in path:
            group_id = int(path.rsplit("/", 1)[1])
            return httpx.Response(
                200, json={"quiz_groups": [{"id": group_id, "name": "Other"}]}
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
    state = _state([_live(11), _live(12)])
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
    plan.questions.append(QuestionChange("delete", None, _live(13)))
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
        "question": {
            "question_text": "<p>new 11</p>",
            "question_name": "Question",
            "question_type": "essay_question",
            "points_possible": 0,
            "answers": [],
            **COMMENTS,
        }
    }
    assert json.loads(requests[2].content)["question"]["quiz_group_id"] == 50
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
    question = _live(11, name="Intro")
    state = _state([question])
    spec = quiz_spec_from_canvas(QUIZ, [question], "", LA)
    path = tmp_path / "quiz.toml"
    dump_quiz_file(spec, path)
    plan = plan_quiz_questions(load_quiz_file(path), state, prune=False)
    client, requests = _apply_client()
    assert apply_question_plan(client, 20, plan) == []
    assert requests == []


def test_apply_moves_questions_out_before_deleting_groups():
    """Q12 leaves "Pair", which is pruned; "Other" is updated and reordered.

    Canvas ignores ``quiz_group_id: null`` and deletes a group's questions
    with the group, so the quiz reorder must take Q12 out before the delete.
    """
    state = _state(
        [
            _live(11),
            _live(12, group_id=5),
            _live(13, group_id=5),
            _live(14, group_id=6),
            _live(15, group_id=6),
        ],
        [_group(5, "Pair", 2), _group(6, "Other", 3)],
    )
    spec = _spec(
        [
            QuestionSpec(text="<p>11</p>", id=11),
            QuestionSpec(text="<p>12</p>", id=12),
            QuestionSpec(text="<p>15</p>", id=15, group="Other"),
            QuestionSpec(text="<p>14</p>", id=14, group="Other"),
        ],
        [GroupSpec("Other", pick_count=2, points_per_item=1.5)],
    )
    plan = plan_quiz_questions(spec, state, prune=True)
    assert [g.action for g in plan.groups] == ["update", "delete"]

    client, requests = _apply_client()
    applied = apply_question_plan(client, 20, plan)

    assert [(r.method, r.url.path) for r in requests] == [
        ("PUT", f"{BASE}/questions/12"),
        ("DELETE", f"{BASE}/questions/13"),
        ("PUT", f"{BASE}/groups/6"),
        ("POST", f"{BASE}/reorder"),
        ("POST", f"{BASE}/groups/6/reorder"),
        ("DELETE", f"{BASE}/groups/5"),
        ("PUT", BASE),
    ]
    assert applied == [
        "update question 12 (group)",
        "delete question 13",
        "update group 'Other'",
        "reorder quiz",
        "reorder group 'Other'",
        "delete group 'Pair'",
        "re-save quiz",
    ]
    assert ("DELETE", f"{BASE}/questions/12") not in [
        (r.method, r.url.path) for r in requests
    ]
    assert json.loads(requests[2].content) == {
        "quiz_groups": [{"pick_count": 2, "question_points": 1.5}]
    }
    reorder = parse_qsl(requests[3].content.decode())
    assert reorder == [
        ("order[][id]", "11"),
        ("order[][type]", "question"),
        ("order[][id]", "12"),
        ("order[][type]", "question"),
        ("order[][id]", "6"),
        ("order[][type]", "group"),
    ]
    group_reorder = parse_qsl(requests[4].content.decode())
    assert [v for k, v in group_reorder if k in ("order[]", "order[][id]")] == [
        "15",
        "14",
    ]


def test_apply_missing_group_id_raises():
    plan = plan_quiz_questions(
        _spec(
            [QuestionSpec(text="<p>11</p>", id=11, group="Pair")], [GroupSpec("Pair")]
        ),
        _state([_live(11)]),
        prune=False,
    )
    plan.groups.clear()  # "Pair" is never created, so it has no Canvas id
    client, requests = _apply_client()
    with pytest.raises(QuestionApplyError, match="'Pair' has no Canvas id"):
        apply_question_plan(client, 20, plan)
    assert requests == []


def test_update_fields_leave_group_sends_no_group():
    # Canvas ignores quiz_group_id: null; the quiz reorder takes it out instead
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>11</p>", id=11),
        _live(11, group_id=5),
        changed=["group"],
    )
    assert "quiz_group_id" not in question_update_fields(change, "survey", None)


def test_update_fields_move_into_group_sends_group_id():
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>11</p>", id=11, group="Pair"),
        _live(11),
        group="Pair",
        changed=["group"],
    )
    assert question_update_fields(change, "survey", 50)["quiz_group_id"] == 50


def test_update_fields_never_sends_empty_name():
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>x</p>", name="", id=11),
        _live(11, name="Live name"),
        changed=["text"],
    )
    assert question_update_fields(change, "survey", None) == {
        "question_text": "<p>x</p>",
        "question_name": "Live name",
        "question_type": "essay_question",
        "points_possible": 0,
        "answers": [],
        **COMMENTS,
    }


def test_update_fields_default_file_name_keeps_live_name():
    change = QuestionChange(
        "update",
        QuestionSpec(text="<p>x</p>", name="Question 2", id=11),
        _live(11, name="Custom"),
        changed=["text"],
    )
    assert question_update_fields(change, "survey", None)["question_name"] == "Custom"


def test_update_fields_resend_unchanged_answers_with_ids():
    live = _live(
        11,
        question_type="multiple_choice_question",
        answers=[
            CanvasQuizAnswer(id=7, text="A", weight=100.0, comments="Right"),
            CanvasQuizAnswer(id=8, text="B", weight=0.0, html="<b>B</b>"),
        ],
    )
    spec = QuestionSpec(
        text="<p>new</p>",
        name="Pick",
        id=11,
        type="multiple_choice_question",
        points=2.0,
        answers=[AnswerSpec("A", correct=True), AnswerSpec("B")],
    )
    change = QuestionChange("update", spec, live, changed=["text", "name", "points"])
    assert question_update_fields(change, "assignment", None) == {
        "question_text": "<p>new</p>",
        "question_name": "Pick",
        "question_type": "multiple_choice_question",
        "points_possible": 2,
        "answers": [
            {
                "id": 7,
                "answer_text": "A",
                "answer_weight": 100.0,
                "answer_comment": "Right",
            },
            {
                "id": 8,
                "answer_text": "B",
                "answer_weight": 0.0,
                "answer_html": "<b>B</b>",
            },
        ],
        **COMMENTS,
    }


def test_update_fields_changed_answers_reuse_ids_by_text():
    plan = _answer_change(student_attempts=0)
    change = plan.questions[0]
    change.spec.answers.append(AnswerSpec("C"))
    fields = question_update_fields(change, "survey", None)
    assert fields["answers"] == [
        {"id": 1, "answer_text": "A", "answer_weight": 0},
        {"id": 2, "answer_text": "B", "answer_weight": 100},
        {"answer_text": "C", "answer_weight": 0},
    ]


def test_apply_reorders_even_when_layout_is_unchanged():
    state = _state([_live(11), _live(12)])
    spec = _spec(
        [QuestionSpec(text="<p>new</p>", id=11), QuestionSpec(text="<p>12</p>", id=12)]
    )
    plan = plan_quiz_questions(spec, state, prune=False)
    assert plan.order_changed is False
    client, requests = _apply_client()
    applied = apply_question_plan(client, 20, plan)
    assert applied == ["update question 11 (text)", "reorder quiz", "re-save quiz"]
    reorder = parse_qsl(requests[1].content.decode())
    assert [v for k, v in reorder if k == "order[][id]"] == ["11", "12"]


def _numerical(text: str = "<p>11</p>"):
    live = _live(
        11,
        name="Count",
        question_type="numerical_question",
        answers=[CanvasQuizAnswer(id=1, text="", weight=100.0)],
    )
    spec = QuestionSpec(
        text=text,
        name="Count",
        id=11,
        type="numerical_question",
        answers=[AnswerSpec("", correct=True)],
    )
    return live, spec


def test_unchanged_numerical_question_stays_keep():
    live, spec = _numerical()
    plan = plan_quiz_questions(_spec([spec]), _state([live]), prune=False)
    assert _actions(plan) == ["keep"]


def test_numerical_update_raises():
    live, spec = _numerical(text="<p>edited</p>")
    with pytest.raises(
        RuntimeError,
        match=r"can't safely update numerical_question questions; edit question "
        r"11 \('Count'\)",
    ):
        plan_quiz_questions(_spec([spec]), _state([live]), prune=False)


def test_update_to_unsupported_file_type_raises():
    spec = QuestionSpec(text="<p>11</p>", id=11, type="matching_question")
    with pytest.raises(RuntimeError, match="matching_question"):
        plan_quiz_questions(_spec([spec]), _state([_live(11)]), prune=False)


def test_unsupported_live_question_can_be_deleted_or_kept_as_extra():
    live, _ = _numerical()
    for prune, action in ((True, "delete"), (False, "extra")):
        plan = plan_quiz_questions(_spec([]), _state([live]), prune=prune)
        assert _actions(plan) == [action]


def test_update_fields_changed_answers_keep_matched_live_fields():
    live = _live(
        11,
        question_type="multiple_choice_question",
        answers=[
            CanvasQuizAnswer(id=1, text="A", weight=100.0, comments="Yes!"),
            CanvasQuizAnswer(
                id=2, text="B", html="<b>B</b>", comments_html="<i>No</i>"
            ),
            CanvasQuizAnswer(id=3, text="C", comments="Old C"),
        ],
    )
    spec = QuestionSpec(
        text="<p>11</p>",
        id=11,
        type="multiple_choice_question",
        answers=[AnswerSpec("A"), AnswerSpec("B", correct=True), AnswerSpec("C2")],
    )
    change = QuestionChange("update", spec, live, changed=["answers"])
    assert question_update_fields(change, "assignment", None)["answers"] == [
        {"id": 1, "answer_text": "A", "answer_weight": 0, "answer_comment": "Yes!"},
        {
            "id": 2,
            "answer_text": "B",
            "answer_weight": 100,
            "answer_html": "<b>B</b>",
            "answer_comment_html": "<i>No</i>",
        },
        {"answer_text": "C2", "answer_weight": 0},
    ]


def test_update_fields_resend_question_feedback():
    live = msgspec.structs.replace(
        _live(11),
        correct_comments="Nice",
        incorrect_comments_html="<p>Try again</p>",
        neutral_comments=None,
    )
    change = QuestionChange(
        "update", QuestionSpec(text="<p>x</p>", id=11), live, changed=["text"]
    )
    fields = question_update_fields(change, "survey", None)
    assert {name: fields[name] for name in COMMENTS} == {
        **COMMENTS,
        "correct_comments": "Nice",
        "incorrect_comments_html": "<p>Try again</p>",
    }


def test_update_fields_duplicate_answer_texts_pair_in_order():
    live = _live(
        11,
        question_type="multiple_choice_question",
        answers=[
            CanvasQuizAnswer(id=1, text="Same", weight=100.0),
            CanvasQuizAnswer(id=2, text="Same"),
        ],
    )
    spec = QuestionSpec(
        text="<p>11</p>",
        id=11,
        type="multiple_choice_question",
        answers=[
            AnswerSpec("Same"),
            AnswerSpec("Same", correct=True),
            AnswerSpec("Same"),
        ],
    )
    change = QuestionChange("update", spec, live, changed=["answers"])
    answers = question_update_fields(change, "assignment", None)["answers"]
    assert isinstance(answers, list)
    assert [a.get("id") for a in answers] == [1, 2, None]
