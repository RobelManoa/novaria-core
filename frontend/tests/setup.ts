import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { installMatchMedia, resetMatchMedia } from "./matchMedia";

// react-router crée des Request avec le AbortSignal de jsdom, que le Request natif de Node refuse.
// Les tests n'annulent aucune navigation : on retire le signal.
const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const withoutSignal = { ...init };
      delete withoutSignal.signal;
      super(input, withoutSignal);
    } else {
      super(input, init);
    }
  }
};

beforeEach(() => {
  resetMatchMedia();
  installMatchMedia();
  // jsdom n'évalue pas les requêtes média : on retire les feuilles de style injectées par Vitest pour
  // que le rendu de test soit sans style. Les règles CSS sont couvertes par tests/styles.
  document.head.querySelectorAll("style").forEach((style) => style.remove());
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.body.className = "";
  document.title = "";
});
