import { ago, formatTime } from "../format";
import type { Message } from "../useNotifications";
import { SeverityBadge } from "./SeverityBadge";

/**
 * Les messages « Me prévenir », en haut de page là où l'on regarde. La zone est toujours présente (vide) pour qu'un lecteur d'écran annonce
 * un message qui s'y ajoute (zone vivante polie). Simulés : rien n'est envoyé.
 */
export function Messages({
  messages,
  current,
  onFermer,
}: {
  messages: readonly Message[];
  current: number;
  onFermer: (id: string) => void;
}) {
  return (
    <div aria-live="polite" className="notifications">
      {messages.map(({ alert, trajet, receivedAt }) => (
        <div
          key={alert.alert_id}
          className="notification"
          role="group"
          aria-label="Message pour votre trajet"
        >
          <p className="notification__titre">
            <strong>Votre trajet « {trajet.nom} » :</strong> une alerte vient de s'ouvrir.
          </p>
          <p className="carte__detail">
            <SeverityBadge severity={alert.severity} /> Alerte ouverte à{" "}
            <time dateTime={alert.opened_at}>{formatTime(alert.opened_at)}</time>, vue{" "}
            {ago(current, receivedAt)}. Message simulé.
          </p>
          <button
            type="button"
            className="bouton bouton--discret bouton--petit"
            onClick={() => onFermer(alert.alert_id)}
          >
            Fermer
          </button>
        </div>
      ))}
    </div>
  );
}
