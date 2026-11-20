import { ago, formatTime } from "../format";
import { SEVERITY_LABEL } from "../labels";
import type { FollowState } from "../useFollow";
import { SeverityBadge } from "./AlertsSection";

/**
 * Suivre un tronçon, avec son consentement (ADR-030, section 4.3). Tout est dit avant le premier clic :
 * la notification est **simulée** (un encadré dans cette page), rien n'est envoyé nulle part, rien n'est enregistré.
 */
export function FollowPanel({ follow }: { follow: FollowState }) {
  return (
    <section aria-labelledby="titre-suivi" className="bloc suivi">
      <h2 id="titre-suivi">Suivre un tronçon</h2>
      <div className="panneau panneau--gauche">
        <p>
          Choisissez un tronçon : quand une nouvelle alerte s'ouvre dessus, un message s'affiche
          ici.
        </p>
        <ul className="suivi__garanties">
          <li>
            <strong>Notification simulée :</strong> aucun courriel, SMS ni message n'est envoyé.
          </li>
          <li>
            <strong>Aucune donnée personnelle :</strong> pas de nom, d'adresse, de numéro ni de
            position.
          </li>
          <li>
            <strong>Rien n'est enregistré :</strong> le suivi reste dans cette page et disparaît si
            vous la fermez ou la rechargez.
          </li>
        </ul>
        <label className="consentement">
          <input
            type="checkbox"
            checked={follow.consent}
            onChange={(event) => follow.setConsent(event.target.checked)}
          />
          <span>J'ai compris et j'accepte ces notifications simulées.</span>
        </label>
        {follow.consent && follow.followed.length > 0 ? (
          <p className="carte__detail">
            Tronçons suivis : <strong>{follow.followed.join(", ")}</strong>
          </p>
        ) : null}
        {follow.consent && follow.followed.length === 0 ? (
          <p className="carte__detail">
            Aucun tronçon suivi. Utilisez « Suivre ce tronçon » dans la liste ci-dessous.
          </p>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Les notifications simulées, en haut de page : là où l'on regarde. La zone est toujours présente (vide) pour qu'un lecteur d'écran
 * annonce un message qui s'y ajoute (zone vivante polie).
 */
export function NotificationsZone({ follow, current }: { follow: FollowState; current: number }) {
  return (
    <div aria-live="polite" className="notifications">
      {follow.notifications.map(({ alert, receivedAt }) => (
        <div
          key={alert.alert_id}
          className="notification"
          role="group"
          aria-label="Notification simulée"
        >
          <p className="notification__titre">
            <strong>Notification simulée</strong> · nouvelle alerte sur le tronçon{" "}
            {alert.road_segment_id}
          </p>
          <p className="carte__detail">
            <SeverityBadge severity={alert.severity} />{" "}
            <span className="visuellement-cache">{SEVERITY_LABEL[alert.severity]}. </span>
            Ouverte à <time dateTime={alert.opened_at}>{formatTime(alert.opened_at)}</time>, reçue{" "}
            {ago(current, receivedAt)}.
          </p>
          <button
            type="button"
            className="bouton bouton--discret bouton--petit"
            onClick={() => follow.dismiss(alert.alert_id)}
          >
            Fermer
          </button>
        </div>
      ))}
    </div>
  );
}
