import { describe, expect, it } from "bun:test";
import { formatCsv, formatMarkdown, formatRows, formatTable } from "../../src/cli/report.ts";

const rows = [
	{ Name: "Alice", Score: 95, Grade: "A" },
	{ Name: "Bob", Score: 82, Grade: "B" },
];

describe("report", () => {
	describe("formatTable", () => {
		it("renders a cli-table3 table string", () => {
			const result = formatTable(rows);
			expect(result).toContain("Alice");
			expect(result).toContain("Bob");
			expect(result).toContain("95");
			expect(result).toContain("Name");
		});

		it("includes title when provided", () => {
			const result = formatTable(rows, { title: "Grades" });
			expect(result).toContain("Grades");
		});

		it("returns empty message for no rows", () => {
			const result = formatTable([]);
			expect(result).toContain("No data");
		});

		it("respects column subset", () => {
			const result = formatTable(rows, { columns: ["Name", "Grade"] });
			expect(result).toContain("Alice");
			expect(result).toContain("A");
			expect(result).not.toContain("95");
		});
	});

	describe("formatCsv", () => {
		it("renders CSV with headers", () => {
			const result = formatCsv(rows);
			expect(result).toContain("Name,Score,Grade");
			expect(result).toContain("Alice,95,A");
		});

		it("handles empty rows", () => {
			const result = formatCsv([]);
			expect(result).toBe("");
		});

		it("respects column subset", () => {
			const result = formatCsv(rows, ["Name", "Grade"]);
			expect(result).toContain("Name,Grade");
			expect(result).toContain("Alice");
			expect(result).not.toContain("95");
		});
	});

	describe("formatMarkdown", () => {
		it("renders a GFM table", () => {
			const result = formatMarkdown(rows);
			expect(result).toContain("| Name");
			expect(result).toContain("| ---");
			expect(result).toContain("| Alice");
		});

		it("handles empty rows", () => {
			const result = formatMarkdown([]);
			expect(result).toBe("");
		});
	});

	describe("formatRows", () => {
		it("dispatches to table by default", () => {
			const result = formatRows(rows, { format: "table" });
			expect(result).toContain("Alice");
			// cli-table3 uses box-drawing chars
		});

		it("dispatches to csv", () => {
			const result = formatRows(rows, { format: "csv" });
			expect(result).toContain("Name,Score,Grade");
		});

		it("dispatches to markdown", () => {
			const result = formatRows(rows, { format: "markdown" });
			expect(result).toContain("| Name");
		});
	});
});
