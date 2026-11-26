// Dessine des diagrammes Mermaid en SVG dans un navigateur sans interface (utilisé par scripts/dev/site_docs.py).
//
//   node scripts/dev/site_mermaid.mjs ENTREE.json SORTIE.json CHEMIN/mermaid.min.js DOSSIER_AVEC_node_modules
//
// ENTREE.json : { "<empreinte>": "<texte Mermaid>", ... }
// SORTIE.json : { "<empreinte>": { "svg": "<svg…>" } ou { "erreur": "…" }, ... }
// Rien n'est envoyé sur le réseau : la bibliothèque est lue sur le disque, la page est vide.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const [, , entree, sortie, mermaidJs, dossier] = process.argv;
if (!entree || !sortie || !mermaidJs || !dossier) {
  console.error("usage : node site_mermaid.mjs ENTREE.json SORTIE.json mermaid.min.js DOSSIER");
  process.exit(2);
}
const require = createRequire(path.join(path.resolve(dossier), "x.js"));
const { chromium } = require("playwright-core");
const codes = JSON.parse(fs.readFileSync(entree, "utf8"));

let navigateur;
try {
  navigateur = await chromium.launch({ headless: true });
} catch (erreur) {
  navigateur = await chromium.launch({ headless: true, channel: "chrome" });
}
const page = await navigateur.newPage();
await page.setContent("<!doctype html><html><body></body></html>");
await page.addScriptTag({ path: path.resolve(mermaidJs) });
await page.evaluate(() => {
  const m = globalThis.mermaid || (globalThis.__esbuild_esm_mermaid_nm && (globalThis.__esbuild_esm_mermaid_nm.mermaid.default || globalThis.__esbuild_esm_mermaid_nm.mermaid));
  m.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict", flowchart: { htmlLabels: false }, fontFamily: "system-ui, sans-serif" });
  globalThis.__m = m;
});
const resultat = {};
for (const [empreinte, code] of Object.entries(codes)) {
  resultat[empreinte] = await page.evaluate(async ([id, texte]) => {
    try {
      const { svg } = await globalThis.__m.render(id, texte);
      return { svg };
    } catch (e) {
      return { erreur: String(e && e.message ? e.message : e) };
    }
  }, ["d" + empreinte, code]);
}
await navigateur.close();
fs.writeFileSync(sortie, JSON.stringify(resultat), "utf8");
console.log(`${Object.values(resultat).filter((r) => r.svg).length}/${Object.keys(resultat).length} diagrammes dessinés`);
