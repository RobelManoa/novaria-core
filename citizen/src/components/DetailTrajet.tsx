import { ago, formatTime } from "../format";
import { CONSEIL, alertesDuTrajet, autresTrajets } from "../detail";
import { faitsDuTroncon } from "../reseau";
import { lienDetail } from "../route";
import type { PublicAlert, SegmentState } from "../types";
import type { Trajet } from "../trajets";
import { VERDICT_ETAT, VERDICT_PHRASE, VERDICT_TITRE, verdictDuTrajet } from "../verdict";
import { SeverityBadge } from "./SeverityBadge";
import { StateBadge } from "./StateBadge";
import { VerdictBadge } from "./VerdictBadge";

interface Props {
  trajet: Trajet;
  /** Tous les trajets gardés : pour comparer avec les autres. */
  trajets: readonly Trajet[];
  parId: ReadonlyMap<string, SegmentState>;
  current: number;
  /** Les alertes ouvertes, ou null quand le service d'alertes ne répond pas : l'écran ne dit alors ni « oui » ni « non ». */
  alertes: readonly PublicAlert[] | null;
  onPrevenir: () => void;
  onSupprimer: () => void;
}

/**
 * Le détail d'un trajet (ADR-031, phase 1). Une question par écran : « puis-je partir ? », puis « pourquoi » et « où » en dessous.
 * Rien n'est montré qui ne soit mesuré : pas de durée, pas de tendance, pas de cause (elles demandent les phases 2 et 3).
 */
export function DetailTrajet({
  trajet,
  trajets,
  parId,
  current,
  alertes,
  onPrevenir,
  onSupprimer,
}: Props) {
  const lecture = verdictDuTrajet(trajet, parId);
  const conseil = CONSEIL[lecture.verdict];
  const ailleurs = autresTrajets(trajet, trajets, parId);
  const ici = alertes === null ? null : alertesDuTrajet(trajet, alertes);
  const etat = VERDICT_ETAT[lecture.verdict].toLowerCase().replace("_", "-");
  const perturbe = lecture.verdict === "BLOQUE" || lecture.verdict === "RALENTI";

  return (
    <article className="detail" aria-labelledby="titre-page">
      <section aria-label="Verdict" className={`detail__verdict detail__verdict--${etat}`}>
        <VerdictBadge verdict={lecture.verdict} />
        <p className="detail__phrase">{VERDICT_PHRASE[lecture.verdict]}</p>
        {lecture.miseAJour ? (
          <p className="trajet__meta">
            Mesure de <time dateTime={lecture.miseAJour}>{formatTime(lecture.miseAJour)}</time> (
            {ago(current, new Date(lecture.miseAJour).getTime())})
          </p>
        ) : null}
      </section>

      <section aria-labelledby="detail-decider" className="detail__bloc">
        <h2 id="detail-decider">Partir maintenant ou attendre ?</h2>
        <ul className="detail__options">
          <li>
            <strong>Partir maintenant</strong>
            <span>{conseil.maintenant}</span>
          </li>
          {conseil.attendre ? (
            <li>
              <strong>Attendre</strong>
              <span>{conseil.attendre}</span>
            </li>
          ) : null}
          {perturbe && ailleurs.length > 0 ? (
            <li>
              <strong>Changer de trajet</strong>
              <span>En ce moment :</span>
              <ul className="detail__autres">
                {ailleurs.map((a) => (
                  <li key={a.id}>
                    <a href={lienDetail(a.id)}>{a.nom}</a> :{" "}
                    {VERDICT_TITRE[a.verdict].toLowerCase()}
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
        </ul>
        <label className="interrupteur">
          <input type="checkbox" checked={trajet.prevenir} onChange={onPrevenir} />
          <span>Me prévenir si ce trajet se bloque</span>
        </label>
        <p className="trajet__meta">
          Un message s'affichera ici. Rien n'est envoyé : c'est une simulation.
        </p>
      </section>

      {perturbe ? (
        <section aria-labelledby="detail-pourquoi" className="detail__bloc">
          <h2 id="detail-pourquoi">
            {lecture.verdict === "BLOQUE" ? "Pourquoi ça bloque ?" : "Pourquoi ça ralentit ?"}
          </h2>
          <p>
            <span className="badge badge--unknown">Cause non confirmée</span>
          </p>
          <p className="trajet__meta">
            Nos capteurs mesurent la vitesse des véhicules : ils ne peuvent pas savoir si c'est un
            accident, des travaux ou simplement beaucoup de monde.
          </p>
        </section>
      ) : null}

      <section aria-labelledby="detail-ou" className="detail__bloc">
        <h2 id="detail-ou">Où ça se passe</h2>
        <ul className="liste">
          {lecture.troncons.map((t) => (
            <li key={t.id} className="detail__endroit">
              <h3>{t.nom}</h3>
              <StateBadge state={t.etat} />
              {faitsDuTroncon(t.id) ? <p className="trajet__meta">{faitsDuTroncon(t.id)}</p> : null}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="detail-alerte" className="detail__bloc">
        <h2 id="detail-alerte">Alerte en cours</h2>
        {ici === null ? (
          <p className="trajet__meta">Les alertes ne sont pas disponibles pour le moment.</p>
        ) : ici.length === 0 ? (
          <p>Aucune alerte en cours sur ce trajet.</p>
        ) : (
          <ul className="liste">
            {ici.map((a) => (
              <li key={a.alert_id} className="detail__alerte">
                <SeverityBadge severity={a.severity} />
                <span>
                  ouverte à <time dateTime={a.opened_at}>{formatTime(a.opened_at)}</time> (
                  {ago(current, new Date(a.opened_at).getTime())})
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="trajet__meta">
          Une alerte s'ouvre quand un endroit reste congestionné plusieurs minutes de suite.
        </p>
      </section>

      <button type="button" className="bouton bouton--discret bouton--petit" onClick={onSupprimer}>
        Supprimer le trajet {trajet.nom}
      </button>
    </article>
  );
}
