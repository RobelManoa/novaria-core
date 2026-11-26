#!/usr/bin/env node
/**
 * Captures de « Mes trajets » sur écran de téléphone (ADR-031, CIT-10) : l'application construite, un vrai Chromium, 390 × 844 pixels.
 * Les réponses de l'API sont FABRIQUÉES par ce script (mêmes champs que le contrat) : la pile ne produit pas à la demande un trajet bloqué, un
 * ralenti et un libre en même temps, ni une alerte qui naît pendant la capture. Les noms de fichiers le disent. La capture sur la VRAIE pile
 * vient de `dev.py parcours` (cas U4 et U5 : `CIT-07-parcours-usager-*.png`).
 *
 * Usage :  npm run build && npm run captures        (ou : python3 scripts/dev/dev.py citoyen captures)
 * Variables : CAPTURES_DOSSIER (défaut : ../docs/Capture d'ecran), PORT_APERCU (défaut 5175).
 */
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { setTimeout as attendre } from "node:timers/promises";
import { chromium } from "playwright-core";

const DOSSIER = resolve(process.env.CAPTURES_DOSSIER ?? "../docs/Capture d'ecran");
const PORT = Number(process.env.PORT_APERCU ?? 5175);
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(DOSSIER, { recursive: true });

const maintenant = Date.now();
const ilYa = (minutes) =>
  new Date(maintenant - minutes * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const APPROCHES = ["N", "E", "S", "W"];

/** Un réseau de 24 tronçons : la gare bloquée (nord), le marché ralenti, tout le reste fluide. */
function reseau(etats = {}) {
  const items = [];
  for (let i = 1; i <= 24; i += 1) {
    const id = `ROAD_${String(i).padStart(3, "0")}`;
    const defaut = id === "ROAD_001" ? "CONGESTED" : id === "ROAD_009" ? "SLOW" : "FREE_FLOW";
    items.push({
      road_segment_id: id,
      intersection_id: `INT_${String(Math.ceil(i / 4)).padStart(2, "0")}`,
      approach: APPROCHES[(i - 1) % 4],
      state: etats[id] ?? defaut,
      updated_at: ilYa(1),
      simulated: true,
    });
  }
  return { items };
}
const alerte = (id, troncon, gravite) => ({
  alert_id: id,
  road_segment_id: troncon,
  intersection_id: "INT_01",
  severity: gravite,
  opened_at: ilYa(0),
  simulated: true,
});
const json = (corps, status = 200) => ({
  status,
  contentType: status === 200 ? "application/json" : "application/problem+json",
  body: JSON.stringify(corps),
});

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

const WINDOWS = process.platform === "win32";
const apercu = spawn(
  WINDOWS ? "npx.cmd" : "npx",
  ["vite", "preview", "--port", String(PORT), "--strictPort"],
  {
    stdio: "ignore",
    shell: WINDOWS,
  },
);
let code = 0;
try {
  await attendreServeur();
  const navigateur = await chromium.launch();

  async function page({
    circulation = () => json(reseau()),
    alertes = () => json({ items: [] }),
    colorScheme = "light",
  } = {}) {
    const contexte = await navigateur.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      locale: "fr-FR",
      timezoneId: "Europe/Paris",
      colorScheme,
    });
    const p = await contexte.newPage();
    await p.route("**/api/v1/public/congestion", (route) => route.fulfill(circulation()));
    await p.route("**/api/v1/public/alerts", (route) => route.fulfill(alertes()));
    return p;
  }
  const prendre = async (p, nom, options = {}) => {
    await p.screenshot({ path: `${DOSSIER}/CIT-10-${nom}.png`, fullPage: false, ...options });
    console.log(`écrit CIT-10-${nom}.png`);
  };
  const trajets = (p) => p.getByRole("region", { name: /trajets/i });

  // 1. Première visite : des trajets pour essayer, avec leur verdict.
  let p = await page();
  await p.goto(BASE);
  await trajets(p).waitFor();
  await prendre(p, "01-premiere-visite-reponse-fabriquee");

  // 2. Un trajet gardé ; « Me prévenir » se règle dans son détail (capture 03), puis retour à l'accueil (capture 02).
  await p
    .getByRole("listitem", { name: "Aller à la gare" })
    .getByRole("button", { name: "Garder ce trajet" })
    .click();
  await p.getByRole("link", { name: "Aller à la gare" }).click();
  await p.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }).check();
  await prendre(p, "03-detail-du-trajet-reponse-fabriquee");
  await p.getByRole("link", { name: "Mes trajets" }).click();
  await trajets(p).waitFor();
  await prendre(p, "02-trajet-garde-reponse-fabriquee");

  // 4. Ajouter un trajet : les croix, le verdict du trajet choisi.
  await p.getByRole("link", { name: "Ajouter un trajet" }).click();
  await p.getByRole("button", { name: /^Avenue des Tilleuls, en venant du nord/ }).click();
  await p.getByRole("button", { name: /^Place de la Gare, en venant du nord/ }).click();
  await p.getByRole("region", { name: /^Votre trajet : 2 endroits/ }).scrollIntoViewIfNeeded();
  await prendre(p, "04-ajouter-un-trajet-reponse-fabriquee");

  // 11. La carte du réseau : le résumé, le plan, la fiche de la place la plus grave.
  await p.goto(`${BASE}/#/carte`);
  await p.getByRole("region", { name: "Plan" }).waitFor();
  await prendre(p, "11-carte-reponse-fabriquee");
  await p.context().close();

  // 5. Une alerte s'ouvre sur le trajet suivi : le message simulé apparaît en haut.
  let nouvelle = false;
  p = await page({
    alertes: () => json({ items: nouvelle ? [alerte("a1", "ROAD_004", "WARNING")] : [] }),
  });
  await p.goto(BASE);
  await trajets(p).waitFor();
  await p
    .getByRole("listitem", { name: "Aller à la gare" })
    .getByRole("button", { name: "Garder ce trajet" })
    .click();
  await p.getByRole("link", { name: "Aller à la gare" }).click();
  await p.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }).check();
  nouvelle = true;
  await p.getByRole("group", { name: "Message pour votre trajet" }).waitFor({ timeout: 15000 });
  await p.evaluate(() => window.scrollTo(0, 0));
  await prendre(p, "05-message-me-prevenir-reponse-fabriquee");

  // 9. L'écran « Messages » : le message reçu pendant la visite, le réglage trajet par trajet (le détail n'a pas d'onglets : retour d'abord).
  await p.getByRole("link", { name: "Mes trajets" }).click();
  await p.getByRole("link", { name: /^Messages/ }).click();
  await p.getByRole("region", { name: "Reçus pendant cette visite" }).waitFor();
  await prendre(p, "09-messages-reponse-fabriquee");

  // 10. Les réglages : les mots, ce qui est gardé et où, effacer.
  await p.getByRole("link", { name: "Mes trajets" }).click();
  await p.getByRole("link", { name: "Réglages et confidentialité" }).click();
  await p.getByRole("region", { name: "Vos trajets restent chez vous" }).waitFor();
  await prendre(p, "10-reglages-reponse-fabriquee");
  await p.context().close();

  // 6. Le service de circulation est indisponible : message clair.
  p = await page({
    circulation: () =>
      json(
        {
          type: "x",
          title: "Service indisponible",
          status: 503,
          code: "UPSTREAM_UNAVAILABLE",
          detail: "x",
          correlation_id: "c",
        },
        503,
      ),
  });
  await p.goto(BASE);
  await p.getByRole("alert").waitFor();
  await prendre(p, "06-service-indisponible-reponse-fabriquee");
  await p.context().close();

  // 7. Les mesures manquent : l'application dit sa prudence au lieu de répondre « Libre ».
  p = await page({
    circulation: () =>
      json({ items: reseau().items.filter((i) => i.road_segment_id !== "ROAD_004") }),
  });
  await p.goto(BASE);
  await trajets(p).waitFor();
  await prendre(p, "07-information-incomplete-reponse-fabriquee");
  await p.context().close();

  // 8. Mode sombre.
  p = await page({ colorScheme: "dark" });
  await p.goto(BASE);
  await trajets(p).waitFor();
  await prendre(p, "08-mode-sombre-reponse-fabriquee");
  await p.context().close();
  await navigateur.close();
} catch (erreur) {
  console.error(erreur);
  code = 1;
} finally {
  if (WINDOWS) spawn("taskkill", ["/pid", String(apercu.pid), "/T", "/F"], { stdio: "ignore" });
  else apercu.kill();
}
process.exit(code);
