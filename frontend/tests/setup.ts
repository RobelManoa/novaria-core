import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { installMatchMedia, resetMatchMedia } from "./matchMedia";

beforeEach(() => {
  resetMatchMedia();
  installMatchMedia();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.body.className = "";
  document.title = "";
});
