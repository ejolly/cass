"""Output formatting — Rich tables, CSV, and markdown."""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

console = Console()


def render_table(
    relation: duckdb.DuckDBPyRelation,
    title: str | None = None,
) -> None:
    """Print a DuckDB relation as a Rich table."""
    columns = relation.columns
    rows = relation.fetchall()

    table = Table(show_edge=False, pad_edge=False, title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*(str(v) if v is not None else "" for v in row))

    console.print()
    console.print(table)
    console.print(f"\n{len(rows)} rows")
    console.print()


def render_list(
    headers: list[str],
    rows: list[list[str]],
    title: str | None = None,
) -> None:
    """Print headers/rows as a Rich table."""
    table = Table(show_edge=False, pad_edge=False, title=title)
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*row)
    console.print()
    console.print(table)
    console.print(f"\n{len(rows)} rows")
    console.print()


def write_csv_file(
    path: str,
    relation: duckdb.DuckDBPyRelation | None = None,
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
) -> None:
    """Write a DuckDB relation or headers/rows to CSV."""
    if relation is not None:
        df = relation.pl()
        df.write_csv(path)
    elif headers is not None and rows is not None:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
    console.print(f"Wrote {path}")


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        padded = [c.ljust(w) for c, w in zip(cells, widths)]
        return "| " + " | ".join(padded) + " |"

    lines = [
        fmt_row(headers),
        "| " + " | ".join("-" * w for w in widths) + " |",
    ]
    for row in rows:
        lines.append(fmt_row(row))
    return "\n".join(lines)


def save_markdown(
    path: str, title: str, headers: list[str], rows: list[list[str]]
) -> None:
    md = f"# {title}\n\n{markdown_table(headers, rows)}\n"
    Path(path).write_text(md)
    console.print(f"Saved to {path}")


def save_relation_markdown(
    path: str, title: str, relation: duckdb.DuckDBPyRelation
) -> None:
    columns = relation.columns
    rows = [
        [str(v) if v is not None else "" for v in row] for row in relation.fetchall()
    ]
    save_markdown(path, title, columns, rows)
