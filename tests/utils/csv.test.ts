import { describe, expect, it } from "bun:test";
import { parseCsv, toCsv, toCsvWithColumns } from "@/utils/csv.ts";

describe("csv utils", () => {
  it("parses CSV to objects", () => {
    const csv = "name,score\nAlice,95\nBob,87";
    const rows = parseCsv(csv);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ name: "Alice", score: "95" });
  });

  it("handles empty CSV", () => {
    expect(parseCsv("")).toEqual([]);
  });

  it("converts objects to CSV", () => {
    const data = [
      { name: "Alice", score: 95 },
      { name: "Bob", score: 87 },
    ];
    const csv = toCsv(data);
    expect(csv).toContain("name");
    expect(csv).toContain("Alice");
    expect(csv).toContain("95");
  });

  it("handles commas in values", () => {
    const data = [{ name: "Smith, Alice", grade: "A" }];
    const csv = toCsv(data);
    // Should be quoted
    expect(csv).toContain('"Smith, Alice"');
  });

  it("converts with specific column order", () => {
    const data = [{ b: 2, a: 1 }];
    const csv = toCsvWithColumns(data, ["a", "b"]);
    expect(csv).toContain("a,b");
    expect(csv).toContain("1,2");
  });

  it("returns empty string for empty data", () => {
    expect(toCsv([])).toBe("");
  });
});
