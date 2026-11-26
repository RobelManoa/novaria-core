import { describe, expect, it } from "vitest";
import {
  defaultAsOf,
  fromInputValue,
  scoreForecasts,
  toInputValue,
  worstSensors,
} from "@/features/forecasts/trained";
import type { SpeedForecastList } from "@/services/traitement";

type Item = SpeedForecastList["items"][number];

const item = (
  sensor: string,
  predicted: number,
  persistence: number,
  observed: number | null,
): Item => ({
  sensor_id: sensor,
  target_time: "2012-06-20T08:15:00Z",
  predicted_speed_kmh: predicted,
  persistence_speed_kmh: persistence,
  observed_speed_kmh: observed,
});

describe("scoreForecasts", () => {
  it("compare le modèle à la persistance sur ce qui a été mesuré", () => {
    const scores = scoreForecasts([
      item("a", 50, 60, 52), // modèle 2, persistance 8
      item("b", 40, 41, 44), // modèle 4, persistance 3
      item("c", 30, 30, 36), // modèle 6, persistance 6 : égalité, pas une victoire
    ]);
    expect(scores).toEqual({
      compared: 3,
      modelMae: 4,
      persistenceMae: 17 / 3,
      modelWins: 1 / 3,
    });
  });

  it("ignore les capteurs sans observé et ne score rien quand rien n'est comparable", () => {
    expect(scoreForecasts([item("a", 50, 60, null)])).toBeNull();
    expect(scoreForecasts([])).toBeNull();
    expect(scoreForecasts([item("a", 50, 60, 55), item("b", 1, 1, null)])?.compared).toBe(1);
  });
});

describe("worstSensors", () => {
  it("met d'abord les capteurs où la persistance se trompe le plus, puis ceux sans observé", () => {
    const rows = worstSensors(
      [
        item("a", 50, 51, 50),
        item("b", 40, 70, 42),
        item("c", 10, 10, null),
        item("d", 30, 38, 31),
      ],
      3,
    );
    expect(rows.map((r) => r.sensorId)).toEqual(["b", "d", "a"]);
    expect(rows[0]).toMatchObject({ modelError: 2, persistenceError: 28, observed: 42 });
  });

  it("garde les capteurs sans observé à la fin, avec des erreurs absentes", () => {
    const rows = worstSensors([item("c", 10, 10, null), item("a", 50, 55, 50)], 5);
    expect(rows.map((r) => r.sensorId)).toEqual(["a", "c"]);
    expect(rows[1]).toMatchObject({ observed: null, modelError: null, persistenceError: null });
  });
});

describe("champ date et heure", () => {
  it("passe d'un instant UTC au champ datetime-local et retour", () => {
    expect(toInputValue("2012-06-20T08:15:00Z")).toBe("2012-06-20T08:15");
    expect(fromInputValue("2012-06-20T08:15")).toBe("2012-06-20T08:15:00Z");
  });
});

describe("instant proposé à l'ouverture", () => {
  it("recule d'une heure pour que l'avenir à 30 minutes soit déjà mesuré", () => {
    expect(defaultAsOf("2012-06-27T23:55:00Z")).toBe("2012-06-27T22:55:00Z");
    expect(defaultAsOf("2012-06-28T00:10:00Z")).toBe("2012-06-27T23:10:00Z");
  });
});
