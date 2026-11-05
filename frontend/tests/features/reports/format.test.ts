import { describe, expect, it } from "vitest";
import { formatFileSize, shortHash } from "@/features/reports/format";
import { mergeReports } from "@/features/reports/load";
import type { Report } from "@/services/traitement";

describe("formatFileSize", () => {
  it.each([
    [0, "0 o"],
    [999, "999 o"],
    [1000, "1,0 ko"],
    [123_456, "123,5 ko"],
    [999_949, "999,9 ko"],
    [1_000_000, "1,0 Mo"],
    [5_250_000, "5,3 Mo"],
  ])("%i octets → %s", (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected);
  });
});

describe("shortHash", () => {
  it("garde les 12 premiers caractères", () => {
    expect(shortHash("9f86d081884c7d659a2feaa0c55ad015")).toBe("9f86d081884c");
  });
});

describe("mergeReports", () => {
  const make = (id: string): Report => ({
    report_id: id,
    title: id,
    period_start: "2026-10-20T00:00:00Z",
    period_end: "2026-10-20T23:59:59Z",
    generated_at: "2026-10-20T23:30:00Z",
    file_name: `${id}.pdf`,
    size_bytes: 1,
    content_type: "application/pdf",
    sha256: "0".repeat(64),
  });

  it("ajoute la page à la suite et écarte un rapport déjà affiché", () => {
    const merged = mergeReports([make("a"), make("b")], [make("b"), make("c")]);
    expect(merged.map((item) => item.report_id)).toEqual(["a", "b", "c"]);
  });

  it("ne modifie pas la liste d'origine", () => {
    const shown = [make("a")];
    mergeReports(shown, [make("b")]);
    expect(shown).toHaveLength(1);
  });
});
