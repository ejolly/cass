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
PLACEHOLDER = re.compile(r"^(<.*>|[A-Z][A-Z0-9_]*|\.\.\.|…)$")


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


def check_invocation(invocation: str, root: click.Command) -> list[str]:
    """Return the problems found walking ``invocation`` down the command tree."""
    try:
        words = shlex.split(invocation, comments=True)
    except ValueError as exc:
        return [f"{invocation!r}: cannot parse ({exc})"]

    problems: list[str] = []
    command = root
    path = ["cass"]
    skip_value = False
    for word in words[1:]:
        if skip_value:
            skip_value = False
            continue
        if SHELL_STOP.match(word):
            break
        if word.startswith("-") and word != "-":
            name, has_value = word.split("=", 1)[0], "=" in word
            option = _find_option(command, name) or _find_option(root, name)
            if option is None:
                problems.append(f"{invocation!r}: {' '.join(path)} has no {name}")
            elif isinstance(option, click.Option) and not (
                option.is_flag or option.count or has_value
            ):
                skip_value = True
            continue
        if PLACEHOLDER.match(word):
            continue
        if isinstance(command, click.Group):
            sub = command.commands.get(word)
            if sub is None:
                problems.append(f"{invocation!r}: {' '.join(path)} has no {word!r}")
                break
            command = sub
            path.append(word)
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
    assert checked >= 15, f"only {checked} cass invocations found; parser broken?"


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
