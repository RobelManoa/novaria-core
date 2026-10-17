import { renderHook } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useEscapeKey } from "@/hooks/useEscapeKey";

describe("useEscapeKey", () => {
  it("appelle le rappel sur Échap quand il est actif", async () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape, true));
    await userEvent.keyboard("{Escape}");
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it("ignore les autres touches et l'état inactif", async () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape, true));
    await userEvent.keyboard("a");
    expect(onEscape).not.toHaveBeenCalled();

    const inactive = vi.fn();
    renderHook(() => useEscapeKey(inactive, false));
    await userEvent.keyboard("{Escape}");
    expect(inactive).not.toHaveBeenCalled();
  });
});
