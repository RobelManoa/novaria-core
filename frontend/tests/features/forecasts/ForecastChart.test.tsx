import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ForecastChart, { type SeriesPoint } from "@/features/forecasts/ForecastChart";

const T0 = Date.parse("2026-10-30T08:00:00Z");
const at = (minutes: number) => T0 + minutes * 60_000;
const points = (entries: Array<[number, number | null]>): SeriesPoint[] =>
  entries.map(([minutes, value]) => ({ time: at(minutes), value }));

const rows = () =>
  Array.from(screen.getAllByRole("row", { hidden: true }).slice(1), (row) =>
    Array.from(row.querySelectorAll("th, td"), (cell) => (cell.textContent ?? "").trim()),
  );

describe("ForecastChart", () => {
  it("décrit en texte l'observé et le prévu", () => {
    render(
      <ForecastChart
        observed={points([
          [-10, 0.6],
          [-5, 0.55],
          [0, 0.5],
        ])}
        predicted={points([
          [5, 0.5],
          [15, 0.45],
          [60, 0.4],
        ])}
        issuedAt={at(0)}
      />,
    );

    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Ratio de vitesse : observé de 07:50 à 08:00 UTC (3 valeurs) ; 3 valeurs prévues jusqu'à 09:00 UTC",
    );
  });

  it("reprend chaque valeur, observée ou prévue, dans le tableau, du plus ancien au plus récent", () => {
    render(
      <ForecastChart
        observed={points([
          [-5, 0.55],
          [0, 0.5],
        ])}
        predicted={points([
          [0, 0.51],
          [5, 0.5],
        ])}
        issuedAt={at(0)}
      />,
    );

    // Un instant commun (08:00) montre l'observé et le prévu côte à côte ; sinon un tiret.
    expect(rows()).toEqual([
      ["07:55", "0,550", "—"],
      ["08:00", "0,500", "0,510"],
      ["08:05", "—", "0,500"],
    ]);
  });

  it("trace une ligne observée, une ligne prévue en pointillés, et un losange par prévision", () => {
    const { container } = render(
      <ForecastChart
        observed={points([
          [-10, 0.6],
          [-5, 0.55],
          [0, 0.5],
        ])}
        predicted={points([
          [5, 0.5],
          [15, 0.45],
          [60, 0.4],
        ])}
        issuedAt={at(0)}
      />,
    );

    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    // 3 repères ronds observés + 1 dans la légende ; 3 losanges prévus + 1 dans la légende.
    expect(container.querySelectorAll("circle")).toHaveLength(3 + 1);
    expect(container.querySelectorAll("polygon")).toHaveLength(3 + 1);
  });

  it("place les horizons à leur vraie distance dans le temps, pas à intervalles égaux", () => {
    const { container } = render(
      <ForecastChart
        observed={[]}
        predicted={points([
          [5, 0.5],
          [10, 0.5],
          [60, 0.5],
        ])}
        issuedAt={at(0)}
      />,
    );

    const xs = Array.from(container.querySelectorAll("svg[role=img] polygon"), (node) => {
      const [first] = (node.getAttribute("points") as string).split(" ");
      return Number(first.split(",")[0]);
    });
    // 5 → 10 minutes : 5 minutes d'écart ; 10 → 60 : 50 minutes, soit dix fois plus de distance.
    expect((xs[2] - xs[1]) / (xs[1] - xs[0])).toBeCloseTo(10, 5);
  });

  it("coupe la courbe observée à une fenêtre sans valeur", () => {
    const { container } = render(
      <ForecastChart
        observed={points([
          [-20, 0.6],
          [-15, 0.6],
          [-10, null],
          [-5, 0.5],
          [0, 0.5],
        ])}
        predicted={[]}
        issuedAt={at(0)}
      />,
    );

    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    expect(rows().find((row) => row[0] === "07:50")).toEqual(["07:50", "—", "—"]);
  });

  it("n'écrit pas deux libellés d'heure l'un sur l'autre : le début et la fin passent avant l'émission", () => {
    // Émission à 08:00, dernier instant à 08:01, sur 100 minutes d'historique : l'émission touche la fin.
    const { container } = render(
      <ForecastChart
        observed={points([
          [-100, 0.5],
          [0, 0.5],
        ])}
        predicted={points([[1, 0.5]])}
        issuedAt={at(0)}
      />,
    );

    const hours = Array.from(
      container.querySelectorAll("svg[role=img] text"),
      (t) => t.textContent,
    ).filter((text) => /^\d\d:\d\d$/.test(text ?? ""));
    expect(hours).toEqual(["06:20", "08:01"]);
  });

  it("écrit début, émission et fin quand ils sont assez éloignés", () => {
    const { container } = render(
      <ForecastChart
        observed={points([
          [-120, 0.5],
          [0, 0.5],
        ])}
        predicted={points([[60, 0.5]])}
        issuedAt={at(0)}
      />,
    );

    const hours = Array.from(
      container.querySelectorAll("svg[role=img] text"),
      (t) => t.textContent,
    ).filter((text) => /^\d\d:\d\d$/.test(text ?? ""));
    expect(hours).toEqual(["06:00", "09:00", "08:00"]);
  });

  it("aligne le premier libellé sur l'axe et le dernier sur le bord droit pour qu'aucun ne soit rogné", () => {
    const { container } = render(
      <ForecastChart
        observed={points([
          [-120, 0.5],
          [0, 0.5],
        ])}
        predicted={points([[60, 0.5]])}
        issuedAt={at(0)}
      />,
    );

    const anchors = Object.fromEntries(
      Array.from(container.querySelectorAll("svg[role=img] text"))
        .filter((text) => /^\d\d:\d\d$/.test(text.textContent ?? ""))
        .map((text) => [text.textContent, text.getAttribute("text-anchor")]),
    );
    expect(anchors).toEqual({ "06:00": "start", "09:00": "end", "08:00": "middle" });
  });

  it("indique l'émission sur l'axe", () => {
    render(
      <ForecastChart
        observed={points([[-10, 0.6]])}
        predicted={points([[60, 0.4]])}
        issuedAt={at(0)}
      />,
    );
    expect(screen.getByText("Émission")).toBeInTheDocument();
  });

  it("dit « aucune valeur » sans observé ni prévu", () => {
    render(<ForecastChart observed={[]} predicted={[]} issuedAt={at(0)} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Ratio de vitesse : aucune valeur observée ; aucune valeur prévue",
    );
  });

  it("n'affiche pas de repères ronds au-delà de 60 valeurs observées", () => {
    const many = points(Array.from({ length: 61 }, (_, i): [number, number] => [-(61 - i), 0.5]));
    const { container } = render(<ForecastChart observed={many} predicted={[]} issuedAt={at(0)} />);
    // Seul le repère de la légende reste.
    expect(container.querySelectorAll("circle")).toHaveLength(1);
  });
});
