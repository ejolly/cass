"""``cass canvas quizzes`` — list, show, export, responses, and authoring."""

from __future__ import annotations

__docformat__ = "google"

from typing import TYPE_CHECKING

import typer

from . import _common
from ._common import console, due, err_console, pub, when

if TYPE_CHECKING:
    from ...apis.canvas.schema import CanvasQuizQuestion

quizzes_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Quizzes — list, show, export, create, update, delete.",
)


@quizzes_app.callback()
def quizzes_callback(ctx: typer.Context) -> None:
    """Quizzes; bare ``quizzes`` runs ``quizzes list``."""
    if ctx.invoked_subcommand is None:
        quizzes_list(csv_out="", save="", as_json=False)


@quizzes_app.command(name="list")
def quizzes_list(
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """List quizzes."""
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        quizzes = c.list_quizzes()

    if as_json:
        _common.emit_json_lines(quizzes)
        return

    headers = ["ID", "Title", "Type", "Questions", "Points", "Due", "Published"]
    rows = [
        [
            str(q.id),
            q.title,
            q.quiz_type,
            str(q.question_count),
            str(q.points_possible or ""),
            due(q.due_at, tz),
            pub(q.published),
        ]
        for q in quizzes
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, "Quizzes", headers, rows)
    else:
        report.render_list(headers, rows, title="Quizzes")


@quizzes_app.command(name="show")
def quizzes_show(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
    as_json: bool = _common.json_option(),
) -> None:
    """Show settings and questions for one quiz."""
    from ...actions.canvas_records import quiz_detail_record
    from ...actions.quizzes import fetch_quiz_state, strip_html
    from .. import report

    _common.reject_json_with_files(as_json, csv_out, save)
    _common.require_canvas()
    with _common.client() as c:
        tz = c.time_zone
        q = c.resolve_quiz(id_or_name)
        state = fetch_quiz_state(c, q.id, allow_statistics=True)
        questions, from_stats = state.questions, state.from_statistics
        groups = {} if as_json else {g.id: g.name for g in c.list_assignment_groups()}

    if as_json:
        _common.emit_json(quiz_detail_record(q, questions, from_statistics=from_stats))
        if from_stats:
            err_console.print(_STATS_NOTE)
        return

    attempts = "unlimited" if q.allowed_attempts == -1 else str(q.allowed_attempts)
    headers = ["Field", "Value"]
    rows = [
        ["ID", str(q.id)],
        ["Title", q.title],
        ["Type", q.quiz_type],
        ["Group", groups.get(q.assignment_group_id or 0, "")],
        ["Points", str(q.points_possible or "")],
        ["Questions", str(q.question_count)],
        ["Unlock", when(q.unlock_at, tz)],
        ["Due", when(q.due_at, tz)],
        ["Lock", when(q.lock_at, tz)],
        ["Attempts", attempts],
        ["Time Limit", f"{q.time_limit} min" if q.time_limit else ""],
        ["Hide Results", q.hide_results or ""],
        ["Scoring", q.scoring_policy],
        ["Shuffle Answers", pub(q.shuffle_answers)],
        ["One at a Time", pub(q.one_question_at_a_time)],
        ["Published", pub(q.published)],
        ["URL", q.html_url],
    ]
    title = f"Quiz: {q.title}"
    question_rows = [
        [
            str(index),
            qq.question_type,
            str(qq.points_possible or 0.0),
            strip_html(qq.question_text),
        ]
        for index, qq in enumerate(questions, 1)
    ]

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, title, headers, rows)
    else:
        report.render_list(headers, rows, title=title)
        report.render_list(
            ["#", "Type", "Points", "Text"], question_rows, title="Questions"
        )
        if from_stats:
            err_console.print(_STATS_NOTE)


_STATS_NOTE = (
    "[yellow]Read from quiz statistics: answer weights are unavailable.[/yellow]"
)


_TEXT_WIDTH = 60


@quizzes_app.command(name="questions")
def quizzes_questions(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    as_json: bool = _common.json_option(),
) -> None:
    """List a quiz's questions in quiz order, with IDs and question groups."""
    from ...actions.quizzes import fetch_quiz_state, group_name_of
    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        state = fetch_quiz_state(c, q.id, allow_statistics=True)

    if as_json:
        _common.emit_json_lines(state.questions)
    else:
        rows = [
            [str(qq.id), group_name_of(qq, state.groups), *_question_cells(qq)]
            for qq in state.questions
        ]
        report.render_list(
            ["ID", "Group", "Type", "Name", "Points", "Text"],
            rows,
            title=f"Questions: {q.title}",
        )
    if state.from_statistics:
        err_console.print(_STATS_NOTE)


def _question_cells(question: CanvasQuizQuestion) -> list[str]:
    """Type, name, points and cut plain text: one question's table cells."""
    from ...actions.quizzes import question_type_alias, strip_html

    return [
        question_type_alias(question.question_type),
        question.question_name,
        str(question.points_possible or 0.0),
        strip_html(question.question_text)[:_TEXT_WIDTH],
    ]


@quizzes_app.command(name="preview")
def quizzes_preview(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    as_json: bool = _common.json_option(),
) -> None:
    """Start a teacher preview and show the questions in the order a student sees them.

    Question groups and shuffling make each attempt differ. The preview
    submission stays on Canvas.
    """
    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        submission = c.start_quiz_preview(q.id)
        questions = c.list_submission_questions(submission.id)

    if as_json:
        _common.emit_json_lines(questions)
    else:
        rows = [
            [str(number), *_question_cells(qq)]
            for number, qq in enumerate(questions, 1)
        ]
        report.render_list(
            ["#", "Type", "Name", "Points", "Text"], rows, title=f"Preview: {q.title}"
        )
    err_console.print(
        "One attempt's draw: groups and shuffling make each attempt differ."
    )


@quizzes_app.command(name="export")
def quizzes_export(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    output: str = typer.Option(
        "", "--output", "-o", help="Write to this file instead of stdout"
    ),
) -> None:
    """Export a quiz as a quiz file (settings and questions)."""
    from pathlib import Path

    from ...actions.quizzes import (
        dump_quiz_file,
        fetch_quiz_state,
        quiz_spec_from_canvas,
    )

    _common.require_canvas()
    with _common.client() as c:
        state = fetch_quiz_state(
            c, c.resolve_quiz_id(id_or_name), allow_statistics=True
        )
        assignment_groups = {g.id: g.name for g in c.list_assignment_groups()}
        group_name = assignment_groups.get(state.quiz.assignment_group_id or 0, "")
        spec = quiz_spec_from_canvas(
            state.quiz,
            state.questions,
            group_name,
            c.time_zone,
            groups=state.groups,
        )
    text = dump_quiz_file(spec, Path(output) if output else None)
    if state.from_statistics:
        err_console.print(_STATS_NOTE)
    if output:
        console.print(f"[green]Wrote[/green] {output}")
    else:
        print(text, end="")


@quizzes_app.command(name="responses")
def quizzes_responses(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    all_attempts: bool = typer.Option(
        False, "--all-attempts", help="Every attempt, not only each student's latest"
    ),
    csv_out: str = typer.Option("", "--csv", help="Write responses to a CSV file"),
    wide: bool = typer.Option(
        False,
        "--wide",
        help="Canvas's report as is: one row per student, a column per question",
    ),
) -> None:
    """Download every student's answers to a classic quiz or survey.

    Times are in the course time zone. started_at and auto_submitted describe
    only each student's latest attempt, so they are blank while a newer attempt
    is open.
    """
    from pathlib import Path

    from ...actions.quiz_responses import RESPONSE_COLUMNS, fetch_quiz_responses
    from .. import report

    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        with err_console.status(f"Generating the Canvas report for {q.title}…"):
            if wide:
                text = c.download_quiz_report(q.id, all_versions=all_attempts)
            else:
                responses = fetch_quiz_responses(c, q, all_attempts=all_attempts)

    if wide:
        if csv_out:
            Path(csv_out).write_text(text)
            console.print(f"Wrote {csv_out}")
        else:
            print(text, end="")
        return
    if csv_out:
        report.write_csv_file(
            csv_out,
            headers=list(RESPONSE_COLUMNS),
            rows=[r.row() for r in responses],
        )
        return
    shown = ("student", "attempt", "position", "answer", "late", "auto_submitted")
    report.render_list(
        ["Student", "Attempt", "#", "Answer", "Late", "Auto-submitted"],
        [r.row(shown) for r in responses],
        title=f"Responses: {q.title}",
    )


@quizzes_app.command(name="create")
def quizzes_create(
    title: str | None = typer.Argument(
        None, help="Quiz title (omit when using --from)"
    ),
    from_file: str = typer.Option(
        "", "--from", help="Quiz file (TOML) with settings and questions"
    ),
    quiz_type: str = typer.Option(
        "assignment",
        "--type",
        help="Quiz type (practice_quiz, assignment, graded_survey, survey)",
    ),
    group: str = typer.Option("", "--group", help="Assignment group name"),
    points: float | None = typer.Option(
        None, "--points", help="Points (graded_survey only)"
    ),
    due: str = typer.Option(
        "", "--due", help="Due (YYYY-MM-DD HH:MM in course time, or ISO 8601)"
    ),
    unlock: str = typer.Option(
        "", "--unlock", help="Unlock time (course time or ISO 8601)"
    ),
    lock: str = typer.Option("", "--lock", help="Lock time (course time or ISO 8601)"),
    attempts: int = typer.Option(
        1, "--attempts", help="Allowed attempts (-1 = unlimited)"
    ),
    time_limit: int = typer.Option(
        0, "--time-limit", help="Time limit in minutes (0 = none)"
    ),
    description: str = typer.Option("", "--description", "-d", help="HTML description"),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately"),
    create_groups: bool = typer.Option(
        False, "--create-groups", help="Create a missing assignment group"
    ),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Create a quiz from a quiz file (--from) or as an empty placeholder."""
    from pathlib import Path

    from ...actions.quizzes import QuizSpec, load_quiz_file

    _common.require_canvas()
    if bool(from_file) == bool(title):
        err_console.print("[red]Give a title or --from FILE, not both.[/red]")
        raise typer.Exit(code=1)
    if from_file:
        spec = load_quiz_file(Path(from_file))
    else:
        if points is not None and quiz_type != "graded_survey":
            err_console.print(
                "[red]--points only applies to --type graded_survey.[/red]"
            )
            raise typer.Exit(code=1)
        spec = QuizSpec(
            title=title or "",
            quiz_type=quiz_type,
            group=group,
            points=points,
            description=description,
            unlock_at=unlock,
            due_at=due,
            lock_at=lock,
            attempts=attempts,
            time_limit=time_limit,
        )
    if publish:
        spec.published = True
    with _common.client(dry_run=dry_run) as c:
        group_id = _common.group_id_for(c, spec.group, create=create_groups)
        q = c.create_quiz(spec, assignment_group_id=group_id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(
        f"[green]Created quiz:[/green] {q.title} "
        f"(id={q.id}, {q.question_count} questions)"
    )


@quizzes_app.command(name="update")
def quizzes_update(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    from_file: str = typer.Option(
        ..., "--from", help="Quiz file with the desired settings"
    ),
    dry_run: bool = _common.dry_run_option(),
    questions: bool = typer.Option(
        False,
        "--questions",
        help="Also reconcile questions and question groups (dry run unless --apply)",
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the changes"),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Delete questions and groups not in the file (with --questions)",
    ),
) -> None:
    """Update a quiz's settings from a quiz file; a dry run unless --apply.

    Only the settings the file sets are compared and sent. Questions are
    untouched unless --questions is given.
    """
    import click

    if prune and not questions:
        raise click.UsageError("--prune needs --questions.")
    if apply and dry_run:
        raise click.UsageError("--apply and --dry-run cannot be combined.")
    if questions:
        _update_with_questions(id_or_name, from_file, apply=apply, prune=prune)
        return

    from pathlib import Path

    from ...actions.quizzes import load_quiz_file, quiz_settings_diff

    _common.require_canvas()
    spec = load_quiz_file(Path(from_file))
    with _common.client(dry_run=not apply) as c:
        q = c.resolve_quiz(id_or_name)
        group_id = _common.group_id_for(c, spec.group, create=False)
        changes = quiz_settings_diff(spec, q, c.time_zone, group_id=group_id)
        if not changes:
            err_console.print(f"[dim]No changes for {q.title}.[/dim]")
            return
        c.update_quiz(q.id, changes)
    detail = ", ".join(f"{k}: {v!r}" for k, v in changes.items())
    if not apply:
        console.print(f"update settings ({detail})", markup=False, highlight=False)
        _common.print_plan(c)
        err_console.print("Dry run — use --apply to send these changes.")
        return
    console.print(f"[green]Updated:[/green] {q.title} ({detail})")


def _update_with_questions(
    id_or_name: str, from_file: str, *, apply: bool, prune: bool
) -> None:
    """Settings plus question reconciliation; a dry run unless *apply*."""
    from pathlib import Path

    from ...actions.quiz_plan import (
        apply_question_plan,
        format_question_plan,
        plan_quiz_questions,
        plan_summary,
        question_plan_warning,
    )
    from ...actions.quizzes import (
        fetch_quiz_state,
        load_quiz_file,
        quiz_settings_diff,
    )

    _common.require_canvas()
    spec = load_quiz_file(Path(from_file))
    with _common.client(dry_run=not apply) as c:
        q = c.resolve_quiz(id_or_name)
        state = fetch_quiz_state(c, q.id, include_submissions=True)
        plan = plan_quiz_questions(spec, state, prune=prune)
        group_id = _common.group_id_for(c, spec.group, create=False)
        changes = quiz_settings_diff(spec, q, c.time_zone, group_id=group_id)

        warning = question_plan_warning(plan)
        if warning:
            err_console.print(warning, markup=False, highlight=False, soft_wrap=True)
        lines = format_question_plan(plan)
        if changes:
            detail = ", ".join(f"{k}: {v!r}" for k, v in changes.items())
            lines.insert(0, f"{'update':<7}settings  ({detail})")
        for line in lines:
            console.print(line, markup=False, highlight=False, soft_wrap=True)

        if changes:
            c.update_quiz(q.id, changes)
        apply_question_plan(c, q.id, plan)
    if not apply:
        _common.print_plan(c)
        if c.planned_requests:
            err_console.print("Dry run — use --apply to send these changes.")
        return
    if not changes and not plan.has_changes:
        err_console.print(f"[dim]No changes for {q.title}.[/dim]")
        return
    console.print(f"[green]Updated:[/green] {q.title} ({plan_summary(plan)})")


@quizzes_app.command(name="publish")
def quizzes_publish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Publish a quiz."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        q = c.resolve_quiz(id_or_name)
        c.publish("quizzes", q.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[green]Published:[/green] {q.title}")


@quizzes_app.command(name="unpublish")
def quizzes_unpublish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Unpublish a quiz."""
    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        q = c.resolve_quiz(id_or_name)
        c.unpublish("quizzes", q.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[yellow]Unpublished:[/yellow] {q.title}")


@quizzes_app.command(name="delete")
def quizzes_delete(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Delete a quiz."""
    from ..prompts import confirm

    _common.require_canvas()
    with _common.client(dry_run=dry_run) as c:
        q = c.resolve_quiz(id_or_name)
        confirm(f"Delete quiz '{q.title}'?", yes=yes, dry_run=dry_run)
        c.delete_quiz(q.id)
    if dry_run:
        _common.print_plan(c)
        return
    console.print(f"[red]Deleted:[/red] {q.title}")
