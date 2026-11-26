import { ACCUEIL, CARTE, MESSAGES } from "../route";

const ROUTE =
  "M5 19a2 2 0 100-4 2 2 0 000 4z M19 9a2 2 0 100-4 2 2 0 000 4z M7 17h7a3 3 0 000-6h-4a3 3 0 010-6h7";
const CARTE_ICONE = "M9 4l-6 2v14l6-2 6 2 6-2V4l-6 2z M9 4v14 M15 6v14";
const CLOCHE = "M6 16V11a6 6 0 1112 0v5l2 2H4z M10 21h4";

function Icone({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
      <path
        d={d}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * La navigation du bas (maquette : trois onglets, rien de caché). Trois onglets, comme la maquette. La pastille dit combien de messages n'ont pas été vus ; le texte caché le dit aussi.
 */
export function Onglets({
  actif,
  nonLus,
}: {
  actif: "trajets" | "carte" | "messages";
  nonLus: number;
}) {
  return (
    <nav aria-label="Navigation principale" className="onglets">
      <a
        href={ACCUEIL}
        className="onglets__lien"
        aria-current={actif === "trajets" ? "page" : undefined}
      >
        <span className="onglets__icone">
          <Icone d={ROUTE} />
        </span>
        Mes trajets
      </a>
      <a
        href={CARTE}
        className="onglets__lien"
        aria-current={actif === "carte" ? "page" : undefined}
      >
        <span className="onglets__icone">
          <Icone d={CARTE_ICONE} />
        </span>
        Carte
      </a>
      <a
        href={MESSAGES}
        className="onglets__lien"
        aria-current={actif === "messages" ? "page" : undefined}
      >
        <span className="onglets__icone">
          <Icone d={CLOCHE} />
          {nonLus > 0 ? (
            <span className="onglets__pastille" aria-hidden="true">
              {nonLus}
            </span>
          ) : null}
        </span>
        Messages
        {nonLus > 0 ? (
          <span className="visuellement-cache">
            {" "}
            ({nonLus} nouveau{nonLus > 1 ? "x" : ""})
          </span>
        ) : null}
      </a>
    </nav>
  );
}
