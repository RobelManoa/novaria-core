// Authentification et sécurité transversales de la passerelle d'API (MS-13), en njs (JavaScript de nginx).
//
// Ce que fait ce fichier :
//   1. verify    : valide le jeton JWT (HS256) et le rôle exigé par la route (sous-requête auth_request) ;
//   2. preflight : répond à la pré-vérification CORS (OPTIONS) sans jeton, pour les origines autorisées ;
//   3. headers   : filtre d'en-têtes de TOUTES les réponses : en-têtes de sécurité, CORS, corrélation. Il
//                  efface d'abord ceux des services : la passerelle est l'unique source de ces en-têtes.
//
// Secrets : la clé de signature vient de l'environnement (`JWT_SECRET`, déclaré par `env JWT_SECRET;` dans
// nginx.conf). Elle n'est écrite ni dans ce fichier, ni dans la configuration, ni dans un journal : les messages
// d'erreur ne citent jamais ni la clé, ni le jeton, ni le contenu d'un en-tête.
//
// Même contrat que `services/*/app/core/auth.py` : HS256 fixé (jamais lu dans le jeton), revendications `sub`,
// `role`, `iat`, `exp` obligatoires, expiration contrôlée. Le rôle exigé vient de `routes.json`, généré depuis les
// contrats OpenAPI par `scripts/dev/gateway_routes.py`.
//
// Le fichier tourne sous njs (nginx) et sous Node (tests : `node --test gateway/tests/`) : mêmes modules `fs` et
// `crypto`, mêmes `Buffer` et `process`.

import fs from "fs";
import crypto from "crypto";

const ROLES = { viewer: 0, operator: 1, admin: 2 };
const KEY_MIN_LENGTH = 32;
const PLACEHOLDER = "change-me-local"; // valeur d'exemple de .env.example : tolérée en local seulement
const MAX_TOKEN_LENGTH = 4096;
const IAT_LEEWAY_S = 30; // tolérance d'horloge sur « émis dans le futur »
const ORIGIN = /^https?:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?$/; // schéma://hôte[:port], jamais de chemin ni de joker

const CORS_METHODS = "GET, POST, PATCH, OPTIONS";
const CORS_HEADERS = "Authorization, Content-Type, X-Correlation-ID";
const CORS_EXPOSED = "X-Correlation-ID, Retry-After, Allow, WWW-Authenticate";
const CORS_MAX_AGE = "600";

// En-têtes que la passerelle impose : ce que les services envoient d'équivalent est effacé.
const OWNED = [
  "Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers",
  "Access-Control-Allow-Credentials", "Access-Control-Expose-Headers", "Access-Control-Max-Age",
  "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy",
  "Strict-Transport-Security", "X-Powered-By",
];

function readRoutes(path) {
  const table = JSON.parse(fs.readFileSync(path, "utf8"));
  return table.map((route) => ({ method: route.method, re: new RegExp(route.pattern), role: route.role }));
}

/** Origines autorisées : liste exacte tirée de CORS_ALLOWED_ORIGINS ; une entrée mal formée est ignorée. */
function parseOrigins(text) {
  return (text || "")
    .split(",")
    .map((item) => item.trim())
    .filter((item) => ORIGIN.test(item));
}

function base64url(text) {
  return /^[A-Za-z0-9_-]+$/.test(text) ? Buffer.from(text, "base64url") : null;
}

function sameBytes(a, b) {
  // Comparaison à durée constante : ne dit pas à partir de quel octet la signature diffère.
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Décode et contrôle un jeton. Rend `{ ok: true, subject, role }` ou `{ ok: false }` : jamais la raison au
 * client (un attaquant n'apprend pas ce qui manquait), jamais le jeton nulle part.
 */
function decode(token, key, now) {
  if (typeof token !== "string" || token.length === 0 || token.length > MAX_TOKEN_LENGTH) return { ok: false };
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false };
  const head = parts[0];
  const body = parts[1];
  const signature = parts[2];
  let header, claims;
  try {
    const rawHeader = base64url(head);
    const rawBody = base64url(body);
    if (!rawHeader || !rawBody) return { ok: false };
    header = JSON.parse(rawHeader.toString("utf8"));
    claims = JSON.parse(rawBody.toString("utf8"));
  } catch (error) {
    return { ok: false };
  }
  // L'algorithme est fixé ici : « none », HS384, RS256… sont refusés avant tout calcul.
  if (!header || header.alg !== "HS256") return { ok: false };
  const expected = crypto.createHmac("sha256", key).update(`${head}.${body}`).digest();
  const given = base64url(signature);
  if (!given || !sameBytes(expected, given)) return { ok: false };
  if (!claims || typeof claims !== "object") return { ok: false };
  const sub = claims.sub;
  const role = claims.role;
  const iat = claims.iat;
  const exp = claims.exp;
  if (typeof sub !== "string" || sub.length === 0 || sub.length > 200) return { ok: false };
  if (typeof role !== "string" || !Object.prototype.hasOwnProperty.call(ROLES, role)) return { ok: false };
  if (!Number.isFinite(iat) || !Number.isFinite(exp)) return { ok: false };
  if (exp <= now) return { ok: false }; // expiré
  if (iat > now + IAT_LEEWAY_S) return { ok: false }; // émis dans le futur
  return { ok: true, subject: sub, role };
}

/** La clé est-elle utilisable ? Sinon la passerelle refuse tout (503) plutôt que de laisser passer. */
function keyProblem(key, environment) {
  if (typeof key !== "string" || key.length < KEY_MIN_LENGTH) return "absente ou trop courte";
  if (environment !== "local" && key.includes(PLACEHOLDER)) return "valeur d'exemple hors local";
  return null;
}

/** Le rôle exigé pour (méthode, chemin), `null` pour une route publique, `undefined` si la route est inconnue. */
function requiredRole(routes, method, path) {
  const route = routes.find((item) => item.method === method && item.re.test(path));
  return route ? route.role : undefined;
}

/** Origine autorisée à lire la réponse : la valeur exacte de `Origin` si elle est dans la liste, sinon null. */
function allowedOrigin(origins, origin) {
  return origin && origins.includes(origin) ? origin : null;
}

/** Les en-têtes que la passerelle pose sur une réponse ; `null` efface. Pure : testée sans nginx. */
function responseHeaders(options) {
  const origins = options.origins;
  const origin = options.origin;
  const method = options.method;
  const path = options.path;
  const headers = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Correlation-ID": options.correlationId,
  };
  if (path === "/api/v1/auth/login" || path.startsWith("/api/v1/auth/") || path === "/api/v1/events/stream") {
    headers["Cache-Control"] = "no-store"; // ni jeton ni identité ni flux dans un cache
  }
  if (options.forwardedProto === "https") {
    // Le point qui termine TLS parle HTTPS ; en local il n'y a pas de TLS et l'en-tête n'aurait aucun effet.
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains";
  }
  const allowed = allowedOrigin(origins, origin);
  if (origins.length > 0) headers["Vary"] = "Origin";
  if (allowed) {
    headers["Access-Control-Allow-Origin"] = allowed;
    headers["Access-Control-Expose-Headers"] = CORS_EXPOSED;
    // Jamais de cookie : Access-Control-Allow-Credentials n'est pas envoyé.
    if (method === "OPTIONS") {
      headers["Access-Control-Allow-Methods"] = CORS_METHODS;
      headers["Access-Control-Allow-Headers"] = CORS_HEADERS;
      headers["Access-Control-Max-Age"] = CORS_MAX_AGE;
    }
  }
  return headers;
}

/** Le jeton d'un en-tête `Authorization: Bearer <jeton>` ; null si l'en-tête est absent ou d'un autre schéma. */
function bearerToken(header) {
  if (typeof header !== "string") return null;
  const match = /^Bearer +([^ ]+)$/i.exec(header.trim());
  return match ? match[1] : null;
}

// ------------------------------------------------------------------------------ branchement sur nginx
function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function createHandlers(environment, routesPath) {
  const key = environment.JWT_SECRET;
  const problem = keyProblem(key, environment.ENVIRONMENT || "local");
  const origins = parseOrigins(environment.CORS_ALLOWED_ORIGINS);
  const routes = readRoutes(routesPath);

  // Sous-requête `auth_request` : 204 = accès accordé ; 401, 403 sont rendus tels quels par nginx ; toute autre
  // valeur est une erreur interne (500) que la configuration transforme en 503.
  function verify(r) {
    if (problem) {
      r.error(`authentification indisponible : clé ${problem}`);
      r.return(500);
      return;
    }
    const method = r.variables.request_method;
    const path = r.variables.request_uri.split("?")[0]; // le chemin brut : nginx a vérifié qu'il est « simple »
    const role = requiredRole(routes, method, path);
    if (role === undefined) {
      // Une route qui n'est pas dans la table ne devrait jamais arriver ici (aucun `location` ne l'envoie).
      r.return(403);
      return;
    }
    if (role === null) {
      r.return(204);
      return;
    }
    const token = bearerToken(r.headersIn["Authorization"]);
    const result = token ? decode(token, key, nowSeconds()) : { ok: false };
    if (!result.ok) {
      r.return(401);
      return;
    }
    if (ROLES[result.role] < ROLES[role]) {
      r.return(403);
      return;
    }
    r.headersOut["X-Auth-User"] = result.subject;
    r.headersOut["X-Auth-Role"] = result.role;
    r.return(204);
  }

  // Pré-vérification CORS : sans jeton, mais seulement pour une origine de la liste.
  function preflight(r) {
    const origin = r.headersIn["Origin"];
    r.return(allowedOrigin(origins, origin) ? 204 : 403);
  }

  // Filtre d'en-têtes : efface ceux des services, pose les nôtres.
  function headers(r) {
    OWNED.forEach((name) => {
      delete r.headersOut[name];
    });
    const wanted = responseHeaders({
      origins,
      origin: r.headersIn["Origin"],
      method: r.variables.request_method,
      path: r.variables.request_uri.split("?")[0],
      correlationId: r.variables.correlation_id,
      forwardedProto: r.headersIn["X-Forwarded-Proto"],
    });
    Object.keys(wanted).forEach((name) => {
      r.headersOut[name] = wanted[name];
    });
  }

  return { verify, preflight, headers };
}

// njs n'accepte qu'un export par défaut : toutes les fonctions y sont, nginx n'utilise que verify, preflight et headers ;
// les autres sont là pour les tests (node --test gateway/tests/).
// Sous nginx (l'objet global `ngx` existe) : les trois gestionnaires sont branchés sur l'environnement. Sous Node : rien.
const handlers = typeof ngx === "undefined" ? {} : createHandlers(process.env, "/etc/nginx/gateway/routes.json");

export default {
  verify: handlers.verify,
  preflight: handlers.preflight,
  headers: handlers.headers,
  createHandlers, decode, keyProblem, requiredRole, allowedOrigin, responseHeaders, bearerToken, parseOrigins,
};
