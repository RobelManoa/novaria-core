import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearSession,
  getAccessToken,
  getSessionExpiry,
  peekAccessToken,
  setAccessToken,
  subscribeToSession,
} from "@/services/session";

const KEY = "novaria-session";

describe("session", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("garde le jeton dans sessionStorage, jamais dans localStorage", () => {
    setAccessToken("abc", 1800);
    expect(getAccessToken()).toBe("abc");
    expect(JSON.parse(window.sessionStorage.getItem(KEY) ?? "{}").token).toBe("abc");
    expect(window.localStorage.length).toBe(0);
  });

  it("calcule l'expiration à partir de la durée reçue", () => {
    vi.useFakeTimers({ now: 1_000_000 });
    setAccessToken("abc", 1800);
    expect(getSessionExpiry()).toBe(1_000_000 + 1_800_000);
  });

  it("n'expire pas sans durée connue", () => {
    setAccessToken("abc");
    expect(getSessionExpiry()).toBeNull();
    expect(getAccessToken()).toBe("abc");
  });

  it("refuse un jeton expiré, et l'efface quand on le lit pour un appel", () => {
    vi.useFakeTimers({ now: 0 });
    setAccessToken("abc", 10);
    vi.setSystemTime(9_999);
    expect(getAccessToken()).toBe("abc");
    vi.setSystemTime(10_000);
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });

  it("peekAccessToken ne modifie rien, même expiré (utilisable pendant un rendu)", () => {
    const listener = vi.fn();
    vi.useFakeTimers({ now: 0 });
    setAccessToken("abc", 1);
    subscribeToSession(listener);
    vi.setSystemTime(5_000);
    expect(peekAccessToken()).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).not.toBeNull();
    expect(listener).not.toHaveBeenCalled();
  });

  it("prévient les abonnés à chaque ouverture, fermeture ou expiration", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSession(listener);
    setAccessToken("abc", 1800);
    clearSession();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setAccessToken("def");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("signale l'expiration une seule fois", () => {
    const listener = vi.fn();
    vi.useFakeTimers({ now: 0 });
    setAccessToken("abc", 1);
    subscribeToSession(listener);
    vi.setSystemTime(2_000);
    getAccessToken();
    getAccessToken();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("ignore un contenu de stockage illisible ou mal formé", () => {
    window.sessionStorage.setItem(KEY, "{pas du json");
    expect(peekAccessToken()).toBeNull();
    window.sessionStorage.setItem(KEY, JSON.stringify({ token: 42, expiresAt: null }));
    expect(peekAccessToken()).toBeNull();
    window.sessionStorage.setItem(KEY, JSON.stringify({ token: "", expiresAt: null }));
    expect(peekAccessToken()).toBeNull();
  });

  it("garde le jeton en mémoire quand le stockage refuse l'écriture", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    setAccessToken("abc", 1800);
    expect(getAccessToken()).toBe("abc");
  });
});
