import { afterEach, describe, expect, it, vi } from "vitest";
import { saveBlob } from "@/features/reports/save";

describe("saveBlob", () => {
  afterEach(() => vi.restoreAllMocks());

  it("déclenche l'enregistrement sous le nom donné, puis libère l'adresse temporaire", () => {
    const create = vi.fn(() => "blob:test-1");
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const clicked: Array<{ href: string; download: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ href: this.href, download: this.download });
      expect(document.body.contains(this)).toBe(true);
    });

    const blob = new Blob(["%PDF"], { type: "application/pdf" });
    saveBlob(blob, "rapport-2026-10-20.pdf");

    expect(create).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([{ href: "blob:test-1", download: "rapport-2026-10-20.pdf" }]);
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
    expect(document.querySelector("a[download]")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("libère l'adresse même si le clic échoue", () => {
    const revoke = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:test-2", revokeObjectURL: revoke }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      throw new Error("clic refusé");
    });

    expect(() => saveBlob(new Blob(["x"]), "a.pdf")).toThrow("clic refusé");
    expect(revoke).toHaveBeenCalledWith("blob:test-2");
    vi.unstubAllGlobals();
  });
});
