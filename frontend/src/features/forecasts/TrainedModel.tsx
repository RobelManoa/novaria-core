import { useState } from "react";
import StateMessage from "@/components/StateMessage";
import { formatDateTime, formatNumber } from "@/features/dashboard/format";
import { SOURCE_LABELS } from "@/features/dashboard/labels";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { isApiError, messageFor } from "@/services/errors";
import {
  listSpeedForecasts,
  listSpeedNetworks,
  type ModelCard,
  type SpeedNetwork,
} from "@/services/traitement";
import {
  TRAINED_HORIZONS,
  defaultAsOf,
  fromInputValue,
  scoreForecasts,
  toInputValue,
  worstSensors,
} from "./trained";
import styles from "./TrainedModel.module.css";

const ROWS_SHOWN = 8;
const MPH_TO_KMH = 1.609344;
const pct = (value: number) => `${formatNumber(value * 100, 1)} %`;
const when = (iso: string) => `${formatDateTime(Date.parse(iso))} (UTC)`;

function Card({ network, model }: Readonly<{ network: SpeedNetwork; model: ModelCard }>) {
  const horizons = Object.keys(model.test)
    .map(Number)
    .sort((a, b) => a - b);
  return (
    <section className={styles.card} aria-labelledby="trained-model">
      <h2 id="trained-model" className={styles.heading}>
        Modèle entraîné : {model.name}
      </h2>
      <p>
        <span className={styles.badge}>
          {SOURCE_LABELS[network.source_type as keyof typeof SOURCE_LABELS] ?? network.source_type}
        </span>{" "}
        Réseau {network.label} · version {model.version} · {formatNumber(model.parameters, 0)} poids
        · entraîné le {model.trained_at ? when(model.trained_at) : "date non communiquée"}.
      </p>
      <h3 className={styles.sub}>Ce qu&apos;il regarde</h3>
      <ul className={styles.list}>
        {model.variables.map((variable) => (
          <li key={variable}>{variable}</li>
        ))}
      </ul>
      <h3 className={styles.sub}>Ce qu&apos;il apprend</h3>
      <p>
        Il apprend l&apos;écart entre la vitesse dans N minutes et la vitesse
        d&apos;aujourd&apos;hui (la persistance) : s&apos;il ne sait rien de plus, il retombe sur la
        persistance. Appris sur {formatNumber(model.periods.apprentissage?.steps ?? 0, 0)} pas de 5
        minutes, réglé sur la validation, jugé sur la période de test (
        {model.periods.test
          ? `${when(model.periods.test.start)} à ${when(model.periods.test.end)}`
          : "—"}
        ).
      </p>
      <h3 className={styles.sub}>Son erreur sur la période de test</h3>
      <table className={styles.table}>
        <caption className="sr-only">Erreur moyenne en miles par heure, par horizon</caption>
        <thead>
          <tr>
            <th scope="col">Horizon</th>
            <th scope="col">Persistance</th>
            <th scope="col">Modèle</th>
            <th scope="col">Gain</th>
            <th scope="col">Intervalle à 95 %</th>
          </tr>
        </thead>
        <tbody>
          {horizons.map((h) => {
            const t = model.test[String(h)];
            if (!t) return null;
            return (
              <tr key={h}>
                <th scope="row">{h} min</th>
                <td>{formatNumber(t.mae_persistence_mph, 2)} mph</td>
                <td>{formatNumber(t.mae_model_mph, 2)} mph</td>
                <td className={styles.win}>{pct(t.gain)}</td>
                <td>
                  de {formatNumber(t.interval_95[0] ?? 0, 2)} à{" "}
                  {formatNumber(t.interval_95[1] ?? 0, 2)} mph
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className={styles.note}>
        Le gain est la part d&apos;erreur en moins par rapport à la persistance (
        {formatNumber(MPH_TO_KMH, 2)} km/h par mph). L&apos;intervalle est celui de l&apos;écart
        d&apos;erreur, journées rééchantillonnées : entièrement sous zéro, le modèle fait mieux que
        la persistance.
      </p>
      <h3 className={styles.sub}>Ses limites</h3>
      <ul className={styles.list}>
        {model.limits.map((limit) => (
          <li key={limit}>{limit}</li>
        ))}
      </ul>
    </section>
  );
}

function Live({ network }: Readonly<{ network: SpeedNetwork }>) {
  const last = network.coverage.last;
  const [asOf, setAsOf] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<number>(15);
  const current = asOf ?? (last ? defaultAsOf(last) : "");
  const { state, reload } = useAsyncResource(
    `speed-${network.network_id}-${current}-${horizon}`,
    () => listSpeedForecasts(network.network_id, { as_of: current, horizon_min: horizon }),
  );
  const scores = state.status === "ready" ? scoreForecasts(state.data.items) : null;
  const rows = state.status === "ready" ? worstSensors(state.data.items, ROWS_SHOWN) : [];

  return (
    <section className={styles.card} aria-labelledby="trained-live">
      <h2 id="trained-live" className={styles.heading}>
        Le modèle face au réel
      </h2>
      <p className={styles.note}>
        Les données sont historiques : l&apos;avenir de l&apos;instant choisi est déjà dans
        l&apos;entrepôt, on peut donc comparer ce que le modèle avait prévu à ce qui s&apos;est
        passé.
      </p>
      <form className={styles.controls} onSubmit={(event) => event.preventDefault()}>
        <label className={styles.field}>
          Instant des dernières mesures (UTC)
          <input
            type="datetime-local"
            value={current ? toInputValue(current) : ""}
            min={network.coverage.first ? toInputValue(network.coverage.first) : undefined}
            max={last ? toInputValue(last) : undefined}
            step={300}
            onChange={(event) => event.target.value && setAsOf(fromInputValue(event.target.value))}
          />
        </label>
        <label className={styles.field}>
          Horizon
          <select value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}>
            {TRAINED_HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h} minutes
              </option>
            ))}
          </select>
        </label>
      </form>
      {state.status === "loading" ? (
        <StateMessage kind="loading" title="Calcul des prévisions du modèle…" />
      ) : null}
      {state.status === "error" ? (
        <StateMessage
          kind="error"
          title="Impossible d'obtenir les prévisions du modèle"
          action={
            <button type="button" onClick={reload}>
              Réessayer
            </button>
          }
        >
          {isApiError(state.error) && state.error.status === 404
            ? "Aucune mesure à cette date ou avant, ou réseau inconnu."
            : messageFor(state.error)}
        </StateMessage>
      ) : null}
      {state.status === "ready" ? (
        <>
          <p>
            Prévisions faites avec les mesures de {when(state.data.as_of)}, pour{" "}
            {when(state.data.items[0]?.target_time ?? state.data.as_of)}.
          </p>
          {scores ? (
            <p className={styles.win} role="status">
              Sur {scores.compared} capteurs : erreur moyenne du modèle{" "}
              {formatNumber(scores.modelMae, 2)} km/h, de la persistance{" "}
              {formatNumber(scores.persistenceMae, 2)} km/h ; le modèle est plus proche du réel pour{" "}
              {pct(scores.modelWins)} des capteurs.
            </p>
          ) : (
            <p className={styles.note} role="status">
              Les mesures de cet instant prévu ne sont pas dans l&apos;entrepôt : rien à comparer.
            </p>
          )}
          <table className={styles.table}>
            <caption className="sr-only">
              Les capteurs où la persistance se trompe le plus, en kilomètres par heure
            </caption>
            <thead>
              <tr>
                <th scope="col">Capteur</th>
                <th scope="col">Observé</th>
                <th scope="col">Modèle</th>
                <th scope="col">Persistance</th>
                <th scope="col">Erreur du modèle</th>
                <th scope="col">Erreur de la persistance</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.sensorId}>
                  <th scope="row">{row.sensorId}</th>
                  <td>{row.observed === null ? "—" : formatNumber(row.observed, 1)}</td>
                  <td>{formatNumber(row.predicted, 1)}</td>
                  <td>{formatNumber(row.persistence, 1)}</td>
                  <td>{row.modelError === null ? "—" : formatNumber(row.modelError, 1)}</td>
                  <td>
                    {row.persistenceError === null ? "—" : formatNumber(row.persistenceError, 1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {state.data.sensors_without_model > 0 ? (
            <p className={styles.note}>
              {state.data.sensors_without_model} capteurs du réseau ne sont pas connus du modèle :
              ils n&apos;ont pas de prévision.
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

/**
 * Le modèle entraîné d'un réseau de vitesses (IA-16, ADR-032) : sa fiche (ce qu'il regarde, ce qu'il apprend, son erreur de test contre la
 * persistance, ses limites) et une comparaison en direct de ses prévisions à ce qui a été mesuré. Rien n'est affiché quand aucun réseau
 * de vitesse n'est chargé : la page reste celle du réseau fictif.
 */
export default function TrainedModel() {
  const { state } = useAsyncResource("speed-networks", listSpeedNetworks);
  if (state.status !== "ready") return null;
  const network = state.data.items.find((item) => item.model !== null);
  if (!network?.model) {
    const problem = state.data.items.find((item) => item.model_problem)?.model_problem;
    return problem ? (
      <section className={styles.section} aria-label="Modèle entraîné">
        <StateMessage kind="empty" title="Pas de modèle entraîné utilisable">
          {problem}
        </StateMessage>
      </section>
    ) : null;
  }
  return (
    <div className={styles.section}>
      <Card network={network} model={network.model} />
      <Live network={network} />
    </div>
  );
}
