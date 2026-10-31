import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsyncResource } from "@/hooks/useAsyncResource";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, ko) => {
    resolve = ok;
    reject = ko;
  });
  return { promise, resolve, reject };
}

describe("useAsyncResource", () => {
  it("passe de « chargement » à « prêt » avec les données", async () => {
    const { result } = renderHook(() => useAsyncResource("a", () => Promise.resolve(42)));

    expect(result.current.state).toEqual({ status: "loading" });
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: 42 }));
  });

  it("rend l'erreur telle quelle", async () => {
    const failure = new Error("panne");
    const { result } = renderHook(() => useAsyncResource("a", () => Promise.reject(failure)));

    await waitFor(() => expect(result.current.state).toEqual({ status: "error", error: failure }));
  });

  it("recharge quand la clé change et repasse par « chargement »", async () => {
    const load = vi.fn((value: string) => Promise.resolve(value));
    const { result, rerender } = renderHook(({ key }) => useAsyncResource(key, () => load(key)), {
      initialProps: { key: "a" },
    });
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "a" }));

    rerender({ key: "b" });

    expect(result.current.state).toEqual({ status: "loading" });
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "b" }));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("ne recharge pas quand seul le chargeur change", async () => {
    const load = vi.fn(() => Promise.resolve(1));
    const { result, rerender } = renderHook(() => useAsyncResource("a", () => load()));
    await waitFor(() => expect(result.current.state.status).toBe("ready"));

    rerender();
    rerender();

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("ignore la réponse tardive d'une ancienne clé", async () => {
    const slow = deferred<string>();
    const { result, rerender } = renderHook(
      ({ key }) =>
        useAsyncResource(key, () => (key === "lent" ? slow.promise : Promise.resolve("rapide"))),
      { initialProps: { key: "lent" } },
    );

    rerender({ key: "rapide" });
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "rapide" }));
    await act(async () => {
      slow.resolve("tardif");
      await slow.promise;
    });

    expect(result.current.state).toEqual({ status: "ready", data: "rapide" });
  });

  it("relit sous la même clé avec reload", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("1")).mockResolvedValueOnce("ok");
    const { result } = renderHook(() => useAsyncResource("a", () => load()));
    await waitFor(() => expect(result.current.state.status).toBe("error"));

    act(() => result.current.reload());

    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "ok" }));
  });
});
