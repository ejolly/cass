"""Drift test: every ``cass …`` command in the packaged skill exists in the CLI."""

from __future__ import annotations

__docformat__ = "google"

import re
import shlex
from importlib.resources import files
from pathlib import Path

import click
import typer.main

from cass.cli import app

FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
INLINE = re.compile(r"`([^`\n]+)`")
CASS_START = re.compile(r"(?:^|(?<=[\s($]))cass(?=\s|$)")
SHELL_STOP = re.compile(r"^(\||\|\||&&|;|\d?>>?.*|<|#.*)$")
GROUP_PLACEHOLDER = re.compile(r"^(<.*>|\.\.\.|…)$")


def skill_paths() -> list[Path]:
    root = Path(str(files("cass") / "skill"))
    return sorted(root.rglob("*.md"))


def invocations(text: str) -> list[str]:
    """Return every ``cass …`` command written in code in a Markdown document.

    Fenced blocks are read line by line, joining lines that end in ``\\``.
    Inline code spans are read from the text outside fenced blocks.
    """
    snippets: list[str] = []
    for block in FENCE.findall(text):
        snippets.extend(block.replace("\\\n", " ").splitlines())
    snippets.extend(INLINE.findall(FENCE.sub("", text)))

    found: list[str] = []
    for snippet in snippets:
        starts = [m.start() for m in CASS_START.finditer(snippet)]
        ends = [*starts[1:], len(snippet)]
        for start, end in zip(starts, ends[: len(starts)], strict=True):
            found.append(snippet[start:end].strip())
    return found


def _find_option(command: click.Command, name: str) -> click.Parameter | None:
    for param in command.params:
        if name in param.opts or name in param.secondary_opts:
            return param
    return None


# Options a ``cass query`` dataset rejects at run time.
QUERY_DATASET_REJECTS = {"gradebook": {"--where", "--order"}}


def _argument_slots(command: click.Command) -> float:
    """How many positional words a leaf command accepts."""
    slots = 0.0
    for param in command.params:
        if isinstance(param, click.Argument):
            slots += float("inf") if param.nargs == -1 else param.nargs
    return slots


def check_invocation(invocation: str, root: click.Command) -> list[str]:
    """Return the problems found walking ``invocation`` down the command tree.

    Root options (``--config``, ``--debug``) count only before the first
    subcommand. A group's next word must name a subcommand (``<angle>`` and
    ``…`` placeholders aside); a leaf command's positional words, CAPS
    placeholders included, must fit its arguments.
    """
    try:
        words = shlex.split(invocation, comments=True)
    except ValueError as exc:
        return [f"{invocation!r}: cannot parse ({exc})"]

    def problem(message: str) -> str:
        return f"{invocation!r}: {' '.join(path)} {message}"

    problems: list[str] = []
    command = root
    path = ["cass"]
    positionals: list[str] = []
    options: set[str] = set()
    skip_value = False
    for word in words[1:]:
        if skip_value:
            skip_value = False
            continue
        if SHELL_STOP.match(word):
            break
        if word.startswith("-") and word != "-":
            name, has_value = word.split("=", 1)[0], "=" in word
            option = _find_option(command, name)
            if option is None:
                problems.append(problem(f"has no {name}"))
                continue
            options.add(name)
            if isinstance(option, click.Option) and not (
                option.is_flag or option.count or has_value
            ):
                skip_value = True
            continue
        if isinstance(command, click.Group):
            if GROUP_PLACEHOLDER.match(word):
                continue
            sub = command.commands.get(word)
            if sub is None:
                problems.append(problem(f"has no {word!r}"))
                break
            command = sub
            path.append(word)
            continue
        positionals.append(word)

    if not isinstance(command, click.Group):
        if len(positionals) > _argument_slots(command):
            problems.append(problem(f"takes no argument {positionals[-1]!r}"))
        if path == ["cass", "query"] and positionals:
            rejected = QUERY_DATASET_REJECTS.get(positionals[0], set()) & options
            for name in sorted(rejected):
                problems.append(problem(f"{positionals[0]} rejects {name}"))
    return problems


def check_file(path: Path) -> tuple[int, list[str]]:
    """Check every invocation in ``path``; return (count, problems)."""
    root = typer.main.get_command(app)
    found = invocations(path.read_text())
    problems = [
        f"{path.name}: {problem}"
        for invocation in found
        for problem in check_invocation(invocation, root)
    ]
    return len(found), problems


def test_skill_commands_exist():
    checked = 0
    problems: list[str] = []
    for path in skill_paths():
        count, found = check_file(path)
        checked += count
        problems.extend(found)

    assert problems == []
    assert checked >= 100, f"only {checked} cass invocations found; parser broken?"


def test_made_up_command_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("Run `cass canvas nope` first.\n")

    count, problems = check_file(doc)

    assert count == 1
    assert len(problems) == 1
    assert "has no 'nope'" in problems[0]


def test_made_up_option_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("```bash\ncass canvas files upload notes.pdf \\\n  --nope\n```\n")

    count, problems = check_file(doc)

    assert count == 1
    assert len(problems) == 1
    assert "has no --nope" in problems[0]


def test_parser_handles_placeholders_values_and_root_options(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text(
        "Use `cass --config other.toml canvas files upload FILE --folder <dir>`.\n"
        "```bash\n"
        "cass canvas modules show 'Week 1' --json | jq .\n"
        "```\n"
        "Not a command: `cass.toml`, `from cass.apis import x`.\n"
    )

    count, problems = check_file(doc)

    assert count == 2
    assert problems == []


def test_caps_word_where_a_subcommand_belongs_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("`cass canvas quizzes QUIZ` and `cass canvas HW1`\n")

    _, problems = check_file(doc)

    assert len(problems) == 2
    assert "has no 'QUIZ'" in problems[0]
    assert "has no 'HW1'" in problems[1]


def test_extra_positional_on_leaf_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("`cass status EXTRA`\n")

    _, problems = check_file(doc)

    assert len(problems) == 1
    assert "takes no argument 'EXTRA'" in problems[0]


def test_root_option_after_subcommand_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text("`cass canvas quizzes list --debug`\n")

    _, problems = check_file(doc)

    assert len(problems) == 1
    assert "has no --debug" in problems[0]


def test_query_gradebook_where_fails(tmp_path):
    doc = tmp_path / "SKILL.md"
    doc.write_text(
        '`cass query gradebook --where "score < 50"` '
        '`cass query submissions --where "score < 50"`\n'
    )

    _, problems = check_file(doc)

    assert len(problems) == 1
    assert "gradebook rejects --where" in problems[0]
