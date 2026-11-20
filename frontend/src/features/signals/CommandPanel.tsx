import { useState, type FormEvent } from "react";
import { useAuth } from "@/features/auth/AuthContext";
import { isApiError, messageFor } from "@/services/errors";
import {
  sendSignalCommand,
  type SignalCommand,
  type SignalCommandRequest,
  type SignalState,
} from "@/services/reponse";
import {
  ACTION_LABELS,
  MAX_COMMAND_S,
  MAX_REASON_LENGTH,
  MIN_COMMAND_S,
  MIN_REASON_LENGTH,
  refusalLabel,
} from "./labels";
import styles from "./Signals.module.css";

interface CommandPanelProps {
  signal: SignalState;
  /** Appelée quand la commande a été envoyée (acceptée ou refusée par les garde-fous), pour relire l'état. */
  onSent: () => void;
}

interface Draft {
  action: SignalCommandRequest["action"];
  phaseId: string;
  durationS: string;
  reason: string;
}

type Outcome = { kind: "applied"; command: SignalCommand } | { kind: "error"; message: string };

/** Le message d'une erreur de commande : le refus des garde-fous est détaillé, le reste vient de `messageFor`. */
function describe(error: unknown): string {
  if (isApiError(error) && error.code === "UNSAFE_COMMAND") {
    const codes = (error.fieldErrors ?? []).map((item) => refusalLabel(item.message));
    const reasons = codes.length > 0 ? ` ${codes.join(" ; ")}.` : "";
    return `${messageFor(error)}${reasons} Le refus est journalisé.`;
  }
  return messageFor(error);
}

function validate(draft: Draft): string | null {
  const reason = draft.reason.trim();
  if (reason.length < MIN_REASON_LENGTH)
    return `Le motif doit compter au moins ${MIN_REASON_LENGTH} caractères.`;
  if (reason.length > MAX_REASON_LENGTH)
    return `Le motif ne peut pas dépasser ${MAX_REASON_LENGTH} caractères.`;
  if (draft.action === "RESUME_AUTOMATIC") return null;
  const duration = Number(draft.durationS);
  if (!Number.isInteger(duration) || duration < MIN_COMMAND_S || duration > MAX_COMMAND_S) {
    return `La durée est un nombre entier de secondes, de ${MIN_COMMAND_S} à ${MAX_COMMAND_S}.`;
  }
  return null;
}

function toRequest(draft: Draft): SignalCommandRequest {
  const reason = draft.reason.trim();
  if (draft.action === "RESUME_AUTOMATIC") return { action: "RESUME_AUTOMATIC", reason };
  return {
    action: "SET_PHASE",
    phase_id: draft.phaseId,
    duration_s: Number(draft.durationS),
    reason,
  };
}

/**
 * Commande manuelle d'un carrefour (EXG-TDB-03). Réservée à l'opérateur et à l'administrateur : le lecteur
 * ne voit pas le formulaire, et la passerelle refuse de toute façon sa requête. La commande se confirme avant
 * l'envoi ; le service la journalise avant de l'appliquer, un refus des garde-fous aussi.
 */
export default function CommandPanel({ signal, onSent }: Readonly<CommandPanelProps>) {
  const { user } = useAuth();
  const [draft, setDraft] = useState<Draft>({
    action: "SET_PHASE",
    phaseId: signal.phases[0]?.phase_id ?? "",
    durationS: "30",
    reason: "",
  });
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const canCommand = user?.role === "operator" || user?.role === "admin";

  if (!canCommand) {
    return (
      <p className={styles.note} role="note">
        La commande manuelle est réservée aux opérateurs et aux administrateurs.
      </p>
    );
  }

  const phaseId = signal.phases.some((phase) => phase.phase_id === draft.phaseId)
    ? draft.phaseId
    : (signal.phases[0]?.phase_id ?? "");
  const current: Draft = { ...draft, phaseId };

  const change = (patch: Partial<Draft>) => {
    setDraft({ ...current, ...patch });
    setConfirming(false);
    setOutcome(null);
    setProblem(null);
  };

  const review = (event: FormEvent) => {
    event.preventDefault();
    const invalid = validate(current);
    setProblem(invalid);
    setOutcome(null);
    setConfirming(invalid === null);
  };

  const send = async () => {
    setBusy(true);
    try {
      const command = await sendSignalCommand(signal.intersection_id, toRequest(current));
      setOutcome({ kind: "applied", command });
      setDraft({ ...current, reason: "" });
    } catch (error: unknown) {
      setOutcome({ kind: "error", message: describe(error) });
    } finally {
      setBusy(false);
      setConfirming(false);
      onSent();
    }
  };

  return (
    <form className={styles.form} onSubmit={review} aria-labelledby="command-title" noValidate>
      <h3 id="command-title" className={styles.formTitle}>
        {`Commande manuelle — ${signal.intersection_id}`}
      </h3>

      <fieldset className={styles.fieldset}>
        <legend className={styles.label}>Action</legend>
        {(["SET_PHASE", "RESUME_AUTOMATIC"] as const).map((action) => (
          <label key={action} className={styles.radio}>
            <input
              type="radio"
              name="action"
              value={action}
              checked={current.action === action}
              onChange={() => change({ action })}
            />
            {ACTION_LABELS[action]}
          </label>
        ))}
      </fieldset>

      {current.action === "SET_PHASE" ? (
        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>Phase</span>
            <select
              className={styles.select}
              value={current.phaseId}
              onChange={(event) => change({ phaseId: event.target.value })}
            >
              {signal.phases.map((phase) => (
                <option key={phase.phase_id} value={phase.phase_id}>
                  {`${phase.phase_id} — vert ${phase.green_approaches.join(" ")}`}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            <span className={styles.label}>{`Durée (s, ${MIN_COMMAND_S} à ${MAX_COMMAND_S})`}</span>
            <input
              className={styles.input}
              type="number"
              inputMode="numeric"
              min={MIN_COMMAND_S}
              max={MAX_COMMAND_S}
              value={current.durationS}
              onChange={(event) => change({ durationS: event.target.value })}
            />
          </label>
        </div>
      ) : null}

      <label className={styles.field}>
        <span className={styles.label}>Motif (conservé dans le journal)</span>
        <textarea
          className={styles.textarea}
          rows={2}
          maxLength={MAX_REASON_LENGTH}
          value={current.reason}
          onChange={(event) => change({ reason: event.target.value })}
        />
      </label>

      <p className={styles.hint}>
        {`Une autre phase ne s'impose qu'après ${MIN_COMMAND_S} s de vert, et pas pendant le dégagement : le carrefour passe d'abord 4 s au rouge. Toute commande est journalisée, refusée ou non.`}
      </p>

      {problem ? (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      ) : null}

      {confirming ? (
        <div className={styles.confirm} role="group" aria-label="Confirmation">
          <p>
            {current.action === "SET_PHASE"
              ? `Imposer la phase ${current.phaseId} pendant ${current.durationS} s sur ${signal.intersection_id} ?`
              : `Rendre ${signal.intersection_id} aux recommandations ?`}
          </p>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={busy}
            onClick={() => void send()}
          >
            Confirmer la commande
          </button>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            onClick={() => setConfirming(false)}
          >
            Annuler
          </button>
        </div>
      ) : (
        <button type="submit" className={`${styles.button} ${styles.primary}`}>
          Préparer la commande
        </button>
      )}

      {outcome?.kind === "applied" ? (
        <p className={styles.success} role="status">
          {`Commande ${outcome.command.status === "APPLIED" ? "appliquée" : "enregistrée"} et journalisée (${outcome.command.command_id}).`}
        </p>
      ) : null}
      {outcome?.kind === "error" ? (
        <p className={styles.error} role="alert">
          {outcome.message}
        </p>
      ) : null}
    </form>
  );
}
