import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { setViewportWidth } from "../matchMedia";

describe("useMediaQuery", () => {
  it("reflète la requête et suit les changements de largeur", () => {
    setViewportWidth(360);
    const { result } = renderHook(() => useMediaQuery("(min-width: 64rem)"));
    expect(result.current).toBe(false);

    setViewportWidth(1280);
    expect(result.current).toBe(true);

    setViewportWidth(800);
    expect(result.current).toBe(false);
  });
});
