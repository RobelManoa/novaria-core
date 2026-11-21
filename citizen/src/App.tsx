import { useEffect, useMemo, useRef, useState } from "react";
import type { PublicAlert, SegmentState } from "./types";
import { AjouterTrajet } from "./components/AjouterTrajet";
import { DetailTrajet } from "./components/DetailTrajet";
import { Messages } from "./components/Messages";
import { ResumeTrajets } from "./components/ResumeTrajets";
import { TroisMots } from "./components/TroisMots";
import {
  ErrorPanel,
  LoadingPanel,
  OldDataNotice,
  SimulatedBanner,
  StaleNotice,
} from "./components/Notices";
import { TrajetCard } from "./components/TrajetCard";
import { STALE_AFTER_MS, ago, formatTime } from "./format";
import { ERROR_MESSAGE } from "./messages";
import { ACCUEIL, useRoute } from "./route";
import { useAlerts } from "./useAlerts";
import { useCongestion } from "./useCongestion";
import { useNotifications } from "./useNotifications";
import { useNow } from "./useNow";
import { useTrajets } from "./useTrajets";

interface Props {
  fetcher?: (signal: AbortSignal) => Promise<SegmentState[]>;
  intervalMs?: number;
  alertsFetcher?: (signal: AbortSignal) => Promise<PublicAlert[]>;
  alertsIntervalMs?: number;
  now?: () => number;
}

/**
 * Un seul écran (ADR-031) : « Mes trajets ». Le citoyen ouvre, voit ses trajets, lit pour chacun un mot (Libre, Ralenti, Bloqué) et une phrase
 * (« Vous pouvez partir »), et décide. Les alertes ne sont plus une liste à lire : elles ne servent qu'à « Me prévenir ».
 */
export default function App({
  fetcher,
  intervalMs,
  alertsFetcher,
  alertsIntervalMs,
  now = Date.now,
}: Props = {}) {
  const circulation = useCongestion({ fetcher, intervalMs, now });
  const alertes = useAlerts({ fetcher: alertsFetcher, intervalMs: alertsIntervalMs, now });
  const trajets = useTrajets();
  const messages = useNotifications(
    alertes.alerts,
    alertes.status === "ready",
    trajets.trajets,
    now,
  );
  const current = useNow(30_000, now);
  const [ajout, setAjout] = useState(false);
  const parId = useMemo(
    () => new Map(circulation.segments.map((s) => [s.road_segment_id, s] as const)),
    [circulation.segments],
  );
  const miseAJour = circulation.segments.reduce<string | null>(
    (m, s) => (m === null || s.updated_at > m ? s.updated_at : m),
    null,
  );
  const donneesAnciennes =
    miseAJour !== null && current - new Date(miseAJour).getTime() > STALE_AFTER_MS;
  const montrerProposes = trajets.trajets.length === 0;
  const surveille = trajets.trajets.some((t) => t.prevenir);
  const route = useRoute();
  const premiereOuverture = route.nom === "accueil" && montrerProposes;
  const detail =
    route.nom === "detail" ? trajets.trajets.find((t) => t.id === route.id) : undefined;
  // Revenir à l'accueil (lien, bouton « retour » du navigateur) remet le focus et le défilement en haut, comme une nouvelle page.
  const dejaVu = useRef(false);
  useEffect(() => {
    if (!dejaVu.current) {
      dejaVu.current = true;
      return;
    }
    document.getElementById("titre-page")?.focus();
    window.scrollTo?.(0, 0);
  }, [route.nom, detail?.id]);

  return (
    <div className="page">
      <a className="lien-evitement" href="#contenu">
        Aller au contenu
      </a>
      <header className="entete">
        {route.nom === "detail" ? (
          <a className="detail__retour" href={ACCUEIL}>
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
              <path
                d="M15 6l-6 6 6 6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Mes trajets
          </a>
        ) : null}
        <h1 id="titre-page" tabIndex={-1}>
          {detail ? detail.nom : premiereOuverture ? "Votre route est-elle libre ?" : "Mes trajets"}
        </h1>
        {route.nom === "accueil" && premiereOuverture ? (
          <p>
            Choisissez vos trajets. Pour chacun, vous voyez tout de suite si vous pouvez partir.
          </p>
        ) : null}
      </header>
      <main id="contenu" tabIndex={-1}>
        <SimulatedBanner />
        <Messages messages={messages.messages} current={current} onFermer={messages.fermer} />
        {circulation.status === "loading" ? <LoadingPanel /> : null}
        {circulation.status === "error" && circulation.error ? (
          <ErrorPanel
            error={circulation.error}
            onRetry={circulation.refresh}
            busy={circulation.refreshing}
          />
        ) : null}
        {circulation.status === "ready" ? (
          <>
            <div className="miseajour">
              <p>
                {miseAJour ? (
                  <>
                    Données de <time dateTime={miseAJour}>{formatTime(miseAJour)}</time> (
                    {ago(current, new Date(miseAJour).getTime())})
                  </>
                ) : (
                  "Aucune donnée"
                )}
              </p>
              <button
                type="button"
                className="bouton bouton--discret"
                onClick={circulation.refresh}
                disabled={circulation.refreshing}
                aria-busy={circulation.refreshing}
              >
                {circulation.refreshing ? "Actualisation…" : "Actualiser"}
              </button>
            </div>
            {circulation.error && circulation.lastSuccess !== null ? (
              <StaleNotice
                error={circulation.error}
                since={ago(current, circulation.lastSuccess)}
              />
            ) : null}
            {donneesAnciennes ? <OldDataNotice /> : null}
            {surveille && alertes.error ? (
              <p className="avis avis--attention" role="status">
                <strong>« Me prévenir » ne se met plus à jour.</strong>{" "}
                {ERROR_MESSAGE[alertes.error.kind]} L'état de vos trajets, lui, reste à jour.
              </p>
            ) : null}
            {route.nom === "detail" ? (
              detail ? (
                <DetailTrajet
                  trajet={detail}
                  trajets={trajets.trajets}
                  parId={parId}
                  current={current}
                  alertes={alertes.status === "ready" && !alertes.error ? alertes.alerts : null}
                  onPrevenir={() => trajets.basculerPrevenir(detail.id)}
                  onSupprimer={() => {
                    trajets.supprimer(detail.id);
                    window.location.hash = ACCUEIL;
                  }}
                />
              ) : (
                <section aria-labelledby="titre-absent" className="bloc">
                  <h2 id="titre-absent">Ce trajet n'existe plus</h2>
                  <p className="bloc__aide">
                    Il a été supprimé, ou il n'a jamais été gardé sur cet appareil.
                  </p>
                  <a className="bouton bouton--lien" href={ACCUEIL}>
                    Retour à mes trajets
                  </a>
                </section>
              )
            ) : (
              <>
                <ResumeTrajets trajets={trajets.trajets} parId={parId} />
                {montrerProposes ? <TroisMots /> : null}
                <section
                  aria-label={montrerProposes ? "Des trajets pour essayer" : "Mes trajets"}
                  className="bloc"
                >
                  {montrerProposes ? <h2>Des trajets pour essayer</h2> : null}
                  {montrerProposes ? (
                    <p className="bloc__aide">
                      {trajets.premiereVisite
                        ? "Voici des exemples. Gardez ceux qui vous servent, ou ajoutez les vôtres."
                        : "Vous n'avez plus de trajet. Gardez un exemple ou ajoutez le vôtre."}
                    </p>
                  ) : null}
                  <ul className="liste">
                    {trajets.trajets.map((t) => (
                      <TrajetCard key={t.id} trajet={t} parId={parId} current={current} />
                    ))}
                    {montrerProposes
                      ? trajets.proposes.map((t) => (
                          <TrajetCard
                            key={t.id}
                            trajet={t}
                            parId={parId}
                            current={current}
                            propose
                            onGarder={() =>
                              trajets.ajouter({ ...t, id: `${t.id}-${Date.now().toString(36)}` })
                            }
                          />
                        ))
                      : null}
                  </ul>
                  {ajout ? (
                    <AjouterTrajet
                      onAjouter={(t) => {
                        trajets.ajouter(t);
                        setAjout(false);
                      }}
                      onFermer={() => setAjout(false)}
                    />
                  ) : (
                    <button
                      type="button"
                      className="bouton bouton--ajout"
                      onClick={() => setAjout(true)}
                    >
                      <svg
                        viewBox="0 0 24 24"
                        width="24"
                        height="24"
                        aria-hidden="true"
                        focusable="false"
                      >
                        <path
                          d="M12 5v14 M5 12h14"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.4"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      Ajouter un trajet
                    </button>
                  )}
                </section>
              </>
            )}
          </>
        ) : null}
      </main>
      <footer className="pied">
        <p>
          Données simulées : elles viennent d'un simulateur, ville fictive, et ne décrivent pas la
          circulation réelle.
        </p>
        <p>
          Vos trajets restent sur cet appareil : rien n'est envoyé, aucun compte, aucun cookie.
          Projet pédagogique (Master 2 EADL) : Novaria Core.
        </p>
        {!trajets.memoire ? (
          <p>
            Votre navigateur ne permet pas de garder vos trajets : ils disparaîtront à la fermeture
            de la page.
          </p>
        ) : null}
        {trajets.trajets.length > 0 ? (
          <button
            type="button"
            className="bouton bouton--discret bouton--petit"
            onClick={trajets.toutEffacer}
          >
            Effacer mes trajets
          </button>
        ) : null}
      </footer>
    </div>
  );
}
