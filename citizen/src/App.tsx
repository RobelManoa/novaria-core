import type { SegmentState } from "./types";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  OldDataNotice,
  SimulatedBanner,
  StaleNotice,
} from "./components/Notices";
import { SegmentCard } from "./components/SegmentCard";
import { Summary } from "./components/Summary";
import { STALE_AFTER_MS, ago, formatTime } from "./format";
import { countByState, groupByIntersection, latestUpdate } from "./summary";
import { useCongestion } from "./useCongestion";
import { useNow } from "./useNow";

interface Props {
  fetcher?: (signal: AbortSignal) => Promise<SegmentState[]>;
  intervalMs?: number;
  now?: () => number;
}

export default function App({ fetcher, intervalMs, now = Date.now }: Props = {}) {
  const view = useCongestion({ fetcher, intervalMs, now });
  const current = useNow(30_000, now);
  const updated = latestUpdate(view.segments);
  const dataAge = updated ? current - new Date(updated).getTime() : 0;

  return (
    <div className="page">
      <a className="lien-evitement" href="#contenu">
        Aller au contenu
      </a>
      <header className="entete">
        <h1>Circulation en ville</h1>
        <p>L'état de la circulation, tronçon par tronçon. Sans compte, sans inscription.</p>
      </header>
      <main id="contenu" tabIndex={-1}>
        <SimulatedBanner />
        {view.status === "loading" ? <LoadingPanel /> : null}
        {view.status === "error" && view.error ? (
          <ErrorPanel error={view.error} onRetry={view.refresh} busy={view.refreshing} />
        ) : null}
        {view.status === "ready" ? (
          <>
            <div className="miseajour">
              <p>
                {updated ? (
                  <>
                    Données de <time dateTime={updated}>{formatTime(updated)}</time> (
                    {ago(current, new Date(updated).getTime())})
                  </>
                ) : (
                  "Aucune donnée"
                )}
              </p>
              <button
                type="button"
                className="bouton bouton--discret"
                onClick={view.refresh}
                disabled={view.refreshing}
                aria-busy={view.refreshing}
              >
                {view.refreshing ? "Actualisation…" : "Actualiser"}
              </button>
            </div>
            {view.error && view.lastSuccess !== null ? (
              <StaleNotice error={view.error} since={ago(current, view.lastSuccess)} />
            ) : null}
            {updated && dataAge > STALE_AFTER_MS ? <OldDataNotice /> : null}
            {view.segments.length === 0 ? (
              <EmptyPanel />
            ) : (
              <>
                <Summary counts={countByState(view.segments)} />
                <section aria-labelledby="titre-carrefours" className="bloc">
                  <h2 id="titre-carrefours">Par carrefour</h2>
                  {groupByIntersection(view.segments).map((group) => (
                    <section
                      key={group.intersection}
                      aria-labelledby={`carrefour-${group.intersection}`}
                      className="groupe"
                    >
                      <h3 id={`carrefour-${group.intersection}`}>Carrefour {group.intersection}</h3>
                      <ul className="liste">
                        {group.segments.map((segment) => (
                          <SegmentCard key={segment.road_segment_id} segment={segment} />
                        ))}
                      </ul>
                    </section>
                  ))}
                </section>
              </>
            )}
          </>
        ) : null}
      </main>
      <footer className="pied">
        <p>
          Aucun compte, aucun cookie : l'application ne garde rien sur votre appareil. Projet
          pédagogique (Master 2 EADL) : Novaria Core.
        </p>
      </footer>
    </div>
  );
}
