import StatCard from "@/components/StatCard";
import { isActive } from "@/features/alerts/merge";
import { STREAM_LABELS } from "@/features/alerts/labels";
import { useAlerts } from "@/features/alerts/useAlerts";
import { formatNumber, formatTime, MISSING } from "@/features/dashboard/format";
import { STATE_LABELS } from "@/features/dashboard/labels";
import { MODE_LABELS } from "@/features/signals/labels";
import { useSignals } from "@/features/signals/useSignals";
import { intersectionRows, latestWindowEnd } from "./rows";
import styles from "./Overview.module.css";
import { useLatestIndicators } from "./useLatestIndicators";

const UNAVAILABLE = "Indisponible";

/**
 * Vue d'ensemble en direct (MS-14) : un chiffre par service, lu auprès de ce service, puis un tableau par
 * carrefour qui réunit les indicateurs du traitement et l'état des feux de la réponse.
 *
 * La collecte n'a pas de lecture destinée aux usagers (ses mesures brutes restent internes) : elle se lit
 * par la fraîcheur de la dernière fenêtre que le traitement en a tirée. C'est dit sur la carte.
 */
export default function Overview() {
  const indicators = useLatestIndicators();
  const signals = useSignals();
  const alerts = useAlerts();

  const rows = intersectionRows(indicators.indicators, signals.signals);
  const windowEnd = latestWindowEnd(indicators.indicators);
  const congested = indicators.indicators.filter((item) => item.congestion_state === "CONGESTED");
  const indicatorsReady = indicators.phase.status === "ready";
  const signalsReady = signals.phase.status === "ready";
  const alertsReady = alerts.phase.status === "ready";
  const activeAlerts = alerts.alerts.filter(isActive).length;
  const manual = signals.signals.filter((item) => item.mode === "MANUAL").length;

  return (
    <section aria-labelledby="overview-title" className={styles.section}>
      <h2 id="overview-title" className={styles.heading}>
        En direct
      </h2>
      <div className={styles.cards}>
        <StatCard
          label="Collecte"
          value={
            indicatorsReady && windowEnd
              ? formatTime(windowEnd)
              : indicatorsReady
                ? MISSING
                : UNAVAILABLE
          }
          unit={indicatorsReady && windowEnd ? "UTC" : undefined}
          hint="Fin de la dernière fenêtre de mesures traitée (la collecte n'expose pas ses mesures brutes)"
        />
        <StatCard
          label="Traitement"
          value={
            indicatorsReady
              ? `${congested.length} sur ${indicators.indicators.length}`
              : UNAVAILABLE
          }
          hint={`Tronçons à l'état « ${STATE_LABELS.CONGESTED} » dans leur dernière fenêtre`}
        />
        <StatCard
          label="Alertes"
          value={alertsReady ? String(activeAlerts) : UNAVAILABLE}
          hint={`Alertes à traiter · flux ${STREAM_LABELS[alerts.stream].toLowerCase()}`}
        />
        <StatCard
          label="Réponse"
          value={signalsReady ? `${manual} sur ${signals.signals.length}` : UNAVAILABLE}
          hint={`Carrefours en mode « ${MODE_LABELS.MANUAL.toLowerCase()} »`}
        />
      </div>

      <h3 className={styles.subheading}>Indicateurs par carrefour</h3>
      {rows.length === 0 ? (
        <p className={styles.empty} role="status">
          {indicatorsReady || signalsReady
            ? "Aucun carrefour à afficher pour le moment."
            : "Chargement des carrefours…"}
        </p>
      ) : (
        <div className={styles.wrap}>
          <table className={styles.table}>
            <caption className={styles.caption}>Indicateurs et feux, par carrefour</caption>
            <thead>
              <tr>
                <th scope="col">Carrefour</th>
                <th scope="col">Tronçons congestionnés</th>
                <th scope="col">Vitesse moyenne</th>
                <th scope="col">Débit</th>
                <th scope="col">Feux</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.intersectionId} data-intersection={row.intersectionId}>
                  <th scope="row">{row.intersectionId}</th>
                  <td>
                    {row.segmentCount === 0
                      ? MISSING
                      : `${row.stateCounts.CONGESTED} sur ${row.segmentCount}`}
                  </td>
                  <td>
                    {row.speedKmh === null ? MISSING : `${formatNumber(row.speedKmh, 1)} km/h`}
                  </td>
                  <td>
                    {row.segmentCount === 0
                      ? MISSING
                      : `${formatNumber(row.flowVehPerMin, 1)} véh/min`}
                  </td>
                  <td>
                    {row.signal
                      ? `${MODE_LABELS[row.signal.mode]} · phase ${row.signal.current_phase_id}`
                      : "Sans feux"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
