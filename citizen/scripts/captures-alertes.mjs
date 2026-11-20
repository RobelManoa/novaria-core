#!/usr/bin/env node
/**
 * Captures des alertes et du suivi sur écran de téléphone (CIT-05) : l'application construite, un vrai Chromium, 390 × 844 pixels.
 * Les réponses de l'API sont FABRIQUÉES par ce script (mêmes six champs que le contrat) : la pile ne produit pas à la demande une
 * alerte de chaque gravité ni une alerte qui naît pendant la capture. Les noms de fichiers le disent. La capture d'une alerte
 * RÉELLE, créée par le service, vient de `dev.py citoyen delai`.
 *
 * Usage :  npm run build && npm run captures:alertes
 * Variables : CAPTURES_DOSSIER (défaut : ../docs/Capture d'ecran), PORT_APERCU (défaut 5177).
 */
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { setTimeout as attendre } from "node:timers/promises";
import { chromium } from "playwright-core";

const DOSSIER = resolve(process.env.CAPTURES_DOSSIER ?? "../docs/Capture d'ecran");
const PORT = Number(process.env.PORT_APERCU ?? 5177);
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(DOSSIER, { recursive: true });

const maintenant = Date.now();
const ilYa = (minutes) =>
  new Date(maintenant - minutes * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const alerte = (id, troncon, carrefour, gravite, minutes) => ({
  alert_id: id,
  road_segment_id: troncon,
  intersection_id: carrefour,
  severity: gravite,
  opened_at: ilYa(minutes),
  simulated: true,
});
const reseau = {
  items: [
    ["ROAD_001", "INT_01", "N", "CONGESTED"],
    ["ROAD_002", "INT_01", "E", "SLOW"],
    ["ROAD_003", "INT_01", "S", "FREE_FLOW"],
    ["ROAD_004", "INT_01", "W", "FREE_FLOW"],
  ].map(([road_segment_id, intersection_id, approach, state]) => ({
    road_segment_id,
    intersection_id,
    approach,
    state,
    updated_at: ilYa(1),
    simulated: true,
  })),
};
const json = (corps) => ({
  status: 200,
  contentType: "application/json",
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
let code = 0;
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
  const base = [
    alerte("a1", "ROAD_001", "INT_01", "CRITICAL", 12),
    alerte("a2", "ROAD_002", "INT_01", "WARNING", 7),
    alerte("a3", "ROAD_017", "INT_05", "INFO", 3),
  ];
  let nouvelle = false;
  await page.route("**/api/v1/public/congestion", (route) => route.fulfill(json(reseau)));
  await page.route("**/api/v1/public/alerts", (route) =>
    route.fulfill(
      json({
        items: nouvelle ? [alerte("a4", "ROAD_002", "INT_01", "CRITICAL", 0), ...base] : base,
      }),
    ),
  );
  const prendre = async (nom, options = {}) => {
    await page.screenshot({ path: `${DOSSIER}/CIT-05-${nom}.png`, ...options });
    console.log(`écrit CIT-05-${nom}.png`);
  };

  await page.goto(BASE);
  await page.getByText("3 alertes en cours").waitFor();
  await prendre("01-liste-des-alertes-reponse-fabriquee", { fullPage: false });

  await page.getByRole("region", { name: "Suivre un tronçon" }).scrollIntoViewIfNeeded();
  await prendre("02-consentement-reponse-fabriquee", { fullPage: false });

  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Suivre le tronçon ROAD_002" }).first().click();
  await page.getByText("Tronçons suivis").waitFor();
  await prendre("03-troncon-suivi-reponse-fabriquee", { fullPage: false });

  nouvelle = true; // le « service » crée une alerte sur le tronçon suivi : l'application la lit au prochain tour (5 s)
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByRole("group", { name: "Notification simulée" }).waitFor({ timeout: 15000 });
  await prendre("04-notification-simulee-reponse-fabriquee", { fullPage: false });
  await navigateur.close();
} catch (erreur) {
  console.error(erreur);
  code = 1;
} finally {
  apercu.kill();
}
process.exit(code);
