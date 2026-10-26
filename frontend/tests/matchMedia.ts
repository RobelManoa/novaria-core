/**
 * jsdom n'implémente pas window.matchMedia : ce mock évalue les requêtes utilisées par l'application
 * à partir d'une largeur de fenêtre et d'une préférence de thème que les tests peuvent modifier.
 */
import { act } from "@testing-library/react";

interface State {
  width: number;
  prefersDark: boolean;
}

const DEFAULT_STATE: State = { width: 1280, prefersDark: false };
const REM_IN_PX = 16;

let state: State = { ...DEFAULT_STATE };
const lists = new Set<MockMediaQueryList>();

function evaluate(query: string): boolean {
  const minWidth = /\(min-width:\s*([\d.]+)rem\)/.exec(query);
  if (minWidth) return state.width >= parseFloat(minWidth[1]) * REM_IN_PX;
  if (query.includes("prefers-color-scheme: dark")) return state.prefersDark;
  return false;
}

class MockMediaQueryList extends EventTarget {
  readonly media: string;
  matches: boolean;
  onchange = null;

  constructor(query: string) {
    super();
    this.media = query;
    this.matches = evaluate(query);
  }

  addListener() {}
  removeListener() {}

  refresh() {
    const matches = evaluate(this.media);
    if (matches === this.matches) return;
    this.matches = matches;
    this.dispatchEvent(new Event("change"));
  }
}

export function installMatchMedia(): void {
  window.matchMedia = ((query: string) => {
    const list = new MockMediaQueryList(query);
    lists.add(list);
    return list;
  }) as unknown as typeof window.matchMedia;
}

function update(next: Partial<State>): void {
  state = { ...state, ...next };
  act(() => lists.forEach((list) => list.refresh()));
}

/** Simule une fenêtre de `width` pixels (ex. 360 pour un téléphone, 1280 pour un ordinateur). */
export function setViewportWidth(width: number): void {
  update({ width });
}

export function setPrefersDark(prefersDark: boolean): void {
  update({ prefersDark });
}

export function resetMatchMedia(): void {
  state = { ...DEFAULT_STATE };
  lists.clear();
}
