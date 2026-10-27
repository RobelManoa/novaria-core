// Génère les types TypeScript du client d'API à partir des contrats OpenAPI de contracts/openapi/.
//   npm run api:generate   écrit src/types/api/<service>.ts
//   npm run api:check      échoue si un fichier généré ne correspond plus au contrat (utilisé aussi par les tests)
import { readdir } from "node:fs/promises";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

/**
 * Services que le tableau de bord appelle par la passerelle. `collecte` est absent : son point
 * d'accès `POST /api/v1/measurements` reste sur le réseau interne (contracts/openapi/README.md).
 */
export const SERVICES = ["api-metier", "traitement", "alerte", "reponse"];

const CONTRATS = new URL("../../contracts/openapi/", import.meta.url);
const SORTIE = new URL("../src/types/api/", import.meta.url);

function entete(service) {
  return [
    "/**",
    ` * Fichier généré par « npm run api:generate » depuis contracts/openapi/${service}.openapi.yaml.`,
    " * Ne pas le modifier à la main : changer le contrat, puis régénérer.",
    " */",
    "",
    "",
  ].join("\n");
}

/** Services qui ont un contrat dans contracts/openapi/ et que la passerelle expose. */
export async function exposedContracts() {
  const noms = await readdir(CONTRATS);
  return noms
    .filter((nom) => nom.endsWith(".openapi.yaml"))
    .map((nom) => nom.replace(".openapi.yaml", ""))
    .filter((service) => service !== "collecte");
}

/** Contenu attendu de chaque fichier généré : { chemin relatif à frontend/ : texte }. */
export async function renderApiTypes() {
  const fichiers = {};
  for (const service of SERVICES) {
    const ast = await openapiTS(new URL(`${service}.openapi.yaml`, CONTRATS), {
      alphabetize: true,
    });
    fichiers[`src/types/api/${service}.ts`] = entete(service) + astToString(ast);
  }
  return fichiers;
}

/** Liste les fichiers générés absents ou différents du contrat. */
export async function outOfDate() {
  const attendus = await renderApiTypes();
  const perimes = [];
  for (const [chemin, texte] of Object.entries(attendus)) {
    const actuel = await readFile(new URL(`../${chemin}`, import.meta.url), "utf-8").catch(
      () => null,
    );
    if (actuel !== texte) perimes.push(chemin);
  }
  return perimes;
}

async function main() {
  if (process.argv.includes("--check")) {
    const perimes = await outOfDate();
    if (perimes.length === 0) {
      console.log("Types d'API à jour avec les contrats.");
      return;
    }
    console.error(`Types d'API périmés (contrat modifié ?) : ${perimes.join(", ")}`);
    console.error("Lancer « npm run api:generate », puis relire les erreurs de compilation.");
    process.exitCode = 1;
    return;
  }
  await mkdir(SORTIE, { recursive: true });
  for (const [chemin, texte] of Object.entries(await renderApiTypes())) {
    await writeFile(new URL(`../${chemin}`, import.meta.url), texte, "utf-8");
    console.log(`écrit ${chemin}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
