import { describe, expect, it } from "bun:test";
import { parseSortableName, scoreToLetter } from "@/apis/canvas/egrades.ts";

describe("egrades", () => {
  const scheme = [
    { name: "A+", value: 0.97 },
    { name: "A", value: 0.93 },
    { name: "A-", value: 0.9 },
    { name: "B+", value: 0.87 },
    { name: "B", value: 0.83 },
    { name: "B-", value: 0.8 },
    { name: "C+", value: 0.77 },
    { name: "C", value: 0.73 },
    { name: "C-", value: 0.7 },
    { name: "D", value: 0.6 },
    { name: "F", value: 0.0 },
  ];

  describe("scoreToLetter", () => {
    it("maps scores to correct letter grades", () => {
      expect(scoreToLetter(98, scheme)).toBe("A+");
      expect(scoreToLetter(95, scheme)).toBe("A");
      expect(scoreToLetter(91, scheme)).toBe("A-");
      expect(scoreToLetter(85, scheme)).toBe("B");
      expect(scoreToLetter(75, scheme)).toBe("C");
      expect(scoreToLetter(50, scheme)).toBe("F");
    });

    it("returns empty string for null/undefined", () => {
      expect(scoreToLetter(null, scheme)).toBe("");
      expect(scoreToLetter(undefined, scheme)).toBe("");
    });

    it("returns empty string for empty scheme", () => {
      expect(scoreToLetter(95, [])).toBe("");
    });

    it("returns lowest grade for score below all thresholds", () => {
      expect(scoreToLetter(0, scheme)).toBe("F");
    });

    it("handles boundary values", () => {
      expect(scoreToLetter(97, scheme)).toBe("A+");
      expect(scoreToLetter(93, scheme)).toBe("A");
      expect(scoreToLetter(90, scheme)).toBe("A-");
    });
  });

  describe("parseSortableName", () => {
    it("splits Last, First format", () => {
      expect(parseSortableName("Smith, Alice")).toEqual(["Smith", "Alice"]);
    });

    it("handles no comma", () => {
      expect(parseSortableName("Alice Smith")).toEqual(["Alice Smith", ""]);
    });

    it("handles extra spaces", () => {
      expect(parseSortableName("  Smith ,  Alice  ")).toEqual(["Smith", "Alice"]);
    });
  });
});
