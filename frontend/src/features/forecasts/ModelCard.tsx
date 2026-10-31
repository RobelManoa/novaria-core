import { formatDateTime } from "@/features/dashboard/format";
import { SOURCE_LABELS } from "@/features/dashboard/labels";
import type { Forecast } from "@/services/traitement";
import styles from "./ModelCard.module.css";

/** Ce que l'API ne fournit pas encore : dit tel quel, jamais remplacé par une valeur de remplissage. */
const NOT_PROVIDED = "Non communiqué par l'API";
const NOT_APPLICABLE = "Sans objet : modèle de référence, pas d'entraînement";

const KIND_LABELS: Record<Forecast["model"]["kind"], string> = {
  REFERENCE: "Modèle de référence (persistance ou moyenne glissante)",
  MODEL: "Modèle entraîné",
};

function describeProvenance(provenance: Forecast["provenance"]): string {
  const parts = [SOURCE_LABELS[provenance.source_type], `exécution ${provenance.run_id}`];
  if (provenance.scenario_id) parts.push(`scénario ${provenance.scenario_id}`);
  if (provenance.dataset_id) parts.push(`jeu ${provenance.dataset_id}`);
  return parts.join(" · ");
}

/**
 * Le modèle derrière la prévision affichée : ses champs viennent de la réponse de l'API (`model`,
 * `provenance`, `issued_at`). La date du dernier entraînement et la métrique n'y figurent pas encore : la
 * carte l'écrit, et distingue le cas d'une référence (pas d'entraînement) de celui d'un modèle entraîné.
 */
export default function ModelCard({ forecast }: Readonly<{ forecast: Forecast }>) {
  const { model, provenance } = forecast;
  const isReference = model.kind === "REFERENCE";
  const rows: Array<[string, string]> = [
    ["Type", KIND_LABELS[model.kind]],
    ["Nom", model.name],
    ["Version", model.version],
    ["Exécution d'entraînement", model.run_id ?? "—"],
    ["Dernier entraînement", isReference ? NOT_APPLICABLE : NOT_PROVIDED],
    ["Métrique du modèle", isReference ? NOT_APPLICABLE : NOT_PROVIDED],
    ["Origine des données", describeProvenance(provenance)],
    ["Prévision émise le", `${formatDateTime(Date.parse(forecast.issued_at))} (UTC)`],
  ];

  return (
    <section className={styles.card} aria-labelledby="forecast-model">
      <h2 id="forecast-model" className={styles.heading}>
        Modèle
      </h2>
      <dl className={styles.list}>
        {rows.map(([label, value]) => (
          <div key={label} className={styles.row}>
            <dt className={styles.term}>{label}</dt>
            <dd className={styles.value}>{value}</dd>
          </div>
        ))}
      </dl>
      {isReference ? (
        <p className={styles.note}>
          Aucun modèle entraîné n&apos;a battu la référence : la valeur prévue est celle de la
          référence.
        </p>
      ) : null}
      {!isReference && provenance.source_type === "SIMULATED" ? (
        <p className={styles.note}>
          Un modèle entraîné sur le simulateur apprend le simulateur : ce résultat prouve la chaîne
          de traitement, pas la précision en conditions réelles.
        </p>
      ) : null}
      {isReference ? null : (
        <p className={styles.note}>
          La date du dernier entraînement et la métrique ne figurent pas encore dans la réponse de
          l&apos;API.
        </p>
      )}
    </section>
  );
}
