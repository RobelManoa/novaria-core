import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TimeSeriesChart, { type ChartPoint } from "@/features/dashboard/TimeSeriesChart";

const T0 = Date.parse("2026-10-20T08:00:00Z");
const minute = (n: number) => T0 + n * 60_000;

function points(values: Array<number | null>): ChartPoint[] {
  return values.map((value, index) => ({ time: minute(index), value }));
}

const tableValues = () =>
  screen
    .getAllByRole("row", { hidden: true })
    .slice(1)
    .map((row) =>
      Array.from(row.querySelectorAll("th, td"), (cell) => cell.textContent?.replace(/\s/g, " ")),
    );

describe("TimeSeriesChart", () => {
  it("ne rend rien sans point", () => {
    const { container } = render(
      <TimeSeriesChart title="Vitesse" unit="km/h" kind="line" digits={1} points={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("décrit le graphique en texte et reprend chaque valeur dans le tableau", () => {
    render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points([30, 45.5, 40])}
      />,
    );

    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Vitesse : de 08:00 à 08:02 UTC, minimum 30,0 km/h, maximum 45,5 km/h",
    );
    expect(tableValues()).toEqual([
      ["08:00", "30,0"],
      ["08:01", "45,5"],
      ["08:02", "40,0"],
    ]);
    expect(screen.getByRole("table", { hidden: true })).toHaveAccessibleName(
      "Vitesse, une ligne par fenêtre (km/h)",
    );
  });

  it("trace une ligne continue, avec un repère par point", () => {
    const { container } = render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points([10, 20, 30])}
      />,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelectorAll("rect")).toHaveLength(0);
  });

  it("coupe le trait à une fenêtre sans valeur, sans la tracer à zéro", () => {
    const { container } = render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points([10, 20, null, 30, 40])}
      />,
    );
    // Deux tracés (avant et après le trou), quatre repères, et le trou reste un tiret dans le tableau.
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    expect(container.querySelectorAll("circle")).toHaveLength(4);
    expect(tableValues()[2]).toEqual(["08:02", "—"]);
  });

  it("ne trace pas de ligne pour une valeur isolée, seulement son repère", () => {
    const { container } = render(
      <TimeSeriesChart title="Vitesse" unit="km/h" kind="line" digits={1} points={points([12])} />,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(0);
    expect(container.querySelectorAll("circle")).toHaveLength(1);
  });

  it("dessine une barre par valeur pour un graphique en barres", () => {
    const { container } = render(
      <TimeSeriesChart
        title="Débit"
        unit="véh/min"
        kind="bar"
        digits={1}
        points={points([5, null, 15])}
      />,
    );
    expect(container.querySelectorAll("rect")).toHaveLength(2);
    expect(container.querySelectorAll("polyline")).toHaveLength(0);
  });

  it("supprime les repères au-delà de 60 points pour garder le trait lisible", () => {
    const { container } = render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points(Array.from({ length: 61 }, (_, i) => i))}
      />,
    );
    expect(container.querySelectorAll("circle")).toHaveLength(0);
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
  });

  it("dit « aucune valeur » quand toutes les fenêtres sont vides", () => {
    render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points([null, null])}
      />,
    );
    expect(screen.getByRole("img")).toHaveAccessibleName("Vitesse : aucune valeur");
  });

  it.each([
    // Valeur maximale → graduations attendues : l'axe part de zéro et avance par pas ronds.
    { max: 47, ticks: ["0", "15", "30", "45", "60"] },
    { max: 269.5, ticks: ["0", "80", "160", "240", "320"] },
    // 3 / 4 = 0,75 : pas rond supérieur 0,8, donc une décimale.
    { max: 3, ticks: ["0,0", "0,8", "1,6", "2,4", "3,2"] },
    { max: 0.3, ticks: ["0,00", "0,08", "0,16", "0,24", "0,32"] },
    { max: 0, ticks: ["0,00", "0,25", "0,50", "0,75", "1,00"] },
  ])("graduations de l'axe pour un maximum de $max", ({ max, ticks }) => {
    const { container } = render(
      <TimeSeriesChart title="Mesure" unit="u" kind="line" digits={1} points={points([0, max])} />,
    );
    const labels = Array.from(container.querySelectorAll("text"), (text) => text.textContent);
    expect(labels.slice(0, 5)).toEqual(ticks);
  });

  it("garde les valeurs du tableau lisibles dans un conteneur défilant", () => {
    render(
      <TimeSeriesChart
        title="Vitesse"
        unit="km/h"
        kind="line"
        digits={1}
        points={points(Array.from({ length: 200 }, (_, i) => i))}
      />,
    );
    const details = screen.getByText("Voir les valeurs").closest("details") as HTMLElement;
    expect(within(details).getAllByRole("row", { hidden: true })).toHaveLength(201);
  });
});
