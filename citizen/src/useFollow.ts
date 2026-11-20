import { useCallback, useEffect, useRef, useState } from "react";
import type { PublicAlert } from "./types";

/** Une notification **simulée** : un encadré à l'écran, rien n'est envoyé (ADR-030, section 4.3). */
export interface SimulatedNotification {
  alert: PublicAlert;
  /** Instant (ms) où l'application a vu l'alerte. */
  receivedAt: number;
}

export interface FollowState {
  consent: boolean;
  setConsent: (value: boolean) => void;
  followed: readonly string[];
  isFollowed: (roadSegmentId: string) => boolean;
  follow: (roadSegmentId: string) => void;
  unfollow: (roadSegmentId: string) => void;
  notifications: readonly SimulatedNotification[];
  dismiss: (alertId: string) => void;
}

/**
 * Le suivi d'un tronçon, **en mémoire seulement** : ni stockage, ni cookie, ni identifiant (ADR-030 : rien n'est gardé sur
 * l'appareil). Fermer ou recharger la page l'efface ; l'écran le dit.
 *
 * Une notification naît quand une alerte **nouvelle** (jamais vue) apparaît sur un tronçon suivi. Les alertes déjà ouvertes au
 * moment du suivi sont déjà à l'écran : elles ne notifient pas. Sans consentement, rien n'est suivi.
 */
export function useFollow(
  alerts: readonly PublicAlert[],
  now: () => number = Date.now,
): FollowState {
  const [consent, setConsentState] = useState(false);
  const [followed, setFollowed] = useState<readonly string[]>([]);
  const [notifications, setNotifications] = useState<readonly SimulatedNotification[]>([]);
  const seen = useRef(new Set<string>());
  const alertsRef = useRef(alerts);
  alertsRef.current = alerts;
  const nowRef = useRef(now);
  nowRef.current = now;

  const markSeen = useCallback((roadSegmentId: string) => {
    for (const alert of alertsRef.current) {
      if (alert.road_segment_id === roadSegmentId) seen.current.add(alert.alert_id);
    }
  }, []);

  const follow = useCallback(
    (roadSegmentId: string) => {
      if (!consent) return;
      markSeen(roadSegmentId);
      setFollowed((list) => (list.includes(roadSegmentId) ? list : [...list, roadSegmentId]));
    },
    [consent, markSeen],
  );

  const unfollow = useCallback((roadSegmentId: string) => {
    setFollowed((list) => list.filter((id) => id !== roadSegmentId));
  }, []);

  const setConsent = useCallback((value: boolean) => {
    setConsentState(value);
    if (!value) {
      setFollowed([]);
      setNotifications([]);
      seen.current = new Set();
    }
  }, []);

  useEffect(() => {
    if (followed.length === 0) return;
    const fresh = alerts.filter(
      (alert) => followed.includes(alert.road_segment_id) && !seen.current.has(alert.alert_id),
    );
    if (fresh.length === 0) return;
    for (const alert of fresh) seen.current.add(alert.alert_id);
    const receivedAt = nowRef.current();
    setNotifications((list) => [...fresh.map((alert) => ({ alert, receivedAt })), ...list]);
  }, [alerts, followed]);

  const dismiss = useCallback((alertId: string) => {
    setNotifications((list) => list.filter((item) => item.alert.alert_id !== alertId));
  }, []);

  return {
    consent,
    setConsent,
    followed,
    isFollowed: (id) => followed.includes(id),
    follow,
    unfollow,
    notifications,
    dismiss,
  };
}
