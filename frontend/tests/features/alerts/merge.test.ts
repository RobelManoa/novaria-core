import { describe, expect, it } from "vitest";
import {
  canAcknowledge,
  isActive,
  MAX_ALERTS,
  mergeAlert,
  mergeAlerts,
} from "@/features/alerts/merge";
import type { Alert } from "@/services/alerte";

const BASE: Alert = {
  alert_id: "a1",
  rule_id: "congestion.persistante",
  kind: "CONGESTION",
  state: "CREATED",
  severity: "WARNING",
  cause: "UNKNOWN",
  road_segment_id: "ROAD_001",
  intersection_id: "INT_01",
  episode_id: null,
  opened_at: "2026-10-20T08:01:00Z",
  notified_at: null,
  acknowledged_by: null,
  resolved_at: null,
  resolution: null,
  provenance: { source_type: "SIMULATED", run_id: "r", scenario_id: "s", seed: 1 },
};
const alert = (changes: Partial<Alert>): Alert => ({ ...BASE, ...changes });

/** Un événement du flux : les valeurs de l'alerte, sans `notified_at` ni `acknowledged_*` (le serveur ne les envoie pas). */
const streamEvent = (changes: Partial<Alert>): Alert => {
  const { notified_at, acknowledged_at, acknowledged_by, ...rest } = alert(changes);
  void [notified_at, acknowledged_at, acknowledged_by];
  return rest;
};

describe("mergeAlert", () => {
  it("ajoute une alerte inconnue et garde la plus récente en premier", () => {
    const older = alert({ alert_id: "old", opened_at: "2026-10-20T07:00:00Z" });
    const merged = mergeAlert(
      [older],
      alert({ alert_id: "new", opened_at: "2026-10-20T09:00:00Z" }),
    );
    expect(merged.map((a) => a.alert_id)).toEqual(["new", "old"]);
  });

  it("fait avancer une alerte connue sans perdre les champs que l'événement ne porte pas", () => {
    const known = alert({ state: "NOTIFIED", notified_at: "2026-11-05T09:00:00Z" });
    const [merged] = mergeAlert([known], streamEvent({ state: "ACKNOWLEDGED" }));
    expect(merged.state).toBe("ACKNOWLEDGED");
    expect(merged.notified_at).toBe("2026-11-05T09:00:00Z");
  });

  it("ne ramène jamais une alerte à un état antérieur (liste lue avant l'événement)", () => {
    const resolved = alert({
      state: "RESOLVED",
      resolution: "AUTO",
      resolved_at: "2026-10-20T08:09:00Z",
    });
    const list = [resolved];
    expect(mergeAlert(list, alert({ state: "NOTIFIED" }))).toBe(list);
  });

  it("accepte le même état (la réponse d'une action arrive après son événement)", () => {
    const merged = mergeAlert(
      [alert({ state: "ACKNOWLEDGED" })],
      alert({ state: "ACKNOWLEDGED", acknowledged_by: "u" }),
    );
    expect(merged[0].acknowledged_by).toBe("u");
  });

  it("limite le nombre d'alertes gardées en retirant les plus anciennes", () => {
    let list: Alert[] = [];
    for (let n = 0; n < MAX_ALERTS + 5; n += 1) {
      list = mergeAlert(
        list,
        alert({
          alert_id: `a${n}`,
          opened_at: new Date(Date.UTC(2026, 9, 20, 0, n)).toISOString(),
        }),
      );
    }
    expect(list).toHaveLength(MAX_ALERTS);
    expect(list[0].alert_id).toBe(`a${MAX_ALERTS + 4}`);
    expect(list.some((a) => a.alert_id === "a0")).toBe(false);
  });

  it("n'altère pas la liste d'origine", () => {
    const list = [alert({})];
    mergeAlert(list, alert({ state: "NOTIFIED" }));
    expect(list[0].state).toBe("CREATED");
  });
});

describe("mergeAlerts, isActive, canAcknowledge", () => {
  it("range plusieurs alertes d'un coup", () => {
    const merged = mergeAlerts([], [alert({ alert_id: "x" }), alert({ alert_id: "y" })]);
    expect(merged).toHaveLength(2);
  });

  it("une alerte résolue n'est pas active", () => {
    expect(isActive(alert({ state: "RESOLVED" }))).toBe(false);
    expect(isActive(alert({ state: "CREATED" }))).toBe(true);
    expect(isActive(alert({ state: "ACKNOWLEDGED" }))).toBe(true);
  });

  it("on acquitte une alerte créée ou notifiée, pas une alerte déjà acquittée ou résolue", () => {
    expect(canAcknowledge(alert({ state: "CREATED" }))).toBe(true);
    expect(canAcknowledge(alert({ state: "NOTIFIED" }))).toBe(true);
    expect(canAcknowledge(alert({ state: "ACKNOWLEDGED" }))).toBe(false);
    expect(canAcknowledge(alert({ state: "RESOLVED" }))).toBe(false);
  });
});
