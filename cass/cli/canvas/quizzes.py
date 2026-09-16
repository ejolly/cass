"""``cass canvas quizzes`` — list, show, export, create, update, publish, delete."""

from __future__ import annotations

__docformat__ = "google"

import typer

from . import _common
from ._common import console, due, pub, when

quizzes_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=False,
    help="Quizzes — list, create, publish, delete.",
)


@quizzes_app.callback()
def quizzes_callback(
    ctx: typer.Context,
    quiz_id: str = typer.Option(
        "", "--id", help="Quiz ID or title for settings and questions"
    ),
    csv_out: str = typer.Option("", "--csv", help="Export as CSV file"),
    save: str = typer.Option("", "--save", help="Save output as markdown file"),
) -> None:
    """List quizzes, or show settings and questions for one quiz."""
    if ctx.invoked_subcommand is not None:
        return
    _common.require_canvas()

    from ...actions.quizzes import strip_html
    from .. import report

    question_rows: list[list[str]] = []
    from_stats = False
    with _common.client() as c:
        tz = c.time_zone
        if quiz_id:
            q = c.resolve_quiz(quiz_id)
            questions, from_stats = c.list_quiz_questions(q.id)
            groups = {g.id: g.name for g in c.list_assignment_groups()}
            attempts = (
                "unlimited" if q.allowed_attempts == -1 else str(q.allowed_attempts)
            )
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
                    str(qq.position or index),
                    qq.question_type,
                    str(qq.points_possible or 0.0),
                    strip_html(qq.question_text),
                ]
                for index, qq in enumerate(questions, 1)
            ]
        else:
            quizzes = c.list_quizzes()
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
            title = "Quizzes"

    if csv_out:
        report.write_csv_file(csv_out, headers=headers, rows=rows)
    elif save:
        report.save_markdown(save, title, headers, rows)
    else:
        report.render_list(headers, rows, title=title)
        if quiz_id:
            report.render_list(
                ["#", "Type", "Points", "Text"], question_rows, title="Questions"
            )
            if from_stats:
                console.print(_STATS_NOTE)


_STATS_NOTE = (
    "[yellow]Read from quiz statistics: answer weights are unavailable.[/yellow]"
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

    from ...actions.quizzes import dump_quiz_file, quiz_spec_from_canvas

    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        questions, from_stats = c.list_quiz_questions(q.id)
        groups = {g.id: g.name for g in c.list_assignment_groups()}
        group_name = groups.get(q.assignment_group_id or 0, "")
        spec = quiz_spec_from_canvas(q, questions, group_name, c.time_zone)
    text = dump_quiz_file(spec, Path(output) if output else None)
    if from_stats:
        console.print(_STATS_NOTE)
    if output:
        console.print(f"[green]Wrote[/green] {output}")
    else:
        print(text, end="")


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
) -> None:
    """Create a quiz from a quiz file (--from) or as an empty placeholder."""
    from pathlib import Path

    from ...actions.quizzes import QuizSpec, load_quiz_file

    _common.require_canvas()
    if bool(from_file) == bool(title):
        console.print("[red]Give a title or --from FILE, not both.[/red]")
        raise typer.Exit(code=1)
    if from_file:
        spec = load_quiz_file(Path(from_file))
    else:
        if points is not None and quiz_type != "graded_survey":
            console.print("[red]--points only applies to --type graded_survey.[/red]")
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
    with _common.client() as c:
        group_id = _common.group_id_for(c, spec.group, create=create_groups)
        q = c.create_quiz(spec, assignment_group_id=group_id)
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
) -> None:
    """Update a quiz's settings from a quiz file (questions are not touched)."""
    from pathlib import Path

    from ...actions.quizzes import load_quiz_file, quiz_settings_diff

    _common.require_canvas()
    spec = load_quiz_file(Path(from_file))
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        group_id = _common.group_id_for(c, spec.group, create=False)
        changes = quiz_settings_diff(spec, q, c.time_zone, group_id=group_id)
        if not changes:
            console.print(f"[dim]No changes for {q.title}.[/dim]")
            return
        c.update_quiz(q.id, changes)
    detail = ", ".join(f"{k}: {v!r}" for k, v in changes.items())
    console.print(f"[green]Updated:[/green] {q.title} ({detail})")


@quizzes_app.command(name="publish")
def quizzes_publish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Publish a quiz."""
    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        c.publish("quizzes", q.id)
    console.print(f"[green]Published:[/green] {q.title}")


@quizzes_app.command(name="unpublish")
def quizzes_unpublish(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
) -> None:
    """Unpublish a quiz."""
    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        c.unpublish("quizzes", q.id)
    console.print(f"[yellow]Unpublished:[/yellow] {q.title}")


@quizzes_app.command(name="delete")
def quizzes_delete(
    id_or_name: str = typer.Argument(..., help="Quiz ID or title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a quiz."""
    _common.require_canvas()
    with _common.client() as c:
        q = c.resolve_quiz(id_or_name)
        if not yes and not typer.confirm(f"Delete quiz '{q.title}'?"):
            raise typer.Abort()
        c.delete_quiz(q.id)
    console.print(f"[red]Deleted:[/red] {q.title}")
