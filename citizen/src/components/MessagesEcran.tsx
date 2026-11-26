import { ago, formatTime } from "../format";
import { lienDetail } from "../route";
import type { Trajet } from "../trajets";
import type { Message } from "../useNotifications";
import { SeverityBadge } from "./SeverityBadge";

interface Props {
  messages: readonly Message[];
  trajets: readonly Trajet[];
  current: number;
  onBasculer: (id: string) => void;
}

/**
 * L'écran « Messages » (maquette E) : ce que « Me prévenir » a annoncé depuis l'ouverture de la page, et le réglage trajet par trajet.
 * Les messages sont simulés (rien n'est envoyé) et ne sont gardés nulle part : l'écran le dit. « De nouveau libre » n'est pas annoncé
 * (seules les alertes qui s'ouvrent le sont).
 */
export function MessagesEcran({ messages, trajets, current, onBasculer }: Props) {
  const prevenus = trajets.filter((t) => t.prevenir).length;
  return (
    <>
      <p className="bloc__aide">
        {trajets.length === 0
          ? "Vous n'avez pas encore de trajet à suivre."
          : `Vous êtes prévenu pour ${prevenus} trajet${prevenus > 1 ? "s" : ""} sur ${trajets.length}.`}{" "}
        Les messages sont simulés : rien n'est envoyé, ils s'affichent seulement ici.
      </p>

      <section aria-labelledby="titre-recus" className="bloc">
        <h2 id="titre-recus">Reçus pendant cette visite</h2>
        {messages.length === 0 ? (
          <div className="vide">
            <strong>Aucun message pour l'instant</strong>
            <span>
              Activez « Me prévenir » sur un trajet : vous serez prévenu ici quand une alerte
              s'ouvre dessus.
            </span>
          </div>
        ) : (
          <ul className="liste">
            {messages.map(({ alert, trajet, receivedAt }) => (
              <li key={alert.alert_id} className="message">
                <strong className="message__titre">
                  {trajet.nom} : une alerte vient de s'ouvrir
                </strong>
                <p className="carte__detail">
                  <SeverityBadge severity={alert.severity} /> Alerte ouverte à{" "}
                  <time dateTime={alert.opened_at}>{formatTime(alert.opened_at)}</time>, vue{" "}
                  {ago(current, receivedAt)}.
                </p>
                <p className="trajet__meta">Message simulé · rien n'est envoyé</p>
                {trajets.some((t) => t.id === trajet.id) ? (
                  <a className="message__lien" href={lienDetail(trajet.id)}>
                    Voir le trajet<span className="visuellement-cache"> {trajet.nom}</span>
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <p className="trajet__meta">
          Les messages disparaissent quand vous fermez la page : ils ne sont gardés nulle part.
        </p>
      </section>

      {trajets.length > 0 ? (
        <section aria-labelledby="titre-prevenir" className="bloc detail__bloc">
          <h2 id="titre-prevenir">Me prévenir, trajet par trajet</h2>
          {trajets.map((t) => (
            <label key={t.id} className="interrupteur interrupteur--ligne">
              <span>{t.nom}</span>
              <input
                type="checkbox"
                checked={t.prevenir}
                onChange={() => onBasculer(t.id)}
                aria-label={`Me prévenir pour ${t.nom}`}
              />
            </label>
          ))}
          <p className="trajet__meta">
            Vous recevez un message quand une alerte s'ouvre sur l'un de ces trajets.
          </p>
        </section>
      ) : null}
    </>
  );
}
