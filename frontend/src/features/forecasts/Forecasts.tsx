import { useMemo, useState } from "react";
import StateMessage from "@/components/StateMessage";
import { WINDOW_SIZES, type WindowSizeSeconds } from "@/features/dashboard/filters";
import { formatNumber } from "@/features/dashboard/format";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { isApiError, messageFor } from "@/services/errors";
import type { Forecast } from "@/services/traitement";
import ComparisonTable from "./ComparisonTable";
import { compareForecasts } from "./compare";
import ForecastChart, { type SeriesPoint } from "./ForecastChart";
import styles from "./Forecasts.module.css";
import { loadForecastView, loadSegments, MAX_OBSERVED, type ForecastView } from "./load";
import ModelCard from "./ModelCard";

/** Horizon dont on montre le modèle : celui du milieu de la gamme, à défaut le plus court. */
const MODEL_HORIZON = 15;

/** Message d'une erreur ; la route absente du serveur (404) est dite comme telle plutôt que « introuvable ». */
function describeError(error: unknown): string {
  if (isApiError(error) && error.status === 404) {
    return "Le service de prévision n'est pas encore disponible sur ce serveur : la route /api/v1/forecasts n'est pas servie.";
  }
  const reference =
    isApiError(error) && error.correlationId ? ` Référence à citer : ${error.correlationId}.` : "";
  return `${messageFor(error)}${reference}`;
}

function RetryButton({ onClick }: Readonly<{ onClick: () => void }>) {
  return (
    <button type="button" className={styles.button} onClick={onClick}>
      Réessayer
    </button>
  );
}

function Result({
  view,
  windowSizeS,
  onWindowSize,
}: Readonly<{
  view: ForecastView;
  windowSizeS: WindowSizeSeconds;
  onWindowSize: (size: WindowSizeSeconds) => void;
}>) {
  const rows = useMemo(
    () => compareForecasts(view.forecasts, view.observed),
    [view.forecasts, view.observed],
  );
  const observed: SeriesPoint[] = useMemo(
    () =>
      [...view.observed]
        .sort((a, b) => Date.parse(a.window_start) - Date.parse(b.window_start))
        .map((item) => ({ time: Date.parse(item.window_start), value: item.speed_ratio })),
    [view.observed],
  );
  const predicted: SeriesPoint[] = rows.map((row) => ({
    time: row.targetTime,
    value: row.predictedRatio,
  }));
  const reference =
    view.forecasts.find((item) => item.horizon_min === MODEL_HORIZON) ?? view.forecasts[0];
  const observedUntil = view.observed.length
    ? Math.max(
        ...view.observed.map((item) => Date.parse(item.window_start) + item.window_size_s * 1000),
      )
    : null;

  return (
    <div className={styles.content}>
      {view.truncated ? (
        <p className={styles.warning} role="note">
          {`La lecture de l'observé s'arrête à ${formatNumber(MAX_OBSERVED, 0)} indicateurs : les plus anciens ne sont pas affichés.`}
        </p>
      ) : null}
      {view.observed.length === 0 ? (
        <p className={styles.warning} role="note">
          {`Aucune valeur observée pour des fenêtres de ${windowSizeS === 60 ? "1 minute" : "5 minutes"} : seules les prévisions sont tracées.`}
          {windowSizeS === 60 ? (
            <>
              {" "}
              <button type="button" className={styles.link} onClick={() => onWindowSize(300)}>
                Essayer les fenêtres de 5 minutes
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      <div className={styles.layout}>
        <ForecastChart
          observed={observed}
          predicted={predicted}
          issuedAt={Date.parse(reference.issued_at)}
        />
        <ModelCard forecast={reference} />
      </div>
      <section aria-labelledby="forecast-table" className={styles.section}>
        <h2 id="forecast-table" className={styles.heading}>
          Prévu contre observé
        </h2>
        <ComparisonTable rows={rows} observedUntil={observedUntil} />
      </section>
    </div>
  );
}

function Panel({ segments }: Readonly<{ segments: readonly Forecast[] }>) {
  const [segmentId, setSegmentId] = useState(segments[0].road_segment_id);
  const [windowSizeS, setWindowSizeS] = useState<WindowSizeSeconds>(60);
  const { state, reload } = useAsyncResource(`${segmentId}|${windowSizeS}`, () =>
    loadForecastView(segmentId, windowSizeS),
  );

  return (
    <>
      <form
        className={styles.filters}
        aria-label="Filtres des prévisions"
        onSubmit={(event) => event.preventDefault()}
      >
        <label className={styles.field}>
          <span className={styles.label}>Tronçon</span>
          <select
            className={styles.select}
            value={segmentId}
            onChange={(event) => setSegmentId(event.target.value)}
          >
            {segments.map((item) => (
              <option key={item.road_segment_id} value={item.road_segment_id}>
                {item.road_segment_id}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Taille des fenêtres observées</span>
          <select
            className={styles.select}
            value={windowSizeS}
            onChange={(event) => setWindowSizeS(Number(event.target.value) as WindowSizeSeconds)}
          >
            {WINDOW_SIZES.map((size) => (
              <option key={size.seconds} value={size.seconds}>
                {size.label}
              </option>
            ))}
          </select>
        </label>
      </form>
      {state.status === "loading" ? (
        <StateMessage kind="loading" title="Chargement des prévisions…" />
      ) : null}
      {state.status === "error" ? (
        <StateMessage
          kind="error"
          title="Impossible de charger les prévisions"
          action={<RetryButton onClick={reload} />}
        >
          {describeError(state.error)}
        </StateMessage>
      ) : null}
      {state.status === "ready" && state.data.forecasts.length === 0 ? (
        <StateMessage kind="empty" title="Aucune prévision pour ce tronçon">
          L&apos;API ne rend aucune prévision pour ce tronçon.
        </StateMessage>
      ) : null}
      {state.status === "ready" && state.data.forecasts.length > 0 ? (
        <Result view={state.data} windowSizeS={windowSizeS} onWindowSize={setWindowSizeS} />
      ) : null}
    </>
  );
}

/** Page des prévisions : une prévision par horizon pour un tronçon, face à ce qui a été observé. */
export default function Forecasts() {
  const { state, reload } = useAsyncResource("segments", loadSegments);

  if (state.status === "loading") {
    return <StateMessage kind="loading" title="Chargement des prévisions…" />;
  }
  if (state.status === "error") {
    return (
      <StateMessage
        kind="error"
        title="Impossible de charger les prévisions"
        action={<RetryButton onClick={reload} />}
      >
        {describeError(state.error)}
      </StateMessage>
    );
  }
  if (state.data.length === 0) {
    return (
      <StateMessage kind="empty" title="Aucune prévision disponible">
        L&apos;API ne rend aucune prévision pour le moment.
      </StateMessage>
    );
  }
  return <Panel segments={state.data} />;
}
