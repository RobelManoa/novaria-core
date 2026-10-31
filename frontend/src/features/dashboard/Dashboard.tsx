import { useMemo, useState } from "react";
import StatCard from "@/components/StatCard";
import StateMessage from "@/components/StateMessage";
import { isApiError, messageFor } from "@/services/errors";
import styles from "./Dashboard.module.css";
import FilterBar from "./FilterBar";
import { DEFAULT_FILTERS, type Filters } from "./filters";
import { formatDateTime, formatNumber } from "./format";
import { SOURCE_LABELS } from "./labels";
import { MAX_PAGES, PAGE_SIZE, type DashboardData } from "./load";
import SegmentTable from "./SegmentTable";
import StateDistribution from "./StateDistribution";
import { summarize } from "./summary";
import TimeSeriesChart from "./TimeSeriesChart";
import { useDashboard } from "./useDashboard";

function describeProvenance(provenance: NonNullable<DashboardData["provenance"]>): string {
  const parts = [SOURCE_LABELS[provenance.source_type], `exécution ${provenance.run_id}`];
  if (provenance.scenario_id) parts.push(`scénario ${provenance.scenario_id}`);
  if (provenance.dataset_id) parts.push(`jeu ${provenance.dataset_id}`);
  return parts.join(" · ");
}

function Ready({ data }: Readonly<{ data: DashboardData }>) {
  const summary = useMemo(() => summarize(data.indicators), [data.indicators]);
  const first = summary.series[0];
  const last = summary.series.at(-1);

  return (
    <div className={styles.content}>
      <p className={styles.meta}>
        {data.provenance ? <strong>{describeProvenance(data.provenance)}</strong> : null}
        {first && last ? (
          <span>
            {` · fenêtres du ${formatDateTime(first.time)} au ${formatDateTime(last.time)} (UTC) · `}
            {`${formatNumber(summary.indicatorCount, 0)} indicateurs · ${summary.segmentCount} tronçons`}
          </span>
        ) : null}
      </p>
      {data.truncated ? (
        <p className={styles.warning} role="note">
          {`La lecture s'arrête à ${formatNumber(MAX_PAGES * PAGE_SIZE, 0)} indicateurs : les fenêtres les plus anciennes ne sont pas affichées. Choisissez une période plus courte ou des fenêtres de 5 minutes.`}
        </p>
      ) : null}

      <section aria-labelledby="dashboard-kpis" className={styles.section}>
        <h2 id="dashboard-kpis" className={styles.heading}>
          Indicateurs clés
        </h2>
        <div className={styles.cards}>
          <StatCard
            label="Vitesse moyenne"
            value={formatNumber(summary.averageSpeedKmh, 1)}
            unit="km/h"
            hint="Moyenne pondérée par le nombre de véhicules"
          />
          <StatCard
            label="Véhicules comptés"
            value={formatNumber(summary.vehicleCount, 0)}
            hint="Somme sur la période"
          />
          <StatCard
            label="Débit moyen"
            value={formatNumber(summary.averageFlowVehPerMin, 1)}
            unit="véh/min"
            hint="Débit cumulé des tronçons, moyenné sur les fenêtres"
          />
          <StatCard
            label="Tronçons congestionnés"
            value={`${summary.stateCounts.CONGESTED} sur ${summary.segmentCount}`}
            hint="D'après la dernière fenêtre de chaque tronçon"
          />
        </div>
      </section>

      <section aria-labelledby="dashboard-evolution" className={styles.section}>
        <h2 id="dashboard-evolution" className={styles.heading}>
          Évolution
        </h2>
        <div className={styles.charts}>
          <TimeSeriesChart
            title="Vitesse moyenne"
            unit="km/h"
            kind="line"
            digits={1}
            points={summary.series.map((point) => ({ time: point.time, value: point.speedKmh }))}
          />
          <TimeSeriesChart
            title="Débit cumulé"
            unit="véh/min"
            kind="bar"
            digits={1}
            points={summary.series.map((point) => ({
              time: point.time,
              value: point.flowVehPerMin,
            }))}
          />
        </div>
      </section>

      <section aria-labelledby="dashboard-states" className={styles.section}>
        <h2 id="dashboard-states" className={styles.heading}>
          État des tronçons
        </h2>
        <StateDistribution counts={summary.stateCounts} total={summary.segmentCount} />
      </section>

      <section aria-labelledby="dashboard-detail" className={styles.section}>
        <h2 id="dashboard-detail" className={styles.heading}>
          Détail par tronçon
        </h2>
        <SegmentTable items={summary.latest} />
      </section>
    </div>
  );
}

interface ContentProps {
  state: ReturnType<typeof useDashboard>["state"];
  filters: Filters;
  onChange: (filters: Filters) => void;
  onRetry: () => void;
}

function Content({ state, filters, onChange, onRetry }: Readonly<ContentProps>) {
  if (state.status === "loading") {
    return <StateMessage kind="loading" title="Chargement des indicateurs…" />;
  }
  if (state.status === "error") {
    const reference =
      isApiError(state.error) && state.error.correlationId
        ? ` Référence à citer : ${state.error.correlationId}.`
        : "";
    return (
      <StateMessage
        kind="error"
        title="Impossible de charger les indicateurs"
        action={
          <button type="button" className={styles.button} onClick={onRetry}>
            Réessayer
          </button>
        }
      >
        {`${messageFor(state.error)}${reference}`}
      </StateMessage>
    );
  }
  if (state.data.indicators.length === 0) {
    const canTryLargerWindows = filters.windowSizeS === 60;
    return (
      <StateMessage
        kind="empty"
        title="Aucun indicateur pour ces filtres"
        action={
          canTryLargerWindows ? (
            <button
              type="button"
              className={styles.button}
              onClick={() => onChange({ ...filters, windowSizeS: 300 })}
            >
              Essayer les fenêtres de 5 minutes
            </button>
          ) : undefined
        }
      >
        {filters.intersectionId
          ? "Cette zone n'a aucune donnée pour la taille de fenêtre choisie. Essayez « Tout le réseau »."
          : "L'API ne renvoie aucune fenêtre pour la taille choisie. Les données chargées peuvent n'exister qu'en fenêtres de 5 minutes."}
      </StateMessage>
    );
  }
  return <Ready data={state.data} />;
}

/** Tableau de bord des indicateurs : filtres, cartes, graphiques d'évolution, états et détail par tronçon. */
export default function Dashboard() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const { state, zones, reload } = useDashboard(filters);

  return (
    <>
      <FilterBar filters={filters} zones={zones} onChange={setFilters} />
      <Content state={state} filters={filters} onChange={setFilters} onRetry={reload} />
    </>
  );
}
