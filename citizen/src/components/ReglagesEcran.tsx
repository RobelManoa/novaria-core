import { ALERTS_REFRESH_MS } from "../useAlerts";
import { REFRESH_MS } from "../useCongestion";
import type { Trajet } from "../trajets";
import { VERDICT_PHRASE, type Verdict } from "../verdict";
import { VerdictBadge } from "./VerdictBadge";

interface Props {
  trajets: readonly Trajet[];
  onSupprimer: (id: string) => void;
  onToutEffacer: () => void;
}

/** Dans l'ordre de la maquette : les trois mots d'abord, puis les deux cas où la mesure manque. */
const MOTS: readonly Verdict[] = ["LIBRE", "RALENTI", "BLOQUE", "INCOMPLET", "INDISPONIBLE"];

const COCHE = (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
    <path
      d="M5 12.5l4.5 4.5L19 7"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/** « Réglages et confidentialité » (maquette F) : ce que veut dire chaque mot, ce qui est gardé et où, et comment tout effacer. */
export function ReglagesEcran({ trajets, onSupprimer, onToutEffacer }: Props) {
  const secondes = (ms: number) => `${ms / 1000} secondes`;
  return (
    <>
      <section aria-labelledby="titre-simule" className="bandeau-grand">
        <h2 id="titre-simule">Données simulées</h2>
        <p>
          Tout ce que vous voyez vient d'un <strong>simulateur</strong> : une ville fictive de 6
          places et 24 endroits. Ce n'est pas la circulation réelle.
        </p>
        <p className="trajet__meta">
          La circulation est relue toutes les {secondes(REFRESH_MS)}, les alertes toutes les{" "}
          {secondes(ALERTS_REFRESH_MS)}.
        </p>
      </section>

      <section aria-labelledby="titre-mots-reglages" className="bloc detail__bloc">
        <h2 id="titre-mots-reglages">Comprendre les mots</h2>
        <ul className="trois-mots__liste">
          {MOTS.map((verdict) => (
            <li key={verdict}>
              <VerdictBadge verdict={verdict} />
              <span>{VERDICT_PHRASE[verdict]}</span>
            </li>
          ))}
        </ul>
        <p className="trajet__meta">
          Chaque état a un mot, une forme et une couleur : vous pouvez les lire sans distinguer les
          couleurs. Un contour en pointillés veut dire « ralenti ».
        </p>
      </section>

      <section aria-labelledby="titre-vie" className="bloc detail__bloc">
        <h2 id="titre-vie">Vos trajets restent chez vous</h2>
        <ul className="garanties">
          <li>
            {COCHE}
            <span>
              <strong>Sans compte, sans cookie.</strong> Aucun nom, courriel, numéro ni position.
            </span>
          </li>
          <li>
            {COCHE}
            <span>
              <strong>Gardés sur cet appareil seulement :</strong> la liste de vos trajets et vos
              choix « Me prévenir ». Jamais envoyés à un serveur.
            </span>
          </li>
          <li>
            {COCHE}
            <span>
              <strong>Rien n'est envoyé</strong> par courriel, SMS ou notification : les messages
              restent dans l'application.
            </span>
          </li>
        </ul>
        {trajets.length > 0 ? (
          <>
            <button type="button" className="bouton bouton--danger" onClick={onToutEffacer}>
              Effacer mes trajets
            </button>
            <p className="trajet__meta">L'application redevient comme à la première visite.</p>
          </>
        ) : null}
      </section>

      {trajets.length > 0 ? (
        <section aria-labelledby="titre-liste" className="bloc detail__bloc">
          <h2 id="titre-liste">Mes trajets ({trajets.length})</h2>
          <ul className="liste liste--pleine">
            {trajets.map((t) => (
              <li key={t.id} className="ligne">
                <span>{t.nom}</span>
                <button
                  type="button"
                  className="bouton bouton--discret bouton--petit"
                  onClick={() => onSupprimer(t.id)}
                >
                  Supprimer le trajet {t.nom}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="titre-confort" className="bloc detail__bloc">
        <h2 id="titre-confort">Confort de lecture</h2>
        <p>
          L'application suit la <strong>taille de texte</strong> de votre appareil et la réduction
          des animations. Elle se lit au clavier et avec un lecteur d'écran.
        </p>
        <p className="trajet__meta">
          Aucun réglage à faire ici : tout suit les réglages de votre appareil.
        </p>
      </section>

      <section aria-labelledby="titre-apropos" className="bloc">
        <h2 id="titre-apropos">À propos</h2>
        <p className="trajet__meta">
          Projet pédagogique de Master 2 EADL : Novaria Core. Ville fictive, données simulées.
        </p>
      </section>
    </>
  );
}
