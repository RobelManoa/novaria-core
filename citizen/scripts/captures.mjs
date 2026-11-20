#!/usr/bin/env node
/**
 * Captures sur écran de téléphone (CIT-04) : l'application construite, un vrai Chromium, un écran de 390 × 844 pixels.
 *
 * - Capture 1 : l'API RÉELLE de la pile locale (la passerelle, `dev.py up` lancé), par le relais de Vite. Les données sont celles
 *   du simulateur, dites « simulées » à l'écran.
 * - Captures 2 à 7 : la réponse de l'API est FABRIQUÉE par ce script (mêmes six champs que le contrat) pour montrer ce que la pile
 *   ne produit pas à la demande : des états variés, le chargement, l'erreur, l'information ancienne. Elles le disent dans leur nom.
 *
 * Usage :  npm run build && npm run captures        (la pile locale doit tourner pour la capture 1)
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
const MAINTENANT = new Date("2026-11-20T09:57:00Z");
mkdirSync(DOSSIER, { recursive: true });

/** Un réseau de six carrefours : l'heure de pointe (nord et ouest saturés, est et sud ralentis), un carrefour fluide, un tronçon sans mesure. */
function reseauVarie(miseAJour = "2026-11-20T09:55:00Z") {
  const items = [];
  for (let c = 1; c <= 6; c += 1) {
    ["N", "E", "S", "W"].forEach((approach, i) => {
      let state = approach === "N" || approach === "W" ? "CONGESTED" : "SLOW";
      if (c === 3) state = "FREE_FLOW";
      if (c === 5 && approach === "S") state = "UNKNOWN";
      if (c === 6 && (approach === "E" || approach === "S")) state = "FREE_FLOW";
      items.push({
        road_segment_id: `ROAD_${String((c - 1) * 4 + i + 1).padStart(3, "0")}`,
        intersection_id: `INT_${String(c).padStart(2, "0")}`,
        approach,
        state,
        updated_at: miseAJour,
        simulated: true,
      });
    });
  }
  return { items };
}

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

const apercu = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], {
  stdio: "ignore",
});
try {
  await attendreServeur();
  const navigateur = await chromium.launch();
  const telephone = {
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: "fr-FR",
    timezoneId: "Europe/Paris",
  };

  async function prendre(
    nom,
    { reponse, colorScheme = "light", viewport, pleinePage = true, avant } = {},
  ) {
    const contexte = await navigateur.newContext({
      ...telephone,
      ...(viewport ? { viewport } : {}),
      colorScheme,
    });
    const page = await contexte.newPage();
    await page.clock.setFixedTime(MAINTENANT);
    if (reponse) await page.route("**/api/v1/public/congestion", reponse);
    await page.goto(BASE);
    if (avant) await avant(page);
    await page.screenshot({ path: `${DOSSIER}/CIT-04-${nom}.png`, fullPage: pleinePage });
    const texte = await page.locator("body").innerText();
    await contexte.close();
    console.log(`écrit CIT-04-${nom}.png`);
    return texte;
  }

  // 1. L'API réelle de la pile locale.
  const reel = await prendre("01-vue-principale-api-reelle-simulee", {
    avant: (page) =>
      page.getByRole("region", { name: "En un coup d'œil" }).waitFor({ timeout: 15000 }),
  });
  if (!reel.includes("Données simulées") || !reel.includes("Carrefour INT_01"))
    throw new Error("La capture 1 ne montre pas l'état réel attendu");

  // 2 et 3. États variés (réponse fabriquée) : une page entière, puis le haut de page seul (ce qu'on voit sans défiler).
  const varie = (route) => route.fulfill(json(reseauVarie()));
  const attenteVue = (page) => page.getByRole("region", { name: "En un coup d'œil" }).waitFor();
  await prendre("02-etats-varies-reponse-fabriquee", { reponse: varie, avant: attenteVue });
  await prendre("03-etats-varies-premier-ecran-reponse-fabriquee", {
    reponse: varie,
    avant: attenteVue,
    pleinePage: false,
  });

  // 4. Chargement : la réponse n'arrive jamais pendant la capture.
  await prendre("04-chargement-reponse-fabriquee", {
    reponse: () => {},
    pleinePage: false,
    avant: (page) => page.getByText("Chargement de la circulation…").waitFor(),
  });

  // 5. Erreur : le service est indisponible, aucune donnée à montrer.
  await prendre("05-erreur-service-indisponible-reponse-fabriquee", {
    reponse: (route) =>
      route.fulfill(
        json(
          {
            type: "x",
            title: "Service indisponible",
            status: 503,
            code: "UPSTREAM_UNAVAILABLE",
            detail: "x",
          },
          503,
        ),
      ),
    pleinePage: false,
    avant: (page) => page.getByRole("alert").waitFor(),
  });

  // 6. Information ancienne : les mesures datent d'une heure.
  await prendre("06-information-ancienne-reponse-fabriquee", {
    reponse: (route) => route.fulfill(json(reseauVarie("2026-11-20T08:50:00Z"))),
    pleinePage: false,
    avant: (page) => page.getByText("Information ancienne.").waitFor(),
  });

  // 7. Thème sombre, et 8. écran étroit (320 px) : lisibilité sans défilement horizontal.
  await prendre("07-theme-sombre-reponse-fabriquee", {
    reponse: varie,
    colorScheme: "dark",
    avant: attenteVue,
    pleinePage: false,
  });
  const etroit = await prendre("08-ecran-320-px-reponse-fabriquee", {
    reponse: varie,
    viewport: { width: 320, height: 640 },
    avant: attenteVue,
    pleinePage: false,
  });
  if (!etroit.includes("Carrefour INT_01"))
    throw new Error("La capture 8 ne montre pas la vue principale");

  // Contrôle : aucune page ne déborde en largeur (WCAG 1.4.10, reflux à 320 px).
  const contexte = await navigateur.newContext({
    ...telephone,
    viewport: { width: 320, height: 640 },
  });
  const page = await contexte.newPage();
  await page.route("**/api/v1/public/congestion", varie);
  await page.goto(BASE);
  await attenteVue(page);
  const largeurs = await page.evaluate(() => ({
    contenu: document.documentElement.scrollWidth,
    fenetre: window.innerWidth,
  }));
  await contexte.close();
  console.log(`largeur du contenu à 320 px : ${largeurs.contenu} (fenêtre : ${largeurs.fenetre})`);
  if (largeurs.contenu > largeurs.fenetre) throw new Error("Défilement horizontal à 320 px");
  await navigateur.close();
} finally {
  apercu.kill();
}
