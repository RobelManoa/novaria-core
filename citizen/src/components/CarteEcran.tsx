import { useState } from "react";
import { ago } from "../format";
import { STATE_LABEL } from "../labels";
import { compterEndroits, etatDuTroncon, lieuLePlusGrave } from "../carte";
import { nomDuTroncon, tousLesLieux } from "../lieux";
import { faitsDuTroncon } from "../reseau";
import { lienAjouter } from "../route";
import type { CongestionState, PublicAlert, SegmentState } from "../types";
import { Croix } from "./Croix";
import { Legende } from "./Legende";
import { SeverityBadge } from "./SeverityBadge";
import { StateBadge, StateIcon } from "./StateBadge";

interface Props {
  parId: ReadonlyMap<string, SegmentState>;
  /** Les alertes ouvertes, ou null quand le service d'alertes ne répond pas. */
  alertes: readonly PublicAlert[] | null;
  current: number;
}

const COMPTEUR: readonly { etat: CongestionState; un: string; plusieurs: string }[] = [
  { etat: "FREE_FLOW", un: "Libre", plusieurs: "Libres" },
  { etat: "SLOW", un: "Ralenti", plusieurs: "Ralentis" },
  { etat: "CONGESTED", un: "Bloqué", plusieurs: "Bloqués" },
  { etat: "UNKNOWN", un: "Sans mesure", plusieurs: "Sans mesure" },
];

/** « Place de la Gare, en venant du nord » → « En venant du nord » : le nom de la place est déjà le titre de la fiche. */
function cote(nom: string, lieu: string): string {
  const reste = nom.replace(`${lieu}, `, "");
  return reste.charAt(0).toUpperCase() + reste.slice(1);
}

const NOTE: Record<CongestionState, string> = {
  FREE_FLOW: "Circulation normale",
  SLOW: "Circulation plus lente que d'habitude",
  CONGESTED: "Circulation très dense",
  UNKNOWN: "Pas de mesure récente",
};

/**
 * La carte du réseau (maquette D) : un plan schématique de la ville fictive, six places vues d'en haut, quatre côtés chacune. On touche une
 * place pour lire l'état de chaque côté, puis on peut faire un trajet avec elle. Ce n'est pas une vraie carte : le réseau n'a ni rues
 * connectées ni coordonnées.
 */
export function CarteEcran({ parId, alertes, current }: Props) {
  const lieux = tousLesLieux();
  const [choisi, setChoisi] = useState(() => lieuLePlusGrave(parId));
  const lieu = lieux[choisi] ?? lieux[0];
  const compte = compterEndroits(parId);
  if (!lieu) return null;
  const faits = faitsDuTroncon(lieu.troncons[0]?.id ?? "");

  return (
    <>
      <p className="bloc__aide">
        Plan schématique d'une ville fictive : {lieux.length} places, 24 endroits.
      </p>

      <ul className="compteurs" aria-label="Résumé du réseau">
        {COMPTEUR.map(({ etat, un, plusieurs }) => (
          <li
            key={etat}
            className={`compteurs__case badge--${etat.toLowerCase().replace("_", "-")}`}
          >
            <StateIcon state={etat} />
            <span className="compteurs__nombre">{compte[etat]}</span>
            <span>{compte[etat] > 1 ? plusieurs : un}</span>
          </li>
        ))}
      </ul>

      <section aria-label="Plan" className="plan">
        {lieux.map((l, i) => (
          <button
            key={l.intersection}
            type="button"
            className="plan__lieu"
            aria-pressed={i === choisi}
            aria-label={`${l.nom} : ${l.troncons
              .map(
                (t) =>
                  `${nomDuTroncon(t.id).replace(`${l.nom}, `, "")} ${STATE_LABEL[
                    etatDuTroncon(t.id, parId)
                  ].toLowerCase()}`,
              )
              .join(", ")}`}
            onClick={() => setChoisi(i)}
          >
            <Croix lieu={l} parId={parId} />
            <span className="plan__nom">{l.nom}</span>
          </button>
        ))}
      </section>
      <Legende />

      <section aria-labelledby="titre-lieu" className="fiche">
        <div className="fiche__tete">
          <h2 id="titre-lieu">{lieu.nom}</h2>
          {faits ? <p className="trajet__meta">{faits}</p> : null}
        </div>
        <ul className="liste liste--pleine">
          {lieu.troncons.map((t) => {
            const etat = etatDuTroncon(t.id, parId);
            const alerte = alertes?.find((a) => a.road_segment_id === t.id);
            return (
              <li key={t.id} className="ligne ligne--carte">
                <span className="fiche__cote">
                  <strong>{cote(nomDuTroncon(t.id), lieu.nom)}</strong>
                  <span className="trajet__meta">
                    {alerte
                      ? `Alerte ouverte ${ago(current, new Date(alerte.opened_at).getTime())}`
                      : NOTE[etat]}
                  </span>
                </span>
                <StateBadge state={etat} />
              </li>
            );
          })}
        </ul>
        <a className="bouton bouton--lien bouton--ajout" href={lienAjouter(choisi)}>
          Faire un trajet avec cette place
        </a>
      </section>

      <section aria-labelledby="titre-alertes" className="bloc detail__bloc">
        <h2 id="titre-alertes">
          {alertes === null
            ? "Alertes"
            : alertes.length === 0
              ? "Aucune alerte en cours"
              : `${alertes.length} alerte${alertes.length > 1 ? "s" : ""} en cours`}
        </h2>
        {alertes === null ? (
          <p className="trajet__meta">Les alertes ne sont pas disponibles pour le moment.</p>
        ) : (
          <ul className="liste liste--pleine">
            {alertes.map((a) => (
              <li key={a.alert_id} className="detail__alerte">
                <SeverityBadge severity={a.severity} />
                <span>
                  {nomDuTroncon(a.road_segment_id)} ·{" "}
                  {ago(current, new Date(a.opened_at).getTime())}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="trajet__meta">
          Une alerte s'ouvre quand un endroit reste congestionné plusieurs minutes de suite.
        </p>
      </section>
    </>
  );
}
