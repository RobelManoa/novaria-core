import { useState } from "react";
import type { ApiError } from "../api";
import { ago, formatTime } from "../format";
import { APPROACH_LABEL, SEVERITY_HELP, SEVERITY_LABEL } from "../labels";
import { ERROR_MESSAGE } from "../messages";
import type { AlertsView } from "../useAlerts";
import type { FollowState } from "../useFollow";
import type { Approach, PublicAlert, Severity } from "../types";
import { FollowButton } from "./FollowButton";

const ICON: Record<Severity, string> = {
  INFO: "M12 8v.01 M11 12h1v5h1", // « i »
  WARNING: "M12 4l9 16H3z M12 10v4 M12 17v.01", // triangle d'attention
  CRITICAL: "M8 3h8l5 5v8l-5 5H8l-5-5V8z M12 8v5 M12 16v.01", // panneau avec point d'exclamation
};

/** La gravité : un **mot** et une **forme**, jamais la couleur seule (WCAG 1.4.1), comme l'état d'un tronçon. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge badge--gravite-${severity.toLowerCase()}`}>
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
        <path
          d={ICON[severity]}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>{SEVERITY_LABEL[severity]}</span>
    </span>
  );
}

interface Props {
  view: AlertsView;
  /** Pour dire « arrivée par le nord » quand l'état de la circulation est connu pour ce tronçon. */
  approaches: ReadonlyMap<string, Approach>;
  follow: FollowState;
  current: number;
  onRetry: () => void;
}

function AlertItem({
  alert,
  approach,
  follow,
  current,
}: {
  alert: PublicAlert;
  approach: Approach | undefined;
  follow: FollowState;
  current: number;
}) {
  const opened = new Date(alert.opened_at).getTime();
  return (
    <li
      className={`carte carte--gravite-${alert.severity.toLowerCase()}`}
      data-alerte={alert.alert_id}
    >
      <div className="carte__texte">
        <p className="carte__titre">
          Tronçon {alert.road_segment_id}
          {approach ? ` · ${APPROACH_LABEL[approach]}` : ""}
        </p>
        <p className="carte__detail">
          Carrefour {alert.intersection_id} · depuis{" "}
          <time dateTime={alert.opened_at}>{formatTime(alert.opened_at)}</time> (
          {ago(current, opened)})
          {alert.simulated ? <span className="etiquette"> · Simulé</span> : null}
        </p>
        <p className="visuellement-cache">
          {SEVERITY_LABEL[alert.severity]}. {SEVERITY_HELP[alert.severity]}
        </p>
        <FollowButton roadSegmentId={alert.road_segment_id} follow={follow} />
      </div>
      <SeverityBadge severity={alert.severity} />
    </li>
  );
}

function AlertsNotice({ error, since }: { error: ApiError; since: string }) {
  return (
    <p className="avis avis--attention" role="status">
      <strong>Alertes non actualisées.</strong> {ERROR_MESSAGE[error.kind]} Vous voyez la dernière
      liste connue, reçue {since}.
    </p>
  );
}

/** Au-delà, la liste est repliée : 44 alertes anciennes enterreraient les nouvelles et le consentement sur un écran de téléphone. */
export const VISIBLE_ALERTS = 10;

/** Les alertes de congestion en cours : tronçon, gravité, heure. La liste se met à jour seule (5 secondes). */
export function AlertsSection({ view, approaches, follow, current, onRetry }: Props) {
  const [all, setAll] = useState(false);
  const shown = all ? view.alerts : view.alerts.slice(0, VISIBLE_ALERTS);
  const hidden = view.alerts.length - shown.length;
  return (
    <section aria-labelledby="titre-alertes" className="bloc">
      <h2 id="titre-alertes">Alertes en cours</h2>
      {/* Zone vivante polie : une alerte qui apparaît ou disparaît est annoncée sans interrompre la lecture. */}
      <div aria-live="polite">
        {view.status === "loading" ? <p className="panneau">Chargement des alertes…</p> : null}
        {view.status === "error" && view.error ? (
          <div className="panneau panneau--erreur" role="alert">
            <p>{ERROR_MESSAGE[view.error.kind]}</p>
            <button
              type="button"
              className="bouton"
              onClick={onRetry}
              disabled={view.refreshing}
              aria-busy={view.refreshing}
            >
              {view.refreshing ? "Nouvel essai…" : "Réessayer"}
            </button>
          </div>
        ) : null}
        {view.status === "ready" ? (
          <>
            {view.error && view.lastSuccess !== null ? (
              <AlertsNotice error={view.error} since={ago(current, view.lastSuccess)} />
            ) : null}
            {view.alerts.length === 0 ? (
              <p className="panneau">Aucune alerte en cours. La liste se met à jour seule.</p>
            ) : (
              <>
                <p className="carte__detail">
                  {view.alerts.length === 1
                    ? "1 alerte en cours"
                    : `${view.alerts.length} alertes en cours`}
                  . La liste se met à jour seule.
                </p>
                {follow.consent ? null : (
                  <p className="carte__detail">
                    Pour suivre un tronçon, acceptez d'abord les notifications simulées dans{" "}
                    <a href="#titre-suivi">« Suivre un tronçon »</a>.
                  </p>
                )}
                <ul className="liste">
                  {shown.map((alert) => (
                    <AlertItem
                      key={alert.alert_id}
                      alert={alert}
                      approach={approaches.get(alert.road_segment_id)}
                      follow={follow}
                      current={current}
                    />
                  ))}
                </ul>
                {hidden > 0 || all ? (
                  <button
                    type="button"
                    className="bouton bouton--discret"
                    aria-expanded={all}
                    onClick={() => setAll(!all)}
                  >
                    {all ? "Réduire la liste" : `Afficher les ${hidden} autres alertes`}
                  </button>
                ) : null}
              </>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
