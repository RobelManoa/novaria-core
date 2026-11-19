import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import FilterBar from "@/features/dashboard/FilterBar";
import { DEFAULT_FILTERS, type Filters } from "@/features/dashboard/filters";

const ZONES = ["INT_01", "INT_02"];

function setup(filters: Filters = DEFAULT_FILTERS, zones: readonly string[] = ZONES) {
  const onChange = vi.fn();
  render(<FilterBar filters={filters} zones={zones} onChange={onChange} />);
  return onChange;
}

describe("FilterBar", () => {
  it("est un formulaire nommé dont chaque liste a un libellé", () => {
    setup();
    expect(screen.getByRole("form", { name: "Filtres du tableau de bord" })).toBeInTheDocument();
    for (const label of ["Période", "Taille des fenêtres", "Zone"]) {
      expect(screen.getByLabelText(label)).toBeInstanceOf(HTMLSelectElement);
    }
  });

  it("reflète les filtres reçus", () => {
    setup({ periodHours: 6, windowSizeS: 300, intersectionId: "INT_02" });
    expect(screen.getByLabelText("Période")).toHaveValue("6");
    expect(screen.getByLabelText("Taille des fenêtres")).toHaveValue("300");
    expect(screen.getByLabelText("Zone")).toHaveValue("INT_02");
  });

  it("propose tout le réseau puis chaque carrefour connu", () => {
    setup();
    const options = Array.from(
      (screen.getByLabelText("Zone") as HTMLSelectElement).options,
      (option) => option.textContent,
    );
    expect(options).toEqual(["Tout le réseau", "Carrefour INT_01", "Carrefour INT_02"]);
  });

  it("garde une zone choisie même si la liste connue ne la contient pas, à sa place triée", () => {
    setup({ ...DEFAULT_FILTERS, intersectionId: "INT_00" }, ["INT_02", "INT_01"]);
    const options = Array.from(
      (screen.getByLabelText("Zone") as HTMLSelectElement).options,
      (option) => option.value,
    );
    expect(options).toEqual(["", "INT_00", "INT_01", "INT_02"]);
    expect(screen.getByLabelText("Zone")).toHaveValue("INT_00");
  });

  it("change la période sans toucher aux autres filtres", async () => {
    const onChange = setup();
    await userEvent.selectOptions(screen.getByLabelText("Période"), "24");
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, periodHours: 24 });
  });

  it("change la taille des fenêtres en nombre, pas en texte", async () => {
    const onChange = setup();
    await userEvent.selectOptions(screen.getByLabelText("Taille des fenêtres"), "300");
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, windowSizeS: 300 });
  });

  it("choisit un carrefour, puis revient à tout le réseau (null)", async () => {
    const onChange = setup({ ...DEFAULT_FILTERS, intersectionId: "INT_01" });
    await userEvent.selectOptions(screen.getByLabelText("Zone"), "INT_02");
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, intersectionId: "INT_02" });
    await userEvent.selectOptions(screen.getByLabelText("Zone"), "");
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, intersectionId: null });
  });

  it("ne recharge pas la page quand on valide le formulaire (Entrée)", async () => {
    setup();
    const form = screen.getByRole("form", { name: "Filtres du tableau de bord" });
    const submitted = new Event("submit", { cancelable: true, bubbles: true });
    form.dispatchEvent(submitted);
    expect(submitted.defaultPrevented).toBe(true);
  });
});
