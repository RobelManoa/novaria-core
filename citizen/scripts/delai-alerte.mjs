#!/usr/bin/env node
/**
 * Observateur du délai d'apparition d'une alerte (CIT-05) : l'application construite dans un vrai Chromium, sur écran de téléphone,
 * relie la passerelle réelle (relais de Vite). Il n'invente rien : il note l'instant où chaque alerte NOUVELLE apparaît à l'écran.
 * Ce script ne crée pas l'alerte : c'est `scripts/dev/citoyen_delai.py` (dev.py citoyen delai) qui envoie les mesures, lit l'instant
 * de création dans PostgreSQL et calcule le délai.
 *
 * Sortie standard : une ligne JSON par événement : {"evenement":"pret"} puis {"evenement":"vue","alert_id":"…","vue_ms":…} (époque, ms).
 * Variables : PORT_APERCU (défaut 5176), ATTENTE_S (défaut 240), CAPTURE (fichier PNG écrit quand la première alerte nouvelle apparaît).
 */
import { spawn } from "node:child_process";
import { setTimeout as attendre } from "node:timers/promises";
import { chromium } from "playwright-core";

const PORT = Number(process.env.PORT_APERCU ?? 5176);
const BASE = `http://127.0.0.1:${PORT}`;
const ATTENTE_MS = Number(process.env.ATTENTE_S ?? 240) * 1000;
const CAPTURE = process.env.CAPTURE;
const ligne = (objet) => process.stdout.write(`${JSON.stringify(objet)}\n`);

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
  const vues = new Set();
  let premiere = true;
  await page.exposeFunction("signaler", async (id, instant, nouvelle) => {
    if (vues.has(id)) return;
    vues.add(id);
    if (!nouvelle) return;
    ligne({ evenement: "vue", alert_id: id, vue_ms: instant });
    if (CAPTURE && premiere) {
      premiere = false;
      await page.screenshot({ path: CAPTURE, fullPage: false });
    }
  });
  await page.addInitScript(() => {
    // Les alertes présentes au premier affichage sont « anciennes » ; toute autre est nouvelle. L'instant est pris dans la page.
    let initial = true;
    const lire = () => {
      document.querySelectorAll("[data-alerte]").forEach((element) => {
        void window.signaler(element.getAttribute("data-alerte"), Date.now(), !initial);
      });
    };
    new MutationObserver(lire).observe(document, { childList: true, subtree: true });
    window.addEventListener("load", () => {
      // La première liste arrive après le chargement : on attend qu'elle soit affichée avant de dire « le départ est donné ».
      const prete = setInterval(() => {
        const section = document.querySelector("#titre-alertes")?.parentElement;
        if (section && !section.textContent?.includes("Chargement des alertes")) {
          clearInterval(prete);
          lire();
          initial = false;
          window.signaler("__pret__", Date.now(), false);
        }
      }, 100);
    });
  });
  await page.goto(BASE);
  await page.waitForFunction(
    () => {
      const section = document.querySelector("#titre-alertes")?.parentElement;
      return Boolean(section) && !section.textContent.includes("Chargement des alertes");
    },
    undefined,
    { timeout: 30000 },
  );
  await attendre(500);
  ligne({ evenement: "pret" });
  await attendre(ATTENTE_MS);
  await navigateur.close();
} catch (erreur) {
  console.error(erreur);
  code = 1;
} finally {
  apercu.kill();
}
process.exit(code);
