import type { ReactNode } from "react";
import { createElement } from "react";
import { AuthContext } from "@/features/auth/AuthContext";
import type { Role } from "@/services/apiMetier";
import type { SignalCommand, SignalState } from "@/services/reponse";

/** Un carrefour à deux phases en mode automatique, d'après le schéma `SignalState` du contrat. */
export const SIGNAL: SignalState = {
  intersection_id: "INT_01",
  mode: "AUTOMATIC",
  signal: "GREEN",
  current_phase_id: "P1",
  green_approaches: ["N", "S"],
  phase_started_at: "2026-10-20T08:00:00Z",
  phase_ends_at: "2026-10-20T08:00:30Z",
  updated_at: "2026-10-20T08:00:00Z",
  decision: {
    origin: "RECOMMENDATION",
    outcome: "APPLIED",
    reference_id: "5d4c8a6e-0f4b-4d6e-b5b1-2a9d8e7c6b51",
    refusal_reason: null,
  },
  phases: [
    { phase_id: "P1", green_approaches: ["N", "S"], duration_s: 30, min_duration_s: 10 },
    { phase_id: "P2", green_approaches: ["E", "W"], duration_s: 30, min_duration_s: 10 },
  ],
  provenance: { source_type: "SIMULATED", run_id: "run-demo", scenario_id: "demo", seed: 42 },
};

export const SIGNAL_2: SignalState = {
  ...SIGNAL,
  intersection_id: "INT_02",
  mode: "DEGRADED_FIXED_PLAN",
  current_phase_id: "P2",
  green_approaches: [],
  signal: "ALL_RED",
};

export const COMMAND: SignalCommand = {
  command_id: "8c1f4a52-7d3b-4e8f-9a60-3b2c1d0e9f87",
  intersection_id: "INT_01",
  action: "SET_PHASE",
  phase_id: "P2",
  duration_s: 30,
  reason: "Évacuation après incident confirmé",
  status: "APPLIED",
  refusal_reason: null,
  requested_by: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11", // le compte de `withRole`
  requested_at: "2026-10-20T08:10:00Z",
};

export const REFUSED_COMMAND: SignalCommand = {
  ...COMMAND,
  command_id: "1e2d3c4b-5a69-4788-9a0b-c1d2e3f4a5b6",
  duration_s: 5,
  reason: "Essai trop court",
  status: "REFUSED",
  refusal_reason: "PHASE_TOO_SHORT",
  requested_by: "cdd610fe-f820-4c4f-b178-ff80cb5efd7a",
  requested_at: "2026-10-20T08:05:00Z",
};

export function withRole(role: Role | null, children: ReactNode) {
  const user = role
    ? {
        user_id: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11",
        username: "agent1",
        role,
        is_active: true,
        created_at: "2026-10-20T08:00:00Z",
      }
    : null;
  return createElement(
    AuthContext.Provider,
    {
      value: {
        isAuthenticated: true,
        user,
        login: async () => undefined,
        logout: () => undefined,
      },
    },
    children,
  );
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

export const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  json(
    { type: "about:blank", title: "Erreur", status, code, correlation_id: "corr-9", ...extra },
    status,
  );
