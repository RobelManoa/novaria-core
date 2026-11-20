import { useCallback, useEffect, useState } from "react";
import { listSignalCommands, type SignalCommand } from "@/services/reponse";

export const HISTORY_PAGE_SIZE = 20;

export type HistoryPhase =
  { status: "loading" } | { status: "error"; error: unknown } | { status: "ready" };

interface Loaded {
  intersectionId: string;
  items: SignalCommand[];
  nextCursor: string | null;
}

/**
 * Journal des commandes d'un carrefour, de la plus récente à la plus ancienne, lu page par page
 * (curseur opaque). `reload` relit la première page, par exemple après l'envoi d'une commande.
 */
export function useCommandHistory(intersectionId: string) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<{ intersectionId: string; error: unknown } | null>(null);
  const [more, setMore] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    listSignalCommands(intersectionId, { limit: HISTORY_PAGE_SIZE }).then(
      (page) => {
        if (!current) return;
        setFailure(null);
        setLoaded({ intersectionId, items: page.items, nextCursor: page.next_cursor });
      },
      (error: unknown) => {
        if (current) setFailure({ intersectionId, error });
      },
    );
    return () => {
      current = false;
    };
  }, [intersectionId, attempt]);

  const fresh = loaded?.intersectionId === intersectionId ? loaded : null;
  const error = failure?.intersectionId === intersectionId ? failure.error : null;

  const loadMore = useCallback(async () => {
    if (!fresh?.nextCursor) return;
    setMore(true);
    try {
      const page = await listSignalCommands(intersectionId, {
        limit: HISTORY_PAGE_SIZE,
        cursor: fresh.nextCursor,
      });
      setLoaded({
        intersectionId,
        items: [...fresh.items, ...page.items],
        nextCursor: page.next_cursor,
      });
    } catch (failed: unknown) {
      setFailure({ intersectionId, error: failed });
    } finally {
      setMore(false);
    }
  }, [fresh, intersectionId]);

  const reload = useCallback(() => {
    setFailure(null);
    setAttempt((count) => count + 1);
  }, []);

  const phase: HistoryPhase = fresh
    ? { status: "ready" }
    : error
      ? { status: "error", error }
      : { status: "loading" };

  return {
    phase,
    items: fresh?.items ?? [],
    hasMore: fresh?.nextCursor != null,
    loadingMore: more,
    loadError: fresh && error ? error : null,
    loadMore,
    reload,
  };
}
