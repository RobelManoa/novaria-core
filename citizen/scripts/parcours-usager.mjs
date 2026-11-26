#!/usr/bin/env node
/**
 * Le citoyen, vu par un vrai navigateur (CIT-07, ADR-031) : l'application construite dans Chromium, sur écran de téléphone, devant la VRAIE
 * passerelle (relais de Vite). Ce script ne crée aucune donnée : `scripts/dev/parcours_usager.py` (dev.py parcours) envoie les mesures,
 * lit l'état public, dit ce que le citoyen doit voir et, pour le cas d'échec, quand arrêter et relancer le service de circulation.
 *
 * Deux modes (variable MODE), un compte rendu JSON par ligne sur la sortie standard :
 *   affichage    : première visite (trajets proposés), puis le citoyen ajoute SON trajet (les tronçons TRONCONS) et lit son verdict (ATTENDU),
 *                  active « Me prévenir », recharge la page (le trajet est retrouvé), et seule la clé des trajets est gardée sur l'appareil.
 *   indisponible : même départ, puis le service de circulation est arrêté (le script attend la ligne « arret » sur son entrée standard) :
 *                  la page ouverte garde son trajet et dit que la mise à jour est impossible ; une page NEUVE dit « momentanément indisponible »
 *                  avec « Réessayer » ; après « reprise », la page ouverte se rétablit seule et « Réessayer » fonctionne.
 *
 * Variables : MODE, TRONCONS (JSON : ["ROAD_017", "ROAD_018"]), NOM (nom du trajet), ATTENDU (le titre du verdict : Libre, Ralenti, Bloqué…),
 *             PORT_APERCU (défaut 5178), CAPTURE, CAPTURE_PANNE (fichiers PNG), DELAI_S (défaut 60). La version construite doit exister.
 */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { setTimeout as attendre } from "node:timers/promises";
import { chromium } from "playwright-core";

const MODE = process.env.MODE ?? "affichage";
const TRONCONS = JSON.parse(process.env.TRONCONS ?? "[]");
const NOM = process.env.NOM ?? "Mon trajet";
const ATTENDU = process.env.ATTENDU ?? "";
const PORT = Number(process.env.PORT_APERCU ?? 5178);
const BASE = `http://127.0.0.1:${PORT}`;
const DELAI_MS = Number(process.env.DELAI_S ?? 60) * 1000;
const CAPTURE = process.env.CAPTURE;
const CAPTURE_PANNE = process.env.CAPTURE_PANNE;
const CLE = "novaria-citoyen-trajets";

// Les mêmes noms que l'application : `src/lieux.json` est la seule source.
const LIEUX = JSON.parse(readFileSync(new URL("../src/lieux.json", import.meta.url), "utf8"));
const COTES = ["du nord", "de l'est", "du sud", "de l'ouest"];
function nomDuTroncon(id) {
  const rang = Number(/^ROAD_(\d{3})$/.exec(id)?.[1]) - 1;
  const intersection = Object.keys(LIEUX)[Math.floor(rang / 4)];
  return `${LIEUX[intersection]}, en venant ${COTES[rang % 4]}`;
}

let code = 0;
/** Une ligne de compte rendu ; un compte rendu « ok: false » fait échouer le script. */
const dire = (objet) => {
  process.stdout.write(`${JSON.stringify(objet)}\n`);
  if (objet.ok === false) code = 1;
};

async function attendreServeur() {
  for (let i = 0; i < 60; i += 1) {
    try {
      if ((await fetch(BASE)).ok) return;
    } catch {
      /* pas encore prêt */
    }
    await attendre(500);
  }
  throw new Error("L'aperçu de Vite ne répond pas");
}

/** Les lignes que le script reçoit de `parcours_usager.py` : « arret », « reprise ». */
const lignes = [];
const recus = [];
createInterface({ input: process.stdin }).on("line", (ligne) => {
  const attente = lignes.shift();
  if (attente) attente(ligne.trim());
  else recus.push(ligne.trim());
});
const recevoir = () =>
  new Promise((resolve) => {
    const deja = recus.shift();
    if (deja !== undefined) resolve(deja);
    else lignes.push(resolve);
  });

const texte = async (locator) => (await locator.innerText()).replace(/\s+/g, " ");
const regionTrajets = (page) => page.getByRole("region", { name: /trajets/i });

/** Le citoyen ajoute son trajet : cocher les tronçons, le nommer, valider. */
async function ajouterTrajet(page) {
  await page.getByRole("link", { name: "Ajouter un trajet" }).click();
  // Chaque côté d'une place est un bouton « <endroit> : <état> » : on le touche pour le choisir.
  for (const id of TRONCONS) {
    await page.getByRole("button", { name: new RegExp(`^${nomDuTroncon(id)}`) }).click();
  }
  await page.getByLabel(/Nom du trajet/).fill(NOM);
  await page.getByRole("button", { name: "Ajouter ce trajet" }).click();
  await regionTrajets(page).getByRole("listitem", { name: NOM }).waitFor({ timeout: DELAI_MS });
}

const WINDOWS = process.platform === "win32";
// Sous Windows, `npx` est un fichier .cmd : il faut `shell: true`, et l'arrêt du serveur passe par `taskkill` (non vérifié sous Windows).
const apercu = spawn(
  WINDOWS ? "npx.cmd" : "npx",
  ["vite", "preview", "--port", String(PORT), "--strictPort"],
  { stdio: "ignore", shell: WINDOWS },
);
const arreter = () => {
  if (WINDOWS) spawn("taskkill", ["/pid", String(apercu.pid), "/T", "/F"], { stdio: "ignore" });
  else apercu.kill();
};

try {
  await attendreServeur();
  const navigateur = await chromium.launch();
  const contexte = await navigateur.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: "fr-FR",
    timezoneId: "Europe/Paris",
  });
  const page = await contexte.newPage();
  const demarrage = Date.now();

  // 1. Première visite : des trajets pour essayer, la mention des données simulées, rien de gardé sur l'appareil.
  await page.goto(BASE);
  await regionTrajets(page).waitFor({ timeout: DELAI_MS });
  const proposes = await regionTrajets(page).getByRole("listitem").count();
  const avantAjout = await page.evaluate(() => localStorage.length);
  const bandeau = (await texte(page.getByRole("note").first())).includes("Données simulées");

  // 2. Il ajoute son trajet, lit son verdict, demande à être prévenu.
  await ajouterTrajet(page);
  const carte = regionTrajets(page).getByRole("listitem", { name: NOM });
  const contenu = await texte(carte);
  const verdictLu = contenu.includes(ATTENDU);
  const phrase = /Vous pouvez partir|prévoyez|Prévoyez|ne vous fiez pas|prudence/.test(contenu);
  // « Me prévenir » se règle dans le détail du trajet : on y entre par la carte, puis on revient à l'accueil.
  await carte.getByRole("link", { name: NOM }).click();
  await page.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }).check();
  await page.getByRole("link", { name: "Mes trajets" }).click();
  await regionTrajets(page).getByRole("listitem", { name: NOM }).waitFor({ timeout: DELAI_MS });

  // 3. Il recharge la page : son trajet est retrouvé ; seule la clé des trajets est sur l'appareil ; aucun cookie.
  await page.reload();
  const retrouvee = regionTrajets(page).getByRole("listitem", { name: NOM });
  await retrouvee.waitFor({ timeout: DELAI_MS });
  const prevenirGarde = (await texte(retrouvee)).includes("Je suis prévenu");
  const cles = await page.evaluate(() => Object.keys(localStorage));
  const cookies = (await contexte.cookies()).length;
  const technique = /ROAD_|INT_|UNKNOWN|CONGESTED|FREE_FLOW|undefined|\[object/.test(
    await page.locator("body").innerText(),
  );
  if (CAPTURE) await page.screenshot({ path: CAPTURE, fullPage: false });
  dire({
    evenement: "affichage",
    ok:
      proposes >= 3 &&
      avantAjout === 0 &&
      bandeau &&
      verdictLu &&
      phrase &&
      prevenirGarde &&
      cles.length === 1 &&
      cles[0] === CLE &&
      cookies === 0 &&
      !technique,
    trajets_proposes: proposes,
    rien_garde_avant: avantAjout === 0,
    bandeau_simule: bandeau,
    verdict_attendu: ATTENDU,
    verdict_lu: verdictLu,
    phrase_de_decision: phrase,
    trajet_retrouve_apres_rechargement: prevenirGarde,
    cles_sur_l_appareil: cles,
    cookies,
    mot_technique: technique,
    delai_ms: Date.now() - demarrage,
  });

  if (MODE === "indisponible" && code === 0) {
    dire({ evenement: "pret" });
    if ((await recevoir()) !== "arret") throw new Error("ordre inattendu : « arret » attendu");

    // 1. La page ouverte : le trajet reste, et elle dit que la mise à jour est impossible. « Actualiser » force une lecture.
    await page.getByRole("button", { name: "Actualiser" }).click();
    const notice = page.getByText("Mise à jour impossible");
    await notice.waitFor({ timeout: DELAI_MS });
    const texteNotice = await texte(notice.locator(".."));
    const garde = await regionTrajets(page).getByRole("listitem", { name: NOM }).isVisible();
    dire({
      evenement: "panne_page_ouverte",
      ok:
        garde &&
        texteNotice.includes("momentanément indisponible") &&
        texteNotice.includes("dernière information connue"),
      trajet_garde: garde,
      texte: texteNotice,
    });

    // 2. Une page NEUVE pendant la panne : message clair et « Réessayer », rien de technique.
    const neuve = await contexte.newPage();
    await neuve.goto(BASE);
    const erreur = neuve.getByRole("alert");
    await erreur.waitFor({ timeout: DELAI_MS });
    const texteErreur = await texte(erreur);
    const reessayer = await erreur.getByRole("button", { name: "Réessayer" }).count();
    const bandeauNeuve = (await texte(neuve.getByRole("note").first())).includes(
      "Données simulées",
    );
    const technique2 = /50[0-9]|UPSTREAM|nginx|Traceback|undefined|\[object|ROAD_|INT_/i.test(
      await neuve.locator("body").innerText(),
    );
    dire({
      evenement: "panne_page_neuve",
      ok:
        texteErreur.includes("momentanément indisponible") &&
        reessayer === 1 &&
        bandeauNeuve &&
        !technique2,
      texte: texteErreur,
      bouton_reessayer: reessayer === 1,
      bandeau_simule: bandeauNeuve,
      message_technique: technique2,
    });
    if (CAPTURE_PANNE) await neuve.screenshot({ path: CAPTURE_PANNE, fullPage: false });

    // 3. Le service revient : la page ouverte se rétablit (plus de message), « Réessayer » de la page neuve rend le trajet.
    dire({ evenement: "attente_reprise" });
    if ((await recevoir()) !== "reprise") throw new Error("ordre inattendu : « reprise » attendu");
    await page.getByRole("button", { name: "Actualiser" }).click();
    await notice.waitFor({ state: "detached", timeout: DELAI_MS });
    await erreur.getByRole("button", { name: "Réessayer" }).click();
    const retablie = regionTrajets(neuve).getByRole("listitem", { name: NOM });
    await retablie.waitFor({ timeout: DELAI_MS });
    const apresReessai = (await texte(retablie)).includes(ATTENDU);
    dire({
      evenement: "reprise",
      ok: apresReessai,
      page_ouverte_retablie: true,
      apres_reessayer: apresReessai,
    });
  }
  await navigateur.close();
} catch (erreur) {
  dire({ evenement: "erreur", message: String(erreur?.message ?? erreur).slice(0, 300) });
  code = 1;
} finally {
  arreter();
}
process.exit(code);
