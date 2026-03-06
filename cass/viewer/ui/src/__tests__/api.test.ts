import { describe, it, expect } from "vitest";
import {
  cellToString,
  parseRows,
  matchesSearch,
  buildCsvContent,
} from "$lib/api.js";
import type { TableData, Row } from "$lib/types.js";

describe("cellToString", () => {
  it("converts null/undefined to empty string", () => {
    expect(cellToString(null)).toBe("");
    expect(cellToString(undefined)).toBe("");
  });

  it("passes strings through", () => {
    expect(cellToString("hello")).toBe("hello");
  });

  it("converts booleans to Yes/No", () => {
    expect(cellToString(true)).toBe("Yes");
    expect(cellToString(false)).toBe("No");
  });

  it("converts integers without decimals", () => {
    expect(cellToString(42)).toBe("42");
    expect(cellToString(0)).toBe("0");
    expect(cellToString(-7)).toBe("-7");
  });

  it("converts floats with decimals", () => {
    expect(cellToString(3.14)).toBe("3.14");
  });
});

describe("parseRows", () => {
  it("converts raw table data to Row records", () => {
    const tableData: TableData = {
      table: "test",
      columns: ["name", "score"],
      types: ["VARCHAR", "INTEGER"],
      rows: [
        ["Alice", 95],
        ["Bob", 87],
      ],
    };

    const rows = parseRows(tableData);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ name: "Alice", score: "95" });
    expect(rows[1]).toEqual({ name: "Bob", score: "87" });
  });

  it("handles null values", () => {
    const tableData: TableData = {
      table: "test",
      columns: ["name", "grade"],
      types: ["VARCHAR", "VARCHAR"],
      rows: [["Alice", null]],
    };

    const rows = parseRows(tableData);
    expect(rows[0]).toEqual({ name: "Alice", grade: "" });
  });

  it("handles boolean values", () => {
    const tableData: TableData = {
      table: "test",
      columns: ["name", "published"],
      types: ["VARCHAR", "BOOLEAN"],
      rows: [
        ["HW1", true],
        ["HW2", false],
      ],
    };

    const rows = parseRows(tableData);
    expect(rows[0]).toEqual({ name: "HW1", published: "Yes" });
    expect(rows[1]).toEqual({ name: "HW2", published: "No" });
  });

  it("handles empty table", () => {
    const tableData: TableData = {
      table: "test",
      columns: ["name"],
      types: ["VARCHAR"],
      rows: [],
    };

    expect(parseRows(tableData)).toEqual([]);
  });
});

describe("matchesSearch", () => {
  const row: Row = {
    name: "Alice Smith",
    email: "alice@example.com",
    score: "95",
  };

  it("matches case-insensitively", () => {
    expect(matchesSearch("alice", row)).toBe(true);
    expect(matchesSearch("ALICE", row)).toBe(true);
    expect(matchesSearch("Alice", row)).toBe(true);
  });

  it("matches across any column", () => {
    expect(matchesSearch("example.com", row)).toBe(true);
    expect(matchesSearch("95", row)).toBe(true);
  });

  it("returns false for non-matches", () => {
    expect(matchesSearch("Bob", row)).toBe(false);
    expect(matchesSearch("xyz", row)).toBe(false);
  });

  it("matches partial strings", () => {
    expect(matchesSearch("smi", row)).toBe(true);
    expect(matchesSearch("@exam", row)).toBe(true);
  });
});

describe("buildCsvContent", () => {
  it("builds CSV with header and rows", () => {
    const columns = ["name", "score"];
    const rows: Row[] = [
      { name: "Alice", score: "95" },
      { name: "Bob", score: "87" },
    ];

    const csv = buildCsvContent(columns, rows);
    expect(csv).toBe("name,score\nAlice,95\nBob,87");
  });

  it("escapes commas in values", () => {
    const columns = ["name"];
    const rows: Row[] = [{ name: "Smith, Alice" }];

    const csv = buildCsvContent(columns, rows);
    expect(csv).toBe('name\n"Smith, Alice"');
  });

  it("escapes quotes in values", () => {
    const columns = ["name"];
    const rows: Row[] = [{ name: 'She said "hello"' }];

    const csv = buildCsvContent(columns, rows);
    expect(csv).toBe('name\n"She said ""hello"""');
  });

  it("escapes newlines in values", () => {
    const columns = ["notes"];
    const rows: Row[] = [{ notes: "line1\nline2" }];

    const csv = buildCsvContent(columns, rows);
    expect(csv).toBe('notes\n"line1\nline2"');
  });

  it("handles empty rows", () => {
    const csv = buildCsvContent(["name", "score"], []);
    expect(csv).toBe("name,score");
  });

  it("handles missing column values", () => {
    const columns = ["name", "score"];
    const rows: Row[] = [{ name: "Alice" }];

    const csv = buildCsvContent(columns, rows);
    expect(csv).toBe("name,score\nAlice,");
  });
});
