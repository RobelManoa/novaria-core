import { useEffect, useRef, useState } from "react";
import type { PublicAlert } from "./types";
import type { Trajet } from "./trajets";

/** Un message « Me prévenir » : un encadré à l'écran, **simulé** (rien n'est envoyé nulle part, ADR-030, section 4.3). */
export interface Message {
  alert: PublicAlert;
  trajet: Pick<Trajet, "id" | "nom">;
  /** Instant (ms) où l'application a vu l'alerte. */
  receivedAt: number;
}

/**
 * Un message naît quand une alerte NOUVELLE (jamais vue depuis l'ouverture de la page) apparaît sur un tronçon d'un trajet où « Me prévenir »
 * est activé. Les alertes déjà ouvertes à l'ouverture, ou quand « Me prévenir » est activé, ne préviennent pas : elles sont déjà à l'écran
 * dans l'état du trajet. Une alerte ne prévient qu'une fois.
 */
export function useNotifications(
  alertes: readonly PublicAlert[],
  prete: boolean,
  trajets: readonly Trajet[],
  now: () => number = Date.now,
) {
  const [messages, setMessages] = useState<readonly Message[]>([]);
  const [lus, setLus] = useState<ReadonlySet<string>>(new Set());
  const vues = useRef<Set<string> | null>(null);
  const nowRef = useRef(now);
  nowRef.current = now;

  useEffect(() => {
    if (!prete) return;
    if (vues.current === null) {
      vues.current = new Set(alertes.map((a) => a.alert_id));
      return;
    }
    const nouvelles = alertes.filter((a) => !vues.current!.has(a.alert_id));
    if (nouvelles.length === 0) return;
    for (const a of nouvelles) vues.current.add(a.alert_id);
    const recus: Message[] = [];
    for (const a of nouvelles) {
      const trajet = trajets.find((t) => t.prevenir && t.troncons.includes(a.road_segment_id));
      if (trajet) {
        recus.push({
          alert: a,
          trajet: { id: trajet.id, nom: trajet.nom },
          receivedAt: nowRef.current(),
        });
      }
    }
    if (recus.length > 0) setMessages((liste) => [...recus, ...liste]);
  }, [alertes, prete, trajets]);

  return {
    /** Tous les messages reçus depuis l'ouverture de la page, le plus récent d'abord. Ils ne sont gardés nulle part : fermer la page les efface. */
    messages,
    /** Ceux que le citoyen n'a pas encore vus : le bandeau en haut de l'écran et la pastille de l'onglet « Messages ». */
    nonLus: messages.filter((m) => !lus.has(m.alert.alert_id)),
    /** Fermer un message le marque lu : il reste dans la liste de l'écran « Messages ». */
    fermer: (alertId: string) => setLus((avant) => new Set(avant).add(alertId)),
    toutLire: () => setLus(new Set(messages.map((m) => m.alert.alert_id))),
  };
}
