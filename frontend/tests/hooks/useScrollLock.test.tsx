import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useScrollLock } from "@/hooks/useScrollLock";

describe("useScrollLock", () => {
  it("bloque le défilement puis le rétablit", () => {
    const { rerender, unmount } = renderHook(({ locked }) => useScrollLock(locked), {
      initialProps: { locked: true },
    });
    expect(document.body).toHaveClass("scroll-locked");
    rerender({ locked: false });
    expect(document.body).not.toHaveClass("scroll-locked");
    rerender({ locked: true });
    unmount();
    expect(document.body).not.toHaveClass("scroll-locked");
  });
});
