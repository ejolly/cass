/**
 * CSV utilities — thin papaparse wrappers for --csv export and egrades import.
 */
import Papa from "papaparse";

/** Parse CSV string to array of objects. */
export function parseCsv<T = Record<string, string>>(csv: string): T[] {
  const result = Papa.parse<T>(csv, {
    header: true,
    skipEmptyLines: true,
    dynamicTyping: false,
  });
  return result.data;
}

/** Convert array of objects to CSV string. */
export function toCsv(data: Record<string, unknown>[]): string {
  if (data.length === 0) return "";
  return Papa.unparse(data);
}

/** Convert array of objects to CSV string with specific column order. */
export function toCsvWithColumns(data: Record<string, unknown>[], columns: string[]): string {
  return Papa.unparse({
    fields: columns,
    data: data.map((row) => columns.map((col) => row[col] ?? "")),
  });
}
