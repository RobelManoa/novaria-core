import type { Verdict } from "../verdict";
import { VerdictBadge } from "./VerdictBadge";

const MOTS: readonly { verdict: Verdict; texte: string }[] = [
  { verdict: "LIBRE", texte: "Vous pouvez partir." },
  { verdict: "RALENTI", texte: "Prévoyez un peu de retard." },
  { verdict: "BLOQUE", texte: "Prévoyez beaucoup de retard." },
];

/** Montré tant que le citoyen n'a gardé aucun trajet : les trois mots qu'il lira ensuite, avec leur forme. */
export function TroisMots() {
  return (
    <section aria-labelledby="titre-mots" className="trois-mots">
      <h2 id="titre-mots">Trois mots à retenir</h2>
      <ul className="trois-mots__liste">
        {MOTS.map(({ verdict, texte }) => (
          <li key={verdict}>
            <VerdictBadge verdict={verdict} />
            <span>{texte}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
