// Tests de gateway/auth.js sous Node (le même fichier tourne sous njs dans nginx) : décodage et contrôle du jeton,
// rôles, clé inutilisable, CORS, en-têtes. Sans Docker, en quelques millisecondes.
//
// Lancer :  node --test gateway/tests/
// Les clés sont générées à l'exécution : aucune valeur secrète n'est écrite ici.

import assert from "node:assert/strict";
import { createHmac, randomBytes } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import auth from "../auth.js";

const KEY = randomBytes(36).toString("base64url");
const NOW = 1_800_000_000;

const b64 = (value) => Buffer.from(typeof value === "string" ? value : JSON.stringify(value)).toString("base64url");

function token({ key = KEY, header = { alg: "HS256", typ: "JWT" }, claims = {}, drop = [], sign = true } = {}) {
  const payload = { sub: "u-1", role: "viewer", iat: NOW, exp: NOW + 600, ...claims };
  for (const name of drop) delete payload[name];
  const head = b64(header);
  const body = b64(payload);
  if (!sign) return `${head}.${body}.`;
  return `${head}.${body}.${createHmac("sha256", key).update(`${head}.${body}`).digest("base64url")}`;
}

// --------------------------------------------------------------------------- decode
test("un jeton valide est accepté, avec son sujet et son rôle", () => {
  assert.deepEqual(auth.decode(token({ claims: { sub: "u-9", role: "operator" } }), KEY, NOW), {
    ok: true,
    subject: "u-9",
    role: "operator",
  });
});

test("chaque rôle connu est accepté, aucun autre", () => {
  for (const role of ["viewer", "operator", "admin"]) assert.equal(auth.decode(token({ claims: { role } }), KEY, NOW).ok, true);
  for (const role of ["root", "", "Admin", "ADMIN", null, 1, ["admin"], "constructor", "toString", "__proto__"]) {
    assert.equal(auth.decode(token({ claims: { role } }), KEY, NOW).ok, false, String(role));
  }
});

test("un jeton signé par une autre clé, ou altéré, est refusé", () => {
  assert.equal(auth.decode(token({ key: randomBytes(36).toString("base64url") }), KEY, NOW).ok, false);
  const [head, body, signature] = token().split(".");
  const forged = b64({ sub: "u-1", role: "admin", iat: NOW, exp: NOW + 600 });
  assert.equal(auth.decode(`${head}.${forged}.${signature}`, KEY, NOW).ok, false); // rôle promu, signature d'origine
  assert.equal(auth.decode(`${head}.${body}.${signature.slice(0, -2)}AA`, KEY, NOW).ok, false);
  assert.equal(auth.decode(`${head}.${body}.${signature}A`, KEY, NOW).ok, false);
  assert.equal(auth.decode(`${head}.${body}.`, KEY, NOW).ok, false);
});

test("l'algorithme est fixé à HS256 : none, HS384, RS256, absent, casse différente sont refusés", () => {
  assert.equal(auth.decode(token({ header: { alg: "none", typ: "JWT" }, sign: false }), KEY, NOW).ok, false);
  assert.equal(auth.decode(token({ header: { alg: "none" } }), KEY, NOW).ok, false);
  for (const alg of ["HS384", "HS512", "RS256", "ES256", "hs256", "Hs256", "", null, undefined]) {
    assert.equal(auth.decode(token({ header: { alg } }), KEY, NOW).ok, false, String(alg));
  }
  assert.equal(auth.decode(token({ header: { typ: "JWT" } }), KEY, NOW).ok, false);
});

test("les revendications sont toutes obligatoires et de bon type", () => {
  for (const name of ["sub", "role", "iat", "exp"]) assert.equal(auth.decode(token({ drop: [name] }), KEY, NOW).ok, false, name);
  for (const claims of [
    { sub: "" }, { sub: 12 }, { sub: null }, { sub: "x".repeat(201) },
    { iat: "1800000000" }, { exp: "1800000600" }, { iat: null }, { exp: null }, { exp: NaN }, { iat: true },
  ]) {
    assert.equal(auth.decode(token({ claims }), KEY, NOW).ok, false, JSON.stringify(claims));
  }
});

test("l'expiration est contrôlée, au dernier instant près", () => {
  assert.equal(auth.decode(token({ claims: { exp: NOW + 1 } }), KEY, NOW).ok, true);
  assert.equal(auth.decode(token({ claims: { exp: NOW } }), KEY, NOW).ok, false); // expire à cet instant
  assert.equal(auth.decode(token({ claims: { exp: NOW - 1 } }), KEY, NOW).ok, false);
});

test("un jeton émis dans le futur est refusé au-delà de 30 secondes de tolérance", () => {
  assert.equal(auth.decode(token({ claims: { iat: NOW + 30 } }), KEY, NOW).ok, true);
  assert.equal(auth.decode(token({ claims: { iat: NOW + 31 } }), KEY, NOW).ok, false);
});

test("un jeton mal formé est refusé sans lever d'exception", () => {
  const cas = [
    "", "x", "..", "a.b", "a.b.c.d", "a.b.c", ".b.c", "a..c", "a.b.", "é.é.é", "a b.c.d", "e30.e30.", "e30.e30.AA",
    "null.null.null", `${b64("[]")}.${b64("[]")}.${b64("x")}`, `${b64("not json")}.${b64("{}")}.${b64("x")}`,
    "x".repeat(4097), undefined, null, 123, {}, [],
  ];
  for (const valeur of cas) assert.equal(auth.decode(valeur, KEY, NOW).ok, false, String(valeur).slice(0, 20));
});

test("la signature est comparée en entier : une signature plus courte ou plus longue est refusée", () => {
  const [head, body, signature] = token().split(".");
  assert.equal(auth.decode(`${head}.${body}.${signature.slice(0, 20)}`, KEY, NOW).ok, false);
  assert.equal(auth.decode(`${head}.${body}.${signature}${signature}`, KEY, NOW).ok, false);
});

// --------------------------------------------------------------------------- bearerToken
test("seul l'en-tête « Bearer <jeton> » donne un jeton", () => {
  assert.equal(auth.bearerToken("Bearer abc.def.ghi"), "abc.def.ghi");
  assert.equal(auth.bearerToken("bearer abc"), "abc");
  assert.equal(auth.bearerToken("  Bearer   abc  "), "abc");
  for (const valeur of ["Basic abc", "abc", "Bearer", "Bearer ", "Bearerabc", "Bearer a b", undefined, null, 1, ""]) {
    assert.equal(auth.bearerToken(valeur), null, String(valeur));
  }
});

// --------------------------------------------------------------------------- clé
test("une clé absente, trop courte ou d'exemple hors local est un problème", () => {
  assert.equal(auth.keyProblem(KEY, "local"), null);
  assert.equal(auth.keyProblem("x".repeat(32), "local"), null);
  assert.ok(auth.keyProblem("x".repeat(31), "local"));
  assert.ok(auth.keyProblem("", "local"));
  assert.ok(auth.keyProblem(undefined, "local"));
  assert.ok(auth.keyProblem(null, "local"));
  const exemple = "change-me-local-" + KEY;
  assert.equal(auth.keyProblem(exemple, "local"), null); // tolérée en local seulement
  assert.ok(auth.keyProblem(exemple, "production"));
  assert.ok(auth.keyProblem(exemple, "staging"));
  assert.equal(auth.keyProblem(KEY, "production"), null);
});

// --------------------------------------------------------------------------- table des routes
const ROUTES = [
  { method: "GET", re: /^\/api\/v1\/alerts$/, role: "viewer" },
  { method: "POST", re: /^\/api\/v1\/alerts\/[^/]+\/resolve$/, role: "operator" },
  { method: "GET", re: /^\/api\/v1\/health$/, role: null },
];

test("le rôle exigé vient de la table : méthode et chemin ensemble", () => {
  assert.equal(auth.requiredRole(ROUTES, "GET", "/api/v1/alerts"), "viewer");
  assert.equal(auth.requiredRole(ROUTES, "POST", "/api/v1/alerts/INT_01/resolve"), "operator");
  assert.equal(auth.requiredRole(ROUTES, "GET", "/api/v1/health"), null); // publique
  assert.equal(auth.requiredRole(ROUTES, "POST", "/api/v1/alerts"), undefined); // autre méthode : inconnue
  assert.equal(auth.requiredRole(ROUTES, "GET", "/api/v1/alerts/INT_01/resolve"), undefined);
  assert.equal(auth.requiredRole(ROUTES, "GET", "/api/v1/alerts/x"), undefined);
  assert.equal(auth.requiredRole(ROUTES, "GET", "/api/v1/alertsx"), undefined);
});

// --------------------------------------------------------------------------- CORS
test("les origines viennent d'une liste exacte : un joker, un chemin ou un hôte voisin sont écartés", () => {
  const origins = auth.parseOrigins(" http://localhost:8080 , https://app.example,*, http://x/chemin,ftp://x, http://a b ,http://[::1]:80,");
  assert.deepEqual(origins, ["http://localhost:8080", "https://app.example"]);
  assert.deepEqual(auth.parseOrigins(""), []);
  assert.deepEqual(auth.parseOrigins(undefined), []);
  assert.equal(auth.allowedOrigin(origins, "http://localhost:8080"), "http://localhost:8080");
  for (const origine of ["http://localhost:8080.evil.example", "http://localhost", "HTTP://LOCALHOST:8080", "null", "*", "", undefined]) {
    assert.equal(auth.allowedOrigin(origins, origine), null, String(origine));
  }
});

function headersFor(overrides = {}) {
  return auth.responseHeaders({
    origins: ["http://localhost:8080"], origin: undefined, method: "GET", path: "/api/v1/alerts",
    correlationId: "abc", forwardedProto: undefined, ...overrides,
  });
}

test("les en-têtes de sécurité sont posés sur toute réponse", () => {
  const h = headersFor();
  assert.equal(h["X-Content-Type-Options"], "nosniff");
  assert.equal(h["X-Frame-Options"], "DENY");
  assert.equal(h["Referrer-Policy"], "no-referrer");
  assert.equal(h["Content-Security-Policy"], "default-src 'none'; frame-ancestors 'none'");
  assert.equal(h["X-Correlation-ID"], "abc");
  assert.equal(h["Cache-Control"], undefined);
  assert.equal(h["Strict-Transport-Security"], undefined);
});

test("l'authentification et le flux ne sont pas mis en cache", () => {
  for (const path of ["/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/events/stream"]) {
    assert.equal(headersFor({ path })["Cache-Control"], "no-store", path);
  }
  assert.equal(headersFor({ path: "/api/v1/authx" })["Cache-Control"], undefined);
});

test("HSTS seulement derrière un point qui parle TLS", () => {
  assert.match(headersFor({ forwardedProto: "https" })["Strict-Transport-Security"], /max-age=31536000/);
  assert.equal(headersFor({ forwardedProto: "http" })["Strict-Transport-Security"], undefined);
});

test("CORS : l'origine autorisée est recopiée, jamais de cookie, la pré-vérification ajoute méthodes et en-têtes", () => {
  const simple = headersFor({ origin: "http://localhost:8080" });
  assert.equal(simple["Access-Control-Allow-Origin"], "http://localhost:8080");
  assert.equal(simple["Vary"], "Origin");
  assert.match(simple["Access-Control-Expose-Headers"], /X-Correlation-ID.*Retry-After/);
  assert.equal(simple["Access-Control-Allow-Methods"], undefined);
  assert.equal(simple["Access-Control-Allow-Credentials"], undefined);
  const prevue = headersFor({ origin: "http://localhost:8080", method: "OPTIONS" });
  assert.equal(prevue["Access-Control-Allow-Methods"], "GET, POST, PATCH, OPTIONS");
  assert.equal(prevue["Access-Control-Allow-Headers"], "Authorization, Content-Type, X-Correlation-ID");
  assert.equal(prevue["Access-Control-Max-Age"], "600");
  assert.equal(prevue["Access-Control-Allow-Credentials"], undefined);
});

test("CORS : une origine inconnue ne reçoit aucun en-tête d'autorisation ; sans liste, aucun en-tête CORS", () => {
  const inconnue = headersFor({ origin: "http://evil.example" });
  assert.equal(inconnue["Access-Control-Allow-Origin"], undefined);
  assert.equal(inconnue["Vary"], "Origin"); // la réponse dépend de l'origine : les caches le savent
  const fermee = headersFor({ origins: [], origin: "http://localhost:8080" });
  assert.equal(fermee["Access-Control-Allow-Origin"], undefined);
  assert.equal(fermee["Vary"], undefined);
});

// --------------------------------------------------------------------------- gestionnaires (verify)
function handlers(env, routes) {
  const dossier = mkdtempSync(join(tmpdir(), "gw-"));
  const fichier = join(dossier, "routes.json");
  writeFileSync(fichier, JSON.stringify(routes));
  return auth.createHandlers(env, fichier);
}

const TABLE = [
  { method: "GET", pattern: "^/api/v1/alerts$", role: "viewer" },
  { method: "POST", pattern: "^/api/v1/alerts/[^/]+/resolve$", role: "operator" },
  { method: "PATCH", pattern: "^/api/v1/alert\\-rules/[^/]+$", role: "admin" },
  { method: "GET", pattern: "^/api/v1/health$", role: null },
];

function requete({ method = "GET", uri = "/api/v1/alerts", authorization, origin } = {}) {
  const sortie = { status: null, headers: {}, errors: [] };
  const r = {
    variables: { request_method: method, request_uri: uri, uri, correlation_id: "c-1" },
    headersIn: { Authorization: authorization, Origin: origin },
    headersOut: sortie.headers,
    uri,
    return(code) { sortie.status = code; },
    error(message) { sortie.errors.push(message); },
  };
  return { r, sortie };
}

function jeton_valide(role, sub = "u-1") {
  const maintenant = Math.floor(Date.now() / 1000);
  return token({ claims: { role, sub, iat: maintenant, exp: maintenant + 600 } });
}

test("verify : 204 avec l'identité pour un jeton valide du bon rôle", () => {
  const { verify } = handlers({ JWT_SECRET: KEY, ENVIRONMENT: "local" }, TABLE);
  const { r, sortie } = requete({ authorization: `Bearer ${jeton_valide("viewer", "u-5")}` });
  verify(r);
  assert.equal(sortie.status, 204);
  assert.equal(sortie.headers["X-Auth-User"], "u-5");
  assert.equal(sortie.headers["X-Auth-Role"], "viewer");
});

test("verify : 401 sans jeton ou avec un jeton faux, jamais le détail", () => {
  const { verify } = handlers({ JWT_SECRET: KEY, ENVIRONMENT: "local" }, TABLE);
  for (const authorization of [undefined, "", "Bearer", "Bearer x", `Basic ${jeton_valide("admin")}`, `Bearer ${token({ key: "autre" + KEY })}`]) {
    const { r, sortie } = requete({ authorization });
    verify(r);
    assert.equal(sortie.status, 401, String(authorization).slice(0, 20));
    assert.equal(sortie.headers["X-Auth-User"], undefined);
  }
});

test("verify : 403 quand le rôle ne suffit pas, 204 quand il est égal ou supérieur", () => {
  const { verify } = handlers({ JWT_SECRET: KEY, ENVIRONMENT: "local" }, TABLE);
  const essai = (role, method, uri) => {
    const { r, sortie } = requete({ method, uri, authorization: `Bearer ${jeton_valide(role)}` });
    verify(r);
    return sortie.status;
  };
  assert.equal(essai("viewer", "POST", "/api/v1/alerts/INT_01/resolve"), 403);
  assert.equal(essai("operator", "POST", "/api/v1/alerts/INT_01/resolve"), 204);
  assert.equal(essai("admin", "POST", "/api/v1/alerts/INT_01/resolve"), 204);
  assert.equal(essai("operator", "PATCH", "/api/v1/alert-rules/r1"), 403);
  assert.equal(essai("admin", "PATCH", "/api/v1/alert-rules/r1"), 204);
  assert.equal(essai("viewer", "GET", "/api/v1/alerts"), 204);
});

test("verify : une route publique passe sans jeton, une route inconnue est refusée", () => {
  const { verify } = handlers({ JWT_SECRET: KEY, ENVIRONMENT: "local" }, TABLE);
  const publique = requete({ uri: "/api/v1/health" });
  verify(publique.r);
  assert.equal(publique.sortie.status, 204);
  for (const [method, uri] of [["DELETE", "/api/v1/alerts"], ["GET", "/api/v1/autre"], ["GET", "/api/v1/alerts/x"]]) {
    const inconnue = requete({ method, uri: uri.split("?")[0], authorization: `Bearer ${jeton_valide("admin")}` });
    verify(inconnue.r);
    assert.equal(inconnue.sortie.status, 403, uri);
  }
});

test("verify : la chaîne de requête n'entre pas dans la décision", () => {
  const { verify } = handlers({ JWT_SECRET: KEY, ENVIRONMENT: "local" }, TABLE);
  const { r, sortie } = requete({ uri: "/api/v1/alerts?limit=5", authorization: `Bearer ${jeton_valide("viewer")}` });
  verify(r);
  assert.equal(sortie.status, 204);
});

test("verify : sans clé utilisable, tout est refusé (500, que nginx transforme en 503), sans citer de secret", () => {
  for (const [env, attendu] of [
    [{ ENVIRONMENT: "local" }, "absente"],
    [{ JWT_SECRET: "court", ENVIRONMENT: "local" }, "trop courte"],
    [{ JWT_SECRET: "change-me-local-" + KEY, ENVIRONMENT: "production" }, "exemple"],
  ]) {
    const { verify } = handlers(env, TABLE);
    for (const uri of ["/api/v1/alerts", "/api/v1/health"]) {
      const { r, sortie } = requete({ uri, authorization: `Bearer ${jeton_valide("admin")}` });
      verify(r);
      assert.equal(sortie.status, 500, `${attendu} ${uri}`);
      assert.match(sortie.errors.join(" "), new RegExp(attendu));
      assert.equal(sortie.errors.join(" ").includes(KEY), false);
    }
  }
});

test("preflight : 204 pour une origine de la liste, 403 sinon", () => {
  const { preflight } = handlers({ JWT_SECRET: KEY, CORS_ALLOWED_ORIGINS: "http://localhost:8080" }, TABLE);
  const bonne = requete({ method: "OPTIONS", origin: "http://localhost:8080" });
  preflight(bonne.r);
  assert.equal(bonne.sortie.status, 204);
  for (const origin of ["http://evil.example", undefined, "*"]) {
    const mauvaise = requete({ method: "OPTIONS", origin });
    preflight(mauvaise.r);
    assert.equal(mauvaise.sortie.status, 403, String(origin));
  }
});

test("headers : efface ceux des services avant de poser les siens", () => {
  const { headers: filtre } = handlers({ JWT_SECRET: KEY, CORS_ALLOWED_ORIGINS: "http://localhost:8080" }, TABLE);
  const { r, sortie } = requete({ origin: "http://localhost:8080" });
  Object.assign(sortie.headers, {
    "Access-Control-Allow-Origin": "*", "X-Frame-Options": "SAMEORIGIN", "X-Powered-By": "service", "Referrer-Policy": "origin",
    "Content-Security-Policy": "default-src *", "Strict-Transport-Security": "max-age=1",
  });
  filtre(r);
  assert.equal(sortie.headers["Access-Control-Allow-Origin"], "http://localhost:8080");
  assert.equal(sortie.headers["X-Frame-Options"], "DENY");
  assert.equal(sortie.headers["Referrer-Policy"], "no-referrer");
  assert.equal(sortie.headers["Content-Security-Policy"], "default-src 'none'; frame-ancestors 'none'");
  assert.equal(sortie.headers["X-Powered-By"], undefined);
  assert.equal(sortie.headers["Strict-Transport-Security"], undefined);
  assert.equal(sortie.headers["X-Correlation-ID"], "c-1");
});

// --------------------------------------------------------------------------- cas limites trouvés par mutation
test("un jeton valide, mais d'une taille démesurée, est refusé avant tout calcul", () => {
  const gros = token({ claims: { pad: "x".repeat(5000) } });
  assert.ok(gros.length > 4096);
  assert.equal(auth.decode(gros, KEY, NOW).ok, false);
  assert.equal(auth.decode(token({ claims: { pad: "x".repeat(100) } }), KEY, NOW).ok, true); // sans l'excès, il passe
});

test("un jeton valide suivi d'un quatrième morceau est refusé", () => {
  assert.equal(auth.decode(`${token()}.extra`, KEY, NOW).ok, false);
  assert.equal(auth.decode(`${token()}.`, KEY, NOW).ok, false);
});

test("un corps signé qui n'est pas un objet est refusé sans lever d'exception", () => {
  for (const corps of ["null", "[]", "7", '"texte"', "true"]) {
    const head = b64({ alg: "HS256", typ: "JWT" });
    const body = b64(corps);
    const signature = createHmac("sha256", KEY).update(`${head}.${body}`).digest("base64url");
    assert.doesNotThrow(() => auth.decode(`${head}.${body}.${signature}`, KEY, NOW), corps);
    assert.equal(auth.decode(`${head}.${body}.${signature}`, KEY, NOW).ok, false, corps);
  }
});

test("la signature doit être en base64url : la forme base64 standard (+ / =) est refusée même si elle décode pareil", () => {
  let essais = 0;
  let verifie = false;
  while (!verifie && essais < 200) {
    const [head, body, signature] = token({ claims: { sub: `u-${essais++}` } }).split(".");
    if (!/[-_]/.test(signature)) continue;
    const standard = signature.replace(/-/g, "+").replace(/_/g, "/") + "=";
    assert.equal(auth.decode(`${head}.${body}.${signature}`, KEY, NOW).ok, true);
    assert.equal(auth.decode(`${head}.${body}.${standard}`, KEY, NOW).ok, false);
    verifie = true;
  }
  assert.ok(verifie, "aucune signature avec - ou _ trouvée");
});
