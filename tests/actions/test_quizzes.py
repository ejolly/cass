"""Tests for quiz spec types, quiz files, and settings diffs."""

from __future__ import annotations

__docformat__ = "google"

from typing import Any
from unittest.mock import MagicMock

import pytest

from cass.actions.quizzes import (
    AnswerSpec,
    GroupSpec,
    QuestionSpec,
    QuizSpec,
    QuizState,
    canvas_layout,
    dump_quiz_file,
    fetch_quiz_state,
    file_layout,
    group_members,
    load_quiz_file,
    ordered_questions,
    question_form_fields,
    quiz_form_fields,
    quiz_settings_diff,
    quiz_spec_from_canvas,
    strip_html,
    sync_quizzes,
)
from cass.apis.canvas.schema import (
    CanvasQuiz,
    CanvasQuizAnswer,
    CanvasQuizGroup,
    CanvasQuizQuestion,
    CanvasQuizSubmission,
    CanvasStudentResponse,
)

LA = "America/Los_Angeles"

SURVEY_TOML = """\
title = "09-25 Participation Survey"
type = "graded_survey"
group = "Attendance & Participation"
points = 2
unlock_at = "2026-09-25 14:15"
due_at = "2026-09-25 17:00"
attempts = 1
hide_results = "always"

[[questions]]
type = "essay"
text = "<p>What are you most hoping to get out of this course?</p>"

[[questions]]
type = "multiple_choice"
text = "<p>Which gamble?</p>"
points = 1
answers = [{ text = "A", correct = true }, { text = "B" }]
"""


def _write(tmp_path, text, name="quiz.toml"):
    path = tmp_path / name
    path.write_text(text)
    return path


class TestLoadQuizFile:
    def test_loads_settings_and_questions(self, tmp_path):
        spec = load_quiz_file(_write(tmp_path, SURVEY_TOML))
        assert spec.title == "09-25 Participation Survey"
        assert spec.quiz_type == "graded_survey"
        assert spec.points == 2
        assert spec.hide_results == "always"
        assert spec.scoring_policy == "keep_highest"
        assert spec.lock_at == ""
        assert [q.type for q in spec.questions] == [
            "essay_question",
            "multiple_choice_question",
        ]
        assert spec.questions[0].points is None
        assert spec.questions[1].answers == [
            AnswerSpec("A", True),
            AnswerSpec("B", False),
        ]

    def test_unknown_question_type_passes_through(self, tmp_path):
        toml = (
            'title = "Q"\ntype = "assignment"\n'
            '[[questions]]\ntype = "calculated_question"\ntext = "x"\n'
        )
        spec = load_quiz_file(_write(tmp_path, toml))
        assert spec.questions[0].type == "calculated_question"

    @pytest.mark.parametrize(
        "toml, message",
        [
            ('type = "survey"\n', "missing required key 'title'"),
            ('title = "Q"\n', "missing required key 'type'"),
            (
                'title = "Q"\ntype = "assignment"\nattemps = 2\n',
                "unknown key 'attemps' (did you mean 'attempts'?)",
            ),
            (
                'title = "Q"\ntype = "assignment"\nhide_results = "never"\n',
                "hide_results",
            ),
            (
                'title = "Q"\ntype = "assignment"\nscoring_policy = "avg"\n',
                "scoring_policy",
            ),
            ('title = "Q"\ntype = "assignment"\npoints = 2\n', "points"),
            ('title = "Q"\ntype = "quizz"\n', "type"),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntype = "multiple_choice"\ntext = "x"\n',
                "answers",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntype = "multiple_choice"\ntext = "x"\n'
                'answers = [{ text = "A", correct = true }, '
                '{ text = "B", correct = true }]\n',
                "one correct answer",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntext = "x"\nponts = 1\n',
                "unknown key 'ponts'",
            ),
            (
                'title = "Q"\ntype = "assignment"\n[[groups]]\npick_count = 1\n',
                "missing required key 'name' in group 1",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[groups]]\nname = "A"\n[[groups]]\nname = "A"\n',
                "two [[groups]] are named 'A'",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntext = "x"\ngroup = "Z"\n',
                "group 'Z' in question 1 is not declared in [[groups]]",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[groups]]\nname = "A"\n'
                '[[questions]]\ntext = "x"\ngroup = "A"\n'
                '[[questions]]\ntext = "y"\n'
                '[[questions]]\ntext = "z"\ngroup = "A"\n',
                "questions in group 'A' must be contiguous (question 3)",
            ),
            (
                'title = "Q"\ntype = "assignment"\n'
                '[[questions]]\ntext = "x"\nid = 5\n'
                '[[questions]]\ntext = "y"\nid = 5\n',
                "id 5 appears on two questions (question 2)",
            ),
            (
                'title = "Q"\ntype = "assignment"\n[[groups]]\nname = "A"\n',
                "group 'A' has no questions",
            ),
        ],
        ids=[
            "no-title",
            "no-type",
            "typo",
            "hide",
            "scoring",
            "points",
            "quiz-type",
            "no-answers",
            "two-correct",
            "q-typo",
            "no-group-name",
            "dup-group",
            "undeclared",
            "noncontiguous",
            "dup-id",
            "empty-group",
        ],
    )
    def test_validation(self, tmp_path, toml, message):
        path = _write(tmp_path, toml)
        with pytest.raises(SystemExit) as exc:
            load_quiz_file(path)
        assert str(path) in str(exc.value)
        assert message in str(exc.value)

    def test_loads_groups_and_ids(self, tmp_path):
        toml = (
            'title = "Q"\ntype = "survey"\n'
            '[[groups]]\nname = "Pair"\npick_count = 1\n'
            '[[questions]]\ntext = "a"\nid = 11\n'
            '[[questions]]\ntext = "b"\ngroup = "Pair"\n'
            '[[questions]]\ntext = "c"\ngroup = "Pair"\nid = 12\n'
            '[[questions]]\ntext = "d"\n'
        )
        spec = load_quiz_file(_write(tmp_path, toml))
        assert spec.groups == [GroupSpec("Pair", 1, None)]
        assert [q.group for q in spec.questions] == ["", "Pair", "Pair", ""]
        assert [q.id for q in spec.questions] == [11, None, 12, None]

    def test_default_names_load_empty(self, tmp_path):
        toml = 'title = "Q"\ntype = "survey"\n' + "".join(
            f'[[questions]]\ntext = "x"\nname = "{n}"\n'
            for n in ("Question", "Question 3", "Question one", "Intro")
        )
        spec = load_quiz_file(_write(tmp_path, toml))
        assert [q.name for q in spec.questions] == ["", "", "Question one", "Intro"]

    def test_file_without_groups_unchanged(self, tmp_path):
        spec = load_quiz_file(_write(tmp_path, SURVEY_TOML))
        assert spec.groups == []
        assert all(q.group == "" for q in spec.questions)
        assert all(q.id is None for q in spec.questions)

    def test_file_layout_and_members(self):
        def q(group=""):
            return QuestionSpec(text="x", group=group)

        spec = QuizSpec(
            title="Q",
            quiz_type="survey",
            groups=[GroupSpec("Pair")],
            questions=[q(), q("Pair"), q("Pair"), q()],
        )
        assert file_layout(spec) == [
            ("question", 0),
            ("group", "Pair"),
            ("question", 3),
        ]
        assert group_members(spec) == {"Pair": [1, 2]}


def test_question_form_fields():
    fields = question_form_fields(QuestionSpec(text="x"), "survey")
    assert fields == {
        "question_name": "Question",
        "question_text": "x",
        "question_type": "essay_question",
        "points_possible": 0,
    }


class TestDumpQuizFile:
    def test_dump_round_trips_groups_and_ids(self, tmp_path):
        spec = QuizSpec(
            title="Q",
            quiz_type="survey",
            groups=[GroupSpec("Pair", 2, 1.5), GroupSpec("Solo")],
            questions=[
                QuestionSpec(text="a", id=7, name="Intro"),
                QuestionSpec(text="b", group="Pair", id=8),
                QuestionSpec(text="c", group="Pair"),
                QuestionSpec(text="d", group="Solo"),
            ],
        )
        text = dump_quiz_file(spec, None)
        again = load_quiz_file(_write(tmp_path, text))
        assert again.groups == spec.groups
        assert again.questions == spec.questions

    def test_round_trip(self, tmp_path):
        spec = load_quiz_file(_write(tmp_path, SURVEY_TOML))
        text = dump_quiz_file(spec, None)
        again = load_quiz_file(_write(tmp_path, text, "again.toml"))
        assert again == spec

    def test_multiline_text_round_trips(self, tmp_path):
        spec = QuizSpec(
            title="Q",
            quiz_type="survey",
            questions=[QuestionSpec(text='<p>line one</p>\n<p>"quoted"</p>')],
        )
        text = dump_quiz_file(spec, None)
        assert load_quiz_file(_write(tmp_path, text)) == spec

    def test_writes_file(self, tmp_path):
        spec = QuizSpec(title="Q", quiz_type="survey")
        out = tmp_path / "out.toml"
        dump_quiz_file(spec, out)
        assert 'title = "Q"' in out.read_text()


class TestQuizSpecFromCanvas:
    def test_maps_fields_and_course_times(self):
        quiz = CanvasQuiz(
            id=1,
            title="S",
            quiz_type="graded_survey",
            points_possible=2.0,
            allowed_attempts=1,
            hide_results="always",
            unlock_at="2026-09-25T21:15:00Z",
            due_at="2026-09-26T00:00:00Z",
            assignment_group_id=9,
            published=True,
        )
        questions = [
            CanvasQuizQuestion(
                id=5,
                question_name="Question 1",
                question_type="essay_question",
                question_text="<p>Hi</p>",
                position=1,
            ),
            CanvasQuizQuestion(
                id=6,
                question_name="Pick",
                question_type="multiple_choice_question",
                question_text="<p>?</p>",
                points_possible=1.0,
                position=2,
                answers=[
                    CanvasQuizAnswer(id=1, text="A", weight=100),
                    CanvasQuizAnswer(id=2, text="B", weight=0),
                ],
            ),
        ]
        spec = quiz_spec_from_canvas(quiz, questions, "Participation", LA)
        assert spec.group == "Participation"
        assert spec.points == 2.0
        assert spec.unlock_at == "2026-09-25 14:15"
        assert spec.due_at == "2026-09-25 17:00"
        assert spec.lock_at == ""
        assert spec.published is True
        assert spec.questions[0].name == ""  # default name is dropped
        assert spec.questions[1].name == "Pick"
        assert spec.questions[1].answers[0].correct is True

    def test_points_only_for_graded_survey(self):
        quiz = CanvasQuiz(id=1, title="Q", quiz_type="assignment", points_possible=3.0)
        assert quiz_spec_from_canvas(quiz, [], "", LA).points is None


def _live(**overrides: Any) -> CanvasQuiz:
    base: dict[str, Any] = {
        "id": 1,
        "title": "S",
        "quiz_type": "graded_survey",
        "points_possible": 2.0,
        "allowed_attempts": 1,
        "hide_results": "always",
        "unlock_at": "2026-09-25T21:15:00Z",
        "due_at": "2026-09-26T00:00:00Z",
        "lock_at": None,
        "time_limit": None,
        "scoring_policy": "keep_highest",
        "published": False,
        "assignment_group_id": 9,
    }
    base.update(overrides)
    return CanvasQuiz(**base)


def _spec(**overrides: Any) -> QuizSpec:
    base: dict[str, Any] = {
        "title": "S",
        "quiz_type": "graded_survey",
        "points": 2,
        "attempts": 1,
        "hide_results": "always",
        "unlock_at": "2026-09-25 14:15",
        "due_at": "2026-09-25 17:00",
    }
    base.update(overrides)
    return QuizSpec(**base)


class TestQuizSettingsDiff:
    def test_equal_is_empty(self):
        assert quiz_settings_diff(_spec(), _live(), LA, group_id=9) == {}

    def test_offset_only_difference_is_not_a_change(self):
        spec = _spec(due_at="2026-09-25T17:00:00-07:00")
        assert quiz_settings_diff(spec, _live(), LA) == {}

    def test_each_field_type(self):
        spec = _spec(
            due_at="2026-09-25 18:00",
            attempts=2,
            hide_results="",
            published=True,
            description="<p>x</p>",
            time_limit=5,
        )
        diff = quiz_settings_diff(spec, _live(), LA, group_id=10)
        assert diff == {
            "description": "<p>x</p>",
            "due_at": "2026-09-25T18:00:00-07:00",
            "allowed_attempts": 2,
            "time_limit": 5,
            "hide_results": "",
            "published": True,
            "assignment_group_id": 10,
        }

    def test_form_fields_and_diff_share_names(self):
        fields = quiz_form_fields(_spec(), LA, assignment_group_id=9)
        assert fields["due_at"] == "2026-09-25T17:00:00-07:00"
        assert fields["points_possible"] == 2
        assert fields["time_limit"] == ""
        assert set(quiz_settings_diff(_spec(title="T"), _live(), LA)) == {"title"}


class TestSyncQuizzes:
    def test_create_update_skip(self):
        live = CanvasQuiz(
            id=1, title="Existing", quiz_type="survey", allowed_attempts=1
        )
        client = MagicMock()
        client.list_quizzes.return_value = [live]
        specs = [
            QuizSpec(title="New", quiz_type="survey", group="Participation"),
            QuizSpec(title="Existing", quiz_type="survey", attempts=2),
            QuizSpec(title="Existing", quiz_type="survey"),
        ]
        rows = sync_quizzes(client, specs, {"participation": 9}, LA)
        assert [r[0] for r in rows] == ["create", "update", "skip"]
        assert "allowed_attempts: 2" in rows[1][2]
        client.create_quiz.assert_called_once_with(specs[0], assignment_group_id=9)
        client.update_quiz.assert_called_once_with(1, {"allowed_attempts": 2})

    def test_sync_quizzes_reports_created(self):
        new_quiz = CanvasQuiz(id=-1, title="New")
        client = MagicMock()
        client.list_quizzes.return_value = []
        client.create_quiz.return_value = new_quiz
        created: list[CanvasQuiz] = []

        rows = sync_quizzes(
            client, [QuizSpec(title="New", quiz_type="survey")], {}, LA, created=created
        )

        assert [r[0] for r in rows] == ["create"]
        assert created == [new_quiz]

    def test_sync_create_ignores_ids(self):
        import httpx

        from cass.apis.canvas.client import CanvasClient

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith("/quizzes"):
                return httpx.Response(200, json=[])
            return httpx.Response(500, json={"message": "unexpected request"})

        client = CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
            time_zone="America/Los_Angeles",
            dry_run=True,
        )
        spec = QuizSpec(
            title="New",
            quiz_type="survey",
            questions=[QuestionSpec(text="a", id=99), QuestionSpec(text="b")],
        )
        rows = sync_quizzes(client, [spec], {}, LA)
        assert [r[0] for r in rows] == ["create"]
        question_posts = [
            r.body["question"]
            for r in client.planned_requests
            if r.path.endswith("/questions")
        ]
        assert len(question_posts) == 2
        assert all("id" not in body for body in question_posts)


def test_strip_html():
    assert strip_html("<p>What &amp; why?</p>\n<ul><li>a</li></ul>") == "What & why? a"
    assert strip_html("<p>What are you <b>hoping</b>?</p>") == "What are you hoping?"


def _ordered_quiz():
    """Q11, group 5 "Pair" (position 2) holding Q12 then Q13, Q14.

    Questions come in Canvas's list order with null positions, as the
    questions API returns them.
    """
    quiz = CanvasQuiz(id=20, title="T", quiz_type="assignment")
    group = CanvasQuizGroup(
        id=5, quiz_id=20, name="Pair", pick_count=1, question_points=2.0, position=2
    )

    def question(qid, group_id=None, name="Question"):
        return CanvasQuizQuestion(
            id=qid,
            question_name=name,
            question_text=f"<p>{qid}</p>",
            question_type="essay_question",
            points_possible=1.0,
            quiz_group_id=group_id,
        )

    questions = [question(11), question(12, 5), question(13, 5), question(14)]
    return quiz, group, questions


def _layout_group(gid, position):
    return CanvasQuizGroup(id=gid, quiz_id=20, name=f"G{gid}", position=position)


def _layout_question(qid, group_id=None):
    return CanvasQuizQuestion(id=qid, quiz_group_id=group_id)


class TestQuizState:
    def test_canvas_layout_puts_group_at_its_position(self):
        _, group, questions = _ordered_quiz()
        assert canvas_layout(questions, [group]) == [
            ("question", 11),
            ("group", 5),
            ("question", 14),
        ]
        assert [q.id for q in ordered_questions(questions, [group])] == [11, 12, 13, 14]

    def test_canvas_layout_from_probe(self):
        # Live probe after reordering to [C, Pair(First, Added), B, D]: the API
        # lists First, C, Added, B, D, every position null; the group GET says 2.
        first, c, added, b, d = 1, 2, 3, 4, 5
        pair = _layout_group(9, 2)
        questions = [
            _layout_question(first, 9),
            _layout_question(c),
            _layout_question(added, 9),
            _layout_question(b),
            _layout_question(d),
        ]
        assert canvas_layout(questions, [pair]) == [
            ("question", c),
            ("group", 9),
            ("question", b),
            ("question", d),
        ]
        assert [q.id for q in ordered_questions(questions, [pair])] == [
            c,
            first,
            added,
            b,
            d,
        ]

    def test_canvas_layout_ignores_question_positions(self):
        questions = [
            CanvasQuizQuestion(id=1, position=3),
            CanvasQuizQuestion(id=2, position=1),
        ]
        assert canvas_layout(questions, []) == [("question", 1), ("question", 2)]

    def test_canvas_layout_clamps_and_resolves_group_collisions(self):
        questions = [
            _layout_question(1),
            _layout_question(10, 7),
            _layout_question(11, 8),
        ]
        # Both groups claim position 9 (past the 3 slots): clamp to 3, then the
        # later id takes the nearest free slot before it.
        groups = [_layout_group(8, 9), _layout_group(7, 9)]
        assert canvas_layout(questions, groups) == [
            ("question", 1),
            ("group", 8),
            ("group", 7),
        ]
        # Same position: lower id first, the other moves to the next free slot.
        groups = [_layout_group(8, 1), _layout_group(7, 1)]
        assert canvas_layout(questions, groups) == [
            ("group", 7),
            ("group", 8),
            ("question", 1),
        ]

    def test_canvas_layout_puts_null_position_group_last(self):
        questions = [_layout_question(10, 7), _layout_question(1), _layout_question(2)]
        assert canvas_layout(questions, [_layout_group(7, None)]) == [
            ("question", 1),
            ("question", 2),
            ("group", 7),
        ]

    def test_export_writes_ids_groups_in_order(self):
        quiz, group, questions = _ordered_quiz()
        spec = quiz_spec_from_canvas(quiz, questions, "", LA, groups=[group])
        assert [q.id for q in spec.questions] == [11, 12, 13, 14]
        assert [q.group for q in spec.questions] == ["", "Pair", "Pair", ""]
        assert spec.groups == [GroupSpec("Pair", 1, 2.0)]

    def test_export_load_round_trip(self, tmp_path):
        quiz, group, questions = _ordered_quiz()
        spec = quiz_spec_from_canvas(quiz, questions, "", LA, groups=[group])
        path = tmp_path / "q.toml"
        dump_quiz_file(spec, path)
        loaded = load_quiz_file(path)
        assert loaded.questions == spec.questions
        assert loaded.groups == spec.groups

    def test_export_duplicate_group_names_raise(self):
        quiz, group, questions = _ordered_quiz()
        twin = CanvasQuizGroup(id=6, quiz_id=group.quiz_id, name=group.name)
        questions[3].quiz_group_id = 6
        with pytest.raises(RuntimeError, match="two question groups named 'Pair'"):
            quiz_spec_from_canvas(quiz, questions, "", LA, groups=[group, twin])

    def test_export_blanks_default_names(self):
        quiz = CanvasQuiz(id=1, title="Q", quiz_type="assignment")
        questions = [
            CanvasQuizQuestion(id=i, question_name=name, position=i)
            for i, name in enumerate(["Question", "Question 7", "Intro"], 1)
        ]
        spec = quiz_spec_from_canvas(quiz, questions, "", LA)
        assert [q.name for q in spec.questions] == ["", "", "Intro"]

    def _client(self, fallback=False):
        quiz, group, questions = _ordered_quiz()
        client = MagicMock()
        client.get_quiz.return_value = quiz
        client.list_quiz_questions.return_value = (questions, fallback)
        client.get_question_group.return_value = group
        return client

    def test_fetch_quiz_state_reads_each_group_once(self):
        client = self._client()
        state = fetch_quiz_state(client, 20)
        client.get_question_group.assert_called_once_with(20, 5)
        assert isinstance(state, QuizState)
        assert [q.id for q in state.questions] == [11, 12, 13, 14]
        assert [g.id for g in state.groups] == [5]

    def test_fetch_quiz_state_statistics_fallback_raises(self):
        client = self._client(fallback=True)
        with pytest.raises(RuntimeError, match="statistics"):
            fetch_quiz_state(client, 20)
        assert fetch_quiz_state(client, 20, allow_statistics=True).from_statistics

    def test_fetch_quiz_state_counts_finished_student_attempts(self):
        client = self._client()
        client.list_quiz_submissions.return_value = [
            CanvasQuizSubmission(id=1, user_id=1, workflow_state="complete"),
            CanvasQuizSubmission(id=2, user_id=2, workflow_state="pending_review"),
            CanvasQuizSubmission(id=3, user_id=3, workflow_state="untaken"),
            CanvasQuizSubmission(id=4, user_id=9, workflow_state="complete"),
        ]
        client.list_students.return_value = [
            CanvasStudentResponse(id=i, name=f"S{i}") for i in (1, 2, 3)
        ]
        state = fetch_quiz_state(client, 20, include_submissions=True)
        assert state.student_attempts == 2

        plain = self._client()
        fetch_quiz_state(plain, 20)
        plain.list_quiz_submissions.assert_not_called()
        plain.list_students.assert_not_called()
