import { useCallback, useEffect, useRef, useState } from "react";

export type Resource<T> =
  { status: "loading" } | { status: "error"; error: unknown } | { status: "ready"; data: T };

type Outcome<T> = { status: "error"; error: unknown } | { status: "ready"; data: T };

/**
 * Charge une ressource asynchrone à chaque changement de `key`. Le résultat est rangé avec la clé qui l'a
 * produit : tant qu'il ne correspond pas à la clé courante, l'état est « chargement », et la réponse
 * tardive d'une ancienne clé ne s'affiche jamais. `reload` relance la lecture sous la même clé.
 *
 * `load` peut changer à chaque rendu : seule `key` décide d'un nouveau chargement, elle doit donc nommer
 * tout ce dont `load` dépend.
 */
export function useAsyncResource<T>(key: string, load: () => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [stored, setStored] = useState<{ key: string; outcome: Outcome<T> } | null>(null);
  const latestLoad = useRef(load);
  const fullKey = `${key}|${attempt}`;

  useEffect(() => {
    latestLoad.current = load;
  });

  useEffect(() => {
    let current = true;
    latestLoad.current().then(
      (data) => {
        if (current) setStored({ key: fullKey, outcome: { status: "ready", data } });
      },
      (error: unknown) => {
        if (current) setStored({ key: fullKey, outcome: { status: "error", error } });
      },
    );
    return () => {
      current = false;
    };
  }, [fullKey]);

  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  const state: Resource<T> = stored?.key === fullKey ? stored.outcome : { status: "loading" };
  return { state, reload };
}
