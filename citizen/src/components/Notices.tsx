import { ERROR_MESSAGE } from "../messages";
import type { ApiError } from "../api";

/** Toujours visible, même pendant le chargement ou en erreur : la donnée de la v1 vient d'un simulateur (ADR-027). */
export function SimulatedBanner() {
  return (
    <p className="bandeau" role="note">
      <strong>Données simulées.</strong> Ces informations viennent d'un simulateur : elles ne
      décrivent pas la circulation réelle.
    </p>
  );
}

export function LoadingPanel() {
  return (
    <div className="panneau" role="status">
      <span className="spinner" aria-hidden="true" />
      <p>Chargement de la circulation…</p>
    </div>
  );
}

export function ErrorPanel({
  error,
  onRetry,
  busy,
}: {
  error: ApiError;
  onRetry: () => void;
  busy: boolean;
}) {
  return (
    <div className="panneau panneau--erreur" role="alert">
      <h2>Impossible d'afficher la circulation</h2>
      <p>{ERROR_MESSAGE[error.kind]}</p>
      <button type="button" className="bouton" onClick={onRetry} disabled={busy} aria-busy={busy}>
        {busy ? "Nouvel essai…" : "Réessayer"}
      </button>
    </div>
  );
}

export function EmptyPanel() {
  return (
    <div className="panneau" role="status">
      <h2>Aucune information pour le moment</h2>
      <p>Aucun tronçon n'a de mesure récente. Revenez dans quelques minutes.</p>
    </div>
  );
}

export function StaleNotice({ error, since }: { error: ApiError; since: string }) {
  return (
    <p className="avis avis--attention" role="status">
      <strong>Mise à jour impossible.</strong> {ERROR_MESSAGE[error.kind]} Vous voyez la dernière
      information connue, reçue {since}.
    </p>
  );
}

export function OldDataNotice() {
  return (
    <p className="avis avis--attention" role="status">
      <strong>Information ancienne.</strong> Ces mesures datent de plus de 10 minutes : elles ne
      reflètent peut-être plus la situation.
    </p>
  );
}
