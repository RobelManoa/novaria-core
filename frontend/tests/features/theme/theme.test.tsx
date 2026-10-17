import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyTheme,
  initTheme,
  isThemeChoice,
  readStoredTheme,
  storeTheme,
  THEME_STORAGE_KEY,
} from "@/features/theme/theme";
import { useTheme } from "@/features/theme/ThemeContext";
import ThemeProvider from "@/features/theme/ThemeProvider";
import ThemeSelector from "@/features/theme/ThemeSelector";

function renderSelector() {
  return render(
    <ThemeProvider>
      <ThemeSelector />
    </ThemeProvider>,
  );
}

const root = () => document.documentElement;

describe("fonctions du thème", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reconnaît les trois choix valides", () => {
    expect(["light", "dark", "system"].every(isThemeChoice)).toBe(true);
    expect(isThemeChoice("violet")).toBe(false);
    expect(isThemeChoice(null)).toBe(false);
  });

  it("applique et retire data-theme", () => {
    applyTheme("dark");
    expect(root()).toHaveAttribute("data-theme", "dark");
    applyTheme("light");
    expect(root()).toHaveAttribute("data-theme", "light");
    applyTheme("system");
    expect(root()).not.toHaveAttribute("data-theme");
  });

  it("lit le choix mémorisé et ignore une valeur inconnue", () => {
    expect(readStoredTheme()).toBe("system");
    storeTheme("dark");
    expect(readStoredTheme()).toBe("dark");
    window.localStorage.setItem(THEME_STORAGE_KEY, "violet");
    expect(readStoredTheme()).toBe("system");
  });

  it("initialise le thème avant le rendu", () => {
    storeTheme("dark");
    expect(initTheme()).toBe("dark");
    expect(root()).toHaveAttribute("data-theme", "dark");
  });

  it("fonctionne quand le stockage lève une exception", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bloqué", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("plein", "QuotaExceededError");
    });
    expect(readStoredTheme()).toBe("system");
    expect(() => storeTheme("dark")).not.toThrow();
  });

  it("useTheme exige un fournisseur", () => {
    const Probe = () => {
      useTheme();
      return null;
    };
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow("ThemeProvider");
  });
});

describe("sélecteur de thème", () => {
  afterEach(() => vi.restoreAllMocks());

  it("propose trois choix dans un groupe nommé, « Système » étant sélectionné par défaut", () => {
    renderSelector();
    expect(screen.getByRole("group", { name: "Thème de l'interface" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("radio", { name: "Système" })).toBeChecked();
    expect(root()).not.toHaveAttribute("data-theme");
  });

  it("applique et mémorise le choix à la souris ou au toucher", async () => {
    renderSelector();
    await userEvent.click(screen.getByRole("radio", { name: "Sombre" }));
    expect(screen.getByRole("radio", { name: "Sombre" })).toBeChecked();
    expect(root()).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    await userEvent.click(screen.getByRole("radio", { name: "Clair" }));
    expect(root()).toHaveAttribute("data-theme", "light");
  });

  it("se pilote au clavier avec les flèches", async () => {
    renderSelector();
    await userEvent.tab();
    expect(screen.getByRole("radio", { name: "Système" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "Sombre" })).toBeChecked();
    expect(root()).toHaveAttribute("data-theme", "dark");
  });

  it("revient au mode Système en retirant data-theme", async () => {
    renderSelector();
    await userEvent.click(screen.getByRole("radio", { name: "Sombre" }));
    await userEvent.click(screen.getByRole("radio", { name: "Système" }));
    expect(root()).not.toHaveAttribute("data-theme");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  });

  it("restaure le choix mémorisé au chargement", () => {
    storeTheme("dark");
    renderSelector();
    expect(screen.getByRole("radio", { name: "Sombre" })).toBeChecked();
    expect(root()).toHaveAttribute("data-theme", "dark");
  });

  it("fonctionne sans stockage disponible", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bloqué", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bloqué", "SecurityError");
    });
    renderSelector();
    expect(screen.getByRole("radio", { name: "Système" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Sombre" }));
    expect(root()).toHaveAttribute("data-theme", "dark");
  });
});
