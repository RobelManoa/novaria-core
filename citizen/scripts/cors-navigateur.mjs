#!/usr/bin/env node
/**
 * Le CORS de l'espace public, vu par un vrai navigateur (CIT-06) : Chromium ouvre une page « sur » une origine, puis lit la VRAIE
 * passerelle d'une autre origine. `curl` ne prouve pas ce que le navigateur bloque : seul un navigateur applique CORS.
 *
 * Chaque origine est servie par un VRAI petit serveur local (une page vide) : une page fabriquée par Playwright serait traitée par
 * Chromium comme « publique » et son appel vers une adresse locale refusé pour une autre raison que CORS. Les appels vers la
 * passerelle ne sont pas interceptés. La requête de lecture reprend exactement celle de `src/api.ts` (GET, Accept, credentials omit,
 * cache no-store). L'origine de l'équipe est le vrai tableau de bord (conteneur `frontend`) quand il tourne.
 *
 * Usage :  python3 scripts/dev/dev.py citoyen cors   (la pile doit tourner)
 * Variables : GATEWAY (défaut http://127.0.0.1:8000), CORS_PUBLIC_ORIGINS, CORS_ALLOWED_ORIGINS (valeurs de .env, sinon celles de docker-compose.yml).
 */
import { createServer } from "node:http";
import { chromium } from "playwright-core";

const PASSERELLE = process.env.GATEWAY ?? "http://127.0.0.1:8000";
const PREMIERE = (liste, defaut) => (liste ?? defaut).split(",")[0].trim();
const CITOYENNE = PREMIERE(process.env.CORS_PUBLIC_ORIGINS, "http://127.0.0.1:5174");
const EQUIPE = PREMIERE(process.env.CORS_ALLOWED_ORIGINS, "http://localhost:8080");

/** Un serveur local qui sert une page vide ; rend son origine. Port occupé (l'application citoyenne tourne déjà) : on s'en sert. */
async function servir(port) {
  const serveur = createServer((_, reponse) => {
    reponse
      .writeHead(200, { "Content-Type": "text/html" })
      .end("<!doctype html><title>essai</title>");
  });
  const arret = () => new Promise((fin) => serveur.close(fin));
  return new Promise((resolve) => {
    serveur.once("error", () =>
      resolve({ origine: `http://127.0.0.1:${port}`, arret: async () => {} }),
    );
    serveur.listen(port, "127.0.0.1", () => {
      resolve({ origine: `http://127.0.0.1:${serveur.address().port}`, arret });
    });
  });
}
const inconnue = await servir(0); // un port libre quelconque : une origine que personne n'a autorisée
const INCONNUE = inconnue.origine;
const citoyenne = CITOYENNE.startsWith("http://127.0.0.1:")
  ? await servir(Number(CITOYENNE.split(":")[2]))
  : null;

const navigateur = await chromium.launch();
const resultats = [];

/** Joue `action` dans une page d'origine `origine` ; rend {ok, statut} ou {bloque: true} quand le navigateur refuse la lecture. */
async function depuis(origine, action) {
  const contexte = await navigateur.newContext();
  const page = await contexte.newPage();
  await page.goto(`${origine}/essai`);
  const sortie = await page.evaluate(action, PASSERELLE);
  await contexte.close();
  return sortie;
}

const lire = async (base, chemin, options = {}) => {
  try {
    const reponse = await fetch(`${base}${chemin}`, {
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json" },
      ...options,
    });
    const corps = await reponse.json().catch(() => null);
    return { bloque: false, statut: reponse.status, items: Array.isArray(corps?.items) };
  } catch (erreur) {
    return { bloque: true, erreur: erreur instanceof TypeError ? "TypeError" : String(erreur) };
  }
};

function verifier(nom, obtenu, attendu) {
  const bon =
    attendu === "lit" ? !obtenu.bloque && obtenu.statut === 200 && obtenu.items : obtenu.bloque;
  resultats.push({
    nom,
    attendu,
    obtenu: obtenu.bloque ? "bloqué par le navigateur" : `HTTP ${obtenu.statut}`,
    bon,
  });
  console.log(
    `${bon ? "OK " : "KO "} ${nom} → ${obtenu.bloque ? "bloqué par le navigateur" : `HTTP ${obtenu.statut}`} (attendu : ${attendu === "lit" ? "lecture" : "blocage"})`,
  );
}

const fonctionLire = `(${lire.toString()})`;
const appeler = (chemin, options) =>
  new Function(
    "base",
    `return ${fonctionLire}(base, ${JSON.stringify(chemin)}, ${JSON.stringify(options ?? {})});`,
  );

try {
  const rien = (chemin, options) => appeler(chemin, options);
  verifier(
    `page ${CITOYENNE} lit /api/v1/public/alerts`,
    await depuis(CITOYENNE, rien("/api/v1/public/alerts")),
    "lit",
  );
  verifier(
    `page ${CITOYENNE} lit /api/v1/public/congestion`,
    await depuis(CITOYENNE, rien("/api/v1/public/congestion")),
    "lit",
  );
  verifier(
    `page ${CITOYENNE} envoie un jeton d'équipe à /api/v1/public/alerts`,
    await depuis(
      CITOYENNE,
      rien("/api/v1/public/alerts", {
        headers: { Accept: "application/json", Authorization: "Bearer jeton-d-essai" },
      }),
    ),
    "bloque",
  );
  verifier(
    `page ${CITOYENNE} écrit (POST) sur /api/v1/public/alerts`,
    await depuis(
      CITOYENNE,
      rien("/api/v1/public/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    ),
    "bloque",
  );
  verifier(
    `page ${CITOYENNE} lit l'API d'équipe /api/v1/alerts`,
    await depuis(CITOYENNE, rien("/api/v1/alerts")),
    "bloque",
  );
  verifier(
    `page ${INCONNUE} lit /api/v1/public/alerts`,
    await depuis(INCONNUE, rien("/api/v1/public/alerts")),
    "bloque",
  );
  verifier(
    `page ${EQUIPE} (tableau de bord) lit /api/v1/public/alerts`,
    await depuis(EQUIPE, rien("/api/v1/public/alerts")),
    "bloque",
  );
  await navigateur.close();
  await inconnue.arret();
  await citoyenne?.arret();
  const mauvais = resultats.filter((r) => !r.bon);
  console.log(`\n${resultats.length - mauvais.length}/${resultats.length} conformes.`);
  process.exit(mauvais.length === 0 ? 0 : 1);
} catch (erreur) {
  console.error(erreur);
  await navigateur.close();
  await inconnue.arret();
  await citoyenne?.arret();
  process.exit(1);
}
