// Audit d'accessibilité de l'application (FE-07, EXG-NFR-15) dans un vrai navigateur.
//
//   npm run build && npm run a11y:audit            écrit audit/resultats.json et audit/rapport-accessibilite.md
//   npm run a11y:audit -- --check                  idem, et échoue s'il reste une erreur bloquante
//
// Outil : axe-core (règles WCAG 2.0, 2.1 et 2.2 niveaux A et AA, plus les bonnes pratiques) exécuté dans Edge
// ou Chrome piloté par playwright-core. Le navigateur calcule les vraies couleurs, tailles et positions : les
// contrastes sont donc vérifiés sur le rendu réel, ce que jsdom ne sait pas faire. L'API est simulée par le
// script (aucun service n'est nécessaire) ; les pages protégées s'ouvrent avec une session factice.
//
// Un défaut est « bloquant » dès qu'axe le range sous une étiquette WCAG A ou AA, quelle que soit sa gravité.
// Les bonnes pratiques d'axe (hors WCAG) sont rapportées comme avertissements. Le script vérifie aussi, par
// des scénarios clavier, ce qu'un outil automatique ne voit pas : lien d'évitement, ordre de tabulation,
// indicateur de focus visible, tiroir mobile (focus piégé, Échap), reflux à 320 px de large (WCAG 1.4.10).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { findEnglish } from "./audit-francais.mjs";

const require = createRequire(import.meta.url);
const axeSource = await readFile(require.resolve("axe-core/axe.min.js"), "utf8");
const axeVersion = JSON.parse(
  await readFile(require.resolve("axe-core/package.json"), "utf8"),
).version;

const ROOT = new URL("../", import.meta.url);
const OUT = new URL("audit/", ROOT);
const CHECK = process.argv.includes("--check");

const BROWSERS = [
  process.env.BROWSER_PATH,
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/usr/bin/microsoft-edge",
].filter(Boolean);

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const isWcag = (tags) => tags.some((tag) => /^wcag\d+a{1,2}$/.test(tag));

// ---------------------------------------------------------------------------------------------------------
// Données simulées (formes du contrat OpenAPI)
// ---------------------------------------------------------------------------------------------------------

const fixture = JSON.parse(
  await readFile(new URL("tests/fixtures/dashboard-api.json", ROOT), "utf8"),
);
const network = fixture.scenarios.find((s) => s.name === "reseau-1h-5min");
const PROVENANCE = { source_type: "SIMULATED", run_id: "run-demo", scenario_id: "demo", seed: 7 };
const USER = {
  user_id: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11",
  username: "operateur1",
  role: "operator",
  is_active: true,
  created_at: "2026-10-20T08:00:00Z",
};

function alert(n, state, severity, kind) {
  return {
    alert_id: `3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d${String(n).padStart(2, "0")}`,
    rule_id: "congestion.persistante",
    kind,
    state,
    severity,
    cause: "UNKNOWN",
    road_segment_id: `ROAD_00${n}`,
    intersection_id: "INT_01",
    episode_id: null,
    opened_at: `2026-10-30T08:0${n}:00Z`,
    notified_at: null,
    acknowledged_at: null,
    acknowledged_by: null,
    resolved_at: state === "RESOLVED" ? "2026-10-30T09:00:00Z" : null,
    resolution: state === "RESOLVED" ? "AUTO" : null,
    provenance: PROVENANCE,
  };
}
const ALERTS = [
  alert(1, "CREATED", "WARNING", "CONGESTION"),
  alert(2, "NOTIFIED", "CRITICAL", "TRAFFIC_ANOMALY"),
  alert(3, "ACKNOWLEDGED", "INFO", "SENSOR_FAULT"),
  alert(4, "RESOLVED", "WARNING", "CONGESTION"),
];

const ISSUED = "2026-10-30T08:55:00Z";
function forecast(segment, horizon, ratio, state) {
  return {
    road_segment_id: segment,
    issued_at: ISSUED,
    horizon_min: horizon,
    target_time: new Date(Date.parse(ISSUED) + horizon * 60_000)
      .toISOString()
      .replace(".000Z", "Z"),
    predicted_speed_ratio: ratio,
    predicted_state: state,
    model: { kind: "REFERENCE", name: "persistance", version: "v0", run_id: null },
    provenance: PROVENANCE,
  };
}

const REPORTS = [0, 1, 2].map((i) => ({
  report_id: `3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d0${i}`,
  title: `Rapport de supervision du ${20 - i}/10/2026`,
  period_start: `2026-10-${20 - i}T00:00:00Z`,
  period_end: `2026-10-${20 - i}T23:59:59Z`,
  generated_at: `2026-10-${20 - i}T23:30:00Z`,
  file_name: `rapport-2026-10-${20 - i}.pdf`,
  size_bytes: 123_456,
  content_type: "application/pdf",
  sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
}));

const problem = (status, code) => ({
  status,
  contentType: "application/problem+json",
  body: JSON.stringify({
    type: "about:blank",
    title: "Erreur",
    status,
    code,
    correlation_id: "corr-audit",
  }),
});
const ok = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

/** Réponses simulées ; `mode` choisit un cas d'échec pour les scénarios d'erreur. */
function api(mode) {
  return async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v1/health")
      return route.fulfill(
        ok({ status: "ok", version: "0.1.0", revision: "audit", environment: "audit" }),
      );
    if (path === "/api/v1/auth/me") return route.fulfill(ok(USER));
    if (path === "/api/v1/auth/login") {
      return route.fulfill(
        mode === "login-refuse"
          ? problem(401, "INVALID_CREDENTIALS")
          : ok({ access_token: "jeton-audit", token_type: "bearer", expires_in: 1800 }),
      );
    }
    if (path === "/api/v1/indicators") {
      if (mode === "indicateurs-503") return route.fulfill(problem(503, "UPSTREAM_UNAVAILABLE"));
      const first = url.searchParams.get("limit") === "1";
      return route.fulfill(ok(network.requests[first ? 0 : 1].response));
    }
    if (path === "/api/v1/alerts") return route.fulfill(ok({ items: ALERTS, next_cursor: null }));
    if (path === "/api/v1/events/stream") {
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: ": audit\n\n" });
    }
    if (path === "/api/v1/forecasts") {
      if (mode === "previsions-404") return route.fulfill(problem(404, "NOT_FOUND"));
      const horizon = Number(url.searchParams.get("horizon_min") ?? 15);
      const segments = url.searchParams.getAll("road_segment_id");
      const wanted = segments.length ? segments : ["ROAD_001", "ROAD_002"];
      return route.fulfill(
        ok({
          items: wanted.map((s, i) =>
            forecast(s, horizon, i ? 0.32 : 0.74, i ? "CONGESTED" : "FREE_FLOW"),
          ),
        }),
      );
    }
    if (path === "/api/v1/reports") return route.fulfill(ok({ items: REPORTS, next_cursor: null }));
    return route.fulfill(problem(404, "NOT_FOUND"));
  };
}

// ---------------------------------------------------------------------------------------------------------
// Scénarios
// ---------------------------------------------------------------------------------------------------------

const DESKTOP = { width: 1280, height: 800 };
const MOBILE = { width: 375, height: 700 };
const NARROW = { width: 320, height: 640 };

const PAGES = [
  { id: "connexion", path: "/connexion", signedIn: false, ready: "form" },
  { id: "tableau-de-bord", path: "/", ready: "table" },
  { id: "alertes", path: "/alertes", ready: "table" },
  { id: "feux", path: "/feux", ready: "main h1" },
  { id: "previsions", path: "/previsions", ready: "main h1 ~ *" },
  { id: "rapports", path: "/rapports", ready: "table" },
  { id: "page-introuvable", path: "/inexistant", ready: "main h1" },
];

const scenarios = [];
for (const page of PAGES) {
  for (const theme of ["light", "dark"]) {
    for (const [sizeName, viewport] of [
      ["ordinateur", DESKTOP],
      ["mobile", MOBILE],
    ]) {
      scenarios.push({
        ...page,
        name: `${page.id} · ${theme === "light" ? "clair" : "sombre"} · ${sizeName}`,
        theme,
        viewport,
      });
    }
  }
  scenarios.push({
    ...page,
    name: `${page.id} · clair · 320 px (reflux)`,
    theme: "light",
    viewport: NARROW,
    reflow: true,
  });
}
scenarios.push(
  {
    id: "connexion",
    path: "/connexion",
    signedIn: false,
    ready: "form",
    theme: "light",
    viewport: DESKTOP,
    mode: "login-refuse",
    name: "connexion · identifiants refusés · clair · ordinateur",
    action: "login",
  },
  {
    id: "connexion",
    path: "/connexion",
    signedIn: false,
    ready: "form",
    theme: "dark",
    viewport: MOBILE,
    mode: "login-refuse",
    name: "connexion · identifiants refusés · sombre · mobile",
    action: "login",
  },
  {
    id: "tableau-de-bord",
    path: "/",
    ready: "[role=alert]",
    theme: "light",
    viewport: DESKTOP,
    mode: "indicateurs-503",
    name: "tableau-de-bord · erreur du serveur · clair · ordinateur",
  },
  {
    id: "tableau-de-bord",
    path: "/",
    ready: "[role=alert]",
    theme: "dark",
    viewport: DESKTOP,
    mode: "indicateurs-503",
    name: "tableau-de-bord · erreur du serveur · sombre · ordinateur",
  },
  {
    id: "previsions",
    path: "/previsions",
    ready: "[role=alert]",
    theme: "light",
    viewport: DESKTOP,
    mode: "previsions-404",
    name: "previsions · service absent · clair · ordinateur",
  },
  {
    id: "alertes",
    path: "/alertes",
    ready: "table",
    theme: "light",
    viewport: DESKTOP,
    name: "alertes · toutes les alertes · clair · ordinateur",
    action: "alertes-toutes",
  },
  {
    id: "alertes",
    path: "/alertes",
    ready: "table",
    theme: "dark",
    viewport: DESKTOP,
    name: "alertes · toutes les alertes · sombre · ordinateur",
    action: "alertes-toutes",
  },
  {
    id: "tiroir",
    path: "/",
    ready: "table",
    theme: "light",
    viewport: MOBILE,
    name: "tiroir de navigation ouvert · clair · mobile",
    action: "tiroir",
  },
  {
    id: "tiroir",
    path: "/",
    ready: "table",
    theme: "dark",
    viewport: MOBILE,
    name: "tiroir de navigation ouvert · sombre · mobile",
    action: "tiroir",
  },
);

// ---------------------------------------------------------------------------------------------------------
// Exécution
// ---------------------------------------------------------------------------------------------------------

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function startPreview() {
  if (!existsSync(new URL("dist/index.html", ROOT)))
    throw new Error("dist/ absent : lancer `npm run build` d'abord");
  const port = await freePort();
  const viteBin = fileURLToPath(new URL("node_modules/vite/bin/vite.js", ROOT));
  const child = spawn(
    process.execPath,
    [viteBin, "preview", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      cwd: fileURLToPath(ROOT),
      stdio: "ignore",
    },
  );
  const base = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      if ((await fetch(base)).ok) return { base, stop: () => child.kill() };
    } catch {
      /* le serveur démarre */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  child.kill();
  throw new Error("vite preview n'a pas démarré");
}

/** Retire de la liste les doublons d'une même règle sur un même élément (même sélecteur). */
const nodesOf = (violation) =>
  violation.nodes.map((node) => ({
    target: node.target.join(" "),
    summary: node.failureSummary?.replace(/\s+/g, " ").trim() ?? "",
    html: node.html.slice(0, 220),
  }));

async function openPage(browser, base, scenario) {
  const context = await browser.newContext({
    viewport: scenario.viewport,
    colorScheme: scenario.theme === "dark" ? "dark" : "light",
    locale: "fr-FR",
    reducedMotion: scenario.motion ?? "reduce",
  });
  await context.addInitScript(
    ([theme, signedIn]) => {
      try {
        localStorage.setItem("novaria-theme", theme);
        if (signedIn)
          sessionStorage.setItem(
            "novaria-session",
            JSON.stringify({ token: "jeton-audit", expiresAt: Date.now() + 3_600_000 }),
          );
      } catch {
        /* stockage indisponible */
      }
    },
    [scenario.theme, scenario.signedIn !== false],
  );
  await context.route("**/api/v1/**", api(scenario.mode));
  const page = await context.newPage();
  await page.goto(base + scenario.path, { waitUntil: "load" });
  await page.waitForSelector(scenario.ready, { state: "attached", timeout: 15_000 });
  // Laisse les requêtes et les polices se terminer, puis fige l'écran avant la mesure.
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(400);
  return { context, page };
}

async function applyAction(page, scenario) {
  if (scenario.action === "login") {
    await page.fill('input[name="username"]', "inconnu");
    await page.fill('input[name="password"]', "mauvais-mot-de-passe");
    await page.click('button[type="submit"]');
    await page.waitForSelector("[role=alert]");
  } else if (scenario.action === "alertes-toutes") {
    await page.selectOption("select", "all");
  } else if (scenario.action === "tiroir") {
    await page.click('button[aria-label="Ouvrir le menu"]');
    await page.waitForTimeout(400);
  }
}

async function runAxe(page) {
  await page.evaluate(axeSource);
  return page.evaluate(async (tags) => {
    return axe.run(document, {
      runOnly: { type: "tag", values: tags },
      resultTypes: ["violations", "incomplete"],
    });
  }, TAGS);
}

/**
 * axe ne sait pas conclure sur le texte d'un SVG (règle « à vérifier ») : on mesure ici le contraste de chaque
 * texte de graphique, couleur de remplissage calculée contre le fond réel du premier ancêtre opaque (WCAG 1.4.3).
 */
async function svgTextContrast(page) {
  return page.evaluate(() => {
    const parse = (value) => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const [r, g, b, a = 1] = m[1]
        .split(/[ ,/]+/)
        .filter(Boolean)
        .map(Number);
      return { r, g, b, a };
    };
    const lum = ({ r, g, b }) => {
      const f = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const failures = [];
    let checked = 0;
    for (const text of document.querySelectorAll("svg text")) {
      const fill = parse(getComputedStyle(text).fill);
      let node = text.closest("svg").parentElement;
      let back = null;
      while (node && !back) {
        const color = parse(getComputedStyle(node).backgroundColor);
        if (color && color.a === 1) back = color;
        node = node.parentElement;
      }
      if (!fill || !back) continue;
      checked += 1;
      const [hi, lo] = [lum(fill), lum(back)].sort((a, b) => b - a);
      const ratio = (hi + 0.05) / (lo + 0.05);
      if (ratio < 4.5)
        failures.push({ text: text.textContent, ratio: Math.round(ratio * 100) / 100 });
    }
    return { checked, failures };
  });
}

async function visibleTexts(page) {
  return page.evaluate(() => {
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent.replace(/\s+/g, " ").trim();
      const parent = node.parentElement;
      if (text && parent && !["SCRIPT", "STYLE"].includes(parent.tagName)) out.push(text);
    }
    for (const element of document.querySelectorAll(
      "[aria-label],[title],[placeholder],img[alt]",
    )) {
      for (const name of ["aria-label", "title", "placeholder", "alt"]) {
        const value = element.getAttribute(name);
        if (value) out.push(value);
      }
    }
    out.push(`lang=${document.documentElement.lang}`, `titre=${document.title}`);
    return out;
  });
}

async function measure(browser, base, scenario) {
  const { context, page } = await openPage(browser, base, scenario);
  try {
    await applyAction(page, scenario);
    const results = await runAxe(page);
    const texts = await visibleTexts(page);
    const svg = await svgTextContrast(page);
    const info = await page.evaluate(() => ({
      lang: document.documentElement.lang,
      title: document.title,
      h1: document.querySelectorAll("h1").length,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
    }));
    const svgViolations = svg.failures.length
      ? [
          {
            id: "svg-text-contrast",
            impact: "serious",
            help: "Le texte d'un graphique doit avoir un contraste d'au moins 4,5:1 (mesure propre à l'audit)",
            helpUrl: "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html",
            tags: ["wcag2aa", "wcag143"],
            wcag: true,
            nodes: svg.failures.map((f) => ({
              target: `svg text « ${f.text} »`,
              summary: `contraste ${f.ratio}:1`,
              html: "",
            })),
          },
        ]
      : [];
    return {
      name: scenario.name,
      svgTextsChecked: svg.checked,
      violations: [
        ...svgViolations,
        ...results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          help: v.help,
          helpUrl: v.helpUrl,
          tags: v.tags,
          wcag: isWcag(v.tags),
          nodes: nodesOf(v),
        })),
      ],
      incomplete: results.incomplete.map((v) => ({
        id: v.id,
        help: v.help,
        count: v.nodes.length,
        targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
        // Éléments qui ne sont pas un texte de SVG : ceux-là, rien ne les mesure à part axe.
        outsideSvgText: v.nodes.filter((n) => !n.html.startsWith("<text")).length,
      })),
      passes: results.passes?.length ?? null,
      english: findEnglish(texts),
      info,
      textCount: texts.length,
    };
  } finally {
    await context.close();
  }
}

// --- Scénarios clavier -------------------------------------------------------------------------------------

/** Description du focus : nom accessible, balise, et visibilité d'un indicateur (contour ou ombre). */
const focusProbe = () => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const style = getComputedStyle(el);
  const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2;
  const shadow = style.boxShadow !== "none";
  const label =
    el.getAttribute("aria-label") ?? el.labels?.[0]?.textContent ?? el.textContent ?? "";
  const rect = el.getBoundingClientRect();
  return {
    tag: el.tagName.toLowerCase(),
    name: label.replace(/\s+/g, " ").trim(),
    visibleIndicator: outline || shadow,
    onScreen:
      rect.width > 0 &&
      rect.height > 0 &&
      rect.bottom > 0 &&
      rect.right > 0 &&
      rect.top < innerHeight &&
      rect.left < innerWidth,
    id: el.id || null,
  };
};

async function keyboardChecks(browser, base, motion) {
  const checks = [];
  // Le mouvement réduit change le comportement (transitions coupées) : lien d'évitement et tiroir sont mesurés dans les deux cas.
  const tag = motion === "reduce" ? " [mouvement réduit]" : "";
  const add = (name, passed, detail = "") => checks.push({ name: name + tag, passed, detail });
  // Un scénario qui ne peut pas s'exécuter (élément introuvable, délai dépassé) est un échec rapporté, pas un arrêt de l'audit.
  const guarded = async (name, task) => {
    try {
      await task();
    } catch (error) {
      add(
        `${name} : le scénario n'a pas pu s'exécuter`,
        false,
        String(error.message).split(/\r?\n/)[0],
      );
    }
  };

  for (const [label, viewport] of [
    ["ordinateur", DESKTOP],
    ["mobile", MOBILE],
  ]) {
    // 1. Lien d'évitement et ordre de tabulation sur le tableau de bord
    await guarded("lien d'évitement et tabulation", async () => {
      const { context, page } = await openPage(browser, base, {
        path: "/",
        ready: "table",
        theme: "light",
        viewport,
        motion,
      });
      await page.keyboard.press("Tab");
      const first = await page.evaluate(focusProbe);
      add(
        `${label} : le premier Tab atteint le lien « Aller au contenu »`,
        first?.name === "Aller au contenu" && first.onScreen,
        JSON.stringify(first),
      );
      await page.keyboard.press("Enter");
      const target = await page.evaluate(() => document.activeElement?.id ?? null);
      add(
        `${label} : Entrée sur le lien d'évitement place le focus sur le contenu principal`,
        target === "contenu",
        `focus sur « ${target} »`,
      );

      // Parcours de toute la page : chaque arrêt a un nom, un indicateur visible, et reste à l'écran.
      await page.goto(base + "/", { waitUntil: "load" });
      await page.waitForSelector("table", { state: "attached" });
      const stops = [];
      for (let i = 0; i < 80; i += 1) {
        await page.keyboard.press("Tab");
        const stop = await page.evaluate(focusProbe);
        if (!stop) break;
        if (
          stops.length &&
          stops[0].id &&
          stop.id === stops[0].id &&
          stop.name === stops[0].name &&
          i > 3
        )
          break;
        stops.push(stop);
      }
      const unnamed = stops.filter((s) => !s.name);
      const noRing = stops.filter((s) => !s.visibleIndicator);
      const hidden = stops.filter((s) => !s.onScreen);
      add(
        `${label} : ${stops.length} arrêts de tabulation sur le tableau de bord, tous nommés`,
        stops.length > 5 && unnamed.length === 0,
        unnamed.length
          ? JSON.stringify(unnamed)
          : stops
              .map((s) => s.name || s.tag)
              .join(" → ")
              .slice(0, 400),
      );
      add(
        `${label} : chaque arrêt de tabulation a un indicateur de focus visible`,
        noRing.length === 0,
        noRing.length ? JSON.stringify(noRing) : "",
      );
      add(
        `${label} : aucun arrêt de tabulation n'est hors de l'écran`,
        hidden.length === 0,
        hidden.length ? JSON.stringify(hidden) : "",
      );
      await context.close();
    });
  }

  // 2. Tiroir mobile : ouverture, focus piégé, Échap, retour du focus
  await guarded("tiroir de navigation", async () => {
    const { context, page } = await openPage(browser, base, {
      path: "/",
      ready: "table",
      theme: "light",
      viewport: MOBILE,
      motion,
    });
    const button = page.locator('button[aria-label="Ouvrir le menu"]');
    await button.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    const inDrawer = await page.evaluate(
      () => document.activeElement?.closest("nav")?.getAttribute("aria-label") ?? null,
    );
    add(
      "mobile : ouvrir le menu au clavier place le focus dans la navigation",
      inDrawer === "Navigation principale",
      `focus dans « ${inDrawer} »`,
    );
    const escaped = [];
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press("Tab");
      escaped.push(await page.evaluate(() => document.activeElement?.closest("nav") !== null));
    }
    add("mobile : douze Tab de suite restent dans le tiroir (focus piégé)", escaped.every(Boolean));
    const backwards = [];
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press("Shift+Tab");
      backwards.push(await page.evaluate(() => document.activeElement?.closest("nav") !== null));
    }
    add("mobile : douze Maj+Tab de suite restent dans le tiroir", backwards.every(Boolean));
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const back = await page.evaluate(
      () => document.activeElement?.getAttribute("aria-label") ?? null,
    );
    add(
      "mobile : Échap ferme le tiroir et rend le focus au bouton de menu",
      back === "Ouvrir le menu",
      `focus sur « ${back} »`,
    );
    const hiddenNav = await page.evaluate(
      () => document.querySelector("nav")?.hasAttribute("inert") ?? false,
    );
    add("mobile : le tiroir fermé n'est plus atteignable (inert)", hiddenNav);
    await context.close();
  });

  if (motion === "reduce") return checks;

  // 3. Changement de page : le focus va sur le titre et le titre du document change
  await guarded("changement de page", async () => {
    const { context, page } = await openPage(browser, base, {
      path: "/",
      ready: "table",
      theme: "light",
      viewport: DESKTOP,
    });
    await page.click('nav a[href="/alertes"]');
    await page.waitForSelector("main h1");
    const focused = await page.evaluate(() => ({
      tag: document.activeElement?.tagName,
      text: document.activeElement?.textContent,
      title: document.title,
    }));
    add(
      "ordinateur : après un changement de page, le focus est sur le titre (h1) de la nouvelle page",
      focused.tag === "H1" && focused.text === "Alertes",
      JSON.stringify(focused),
    );
    add(
      "ordinateur : le titre du document change avec la page",
      focused.title === "Alertes · Novaria Core",
      focused.title,
    );
    await context.close();
  });

  // 4. Formulaire de connexion : champ libellé, Entrée envoie, erreur annoncée
  await guarded("formulaire de connexion", async () => {
    const { context, page } = await openPage(browser, base, {
      path: "/connexion",
      signedIn: false,
      ready: "form",
      theme: "light",
      viewport: DESKTOP,
      mode: "login-refuse",
    });
    await page.getByLabel("Identifiant").fill("inconnu");
    await page.getByLabel("Mot de passe").fill("mauvais-mot-de-passe");
    await page.keyboard.press("Enter");
    await page.waitForSelector("[role=alert]");
    const message = await page.locator("[role=alert]").innerText();
    add(
      "ordinateur : le formulaire de connexion s'envoie avec Entrée et l'erreur est annoncée (role=alert, en français)",
      message === "Identifiant ou mot de passe incorrect.",
      message,
    );
    await context.close();
  });

  // 5. Texte agrandi : 200 % de taille de police sans perte de contenu (WCAG 1.4.4)
  await guarded("texte agrandi", async () => {
    const { context, page } = await openPage(browser, base, {
      path: "/alertes",
      ready: "table",
      theme: "light",
      viewport: { width: 1280, height: 800 },
    });
    await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    add(
      "ordinateur : texte à 200 % sans défilement horizontal de la page (1.4.4)",
      overflow <= 1,
      `débordement de ${overflow} px`,
    );
    await context.close();
  });
  return checks;
}

// ---------------------------------------------------------------------------------------------------------

function markdown(report) {
  const lines = [];
  const blocking = report.scenarios.flatMap((s) =>
    s.violations.filter((v) => v.wcag).map((v) => ({ ...v, scenario: s.name })),
  );
  const advice = report.scenarios.flatMap((s) =>
    s.violations.filter((v) => !v.wcag).map((v) => ({ ...v, scenario: s.name })),
  );
  const keyFailures = report.keyboard.filter((c) => !c.passed);
  const english = report.scenarios.flatMap((s) =>
    s.english.map((e) => ({ ...e, scenario: s.name })),
  );
  const reflow = report.scenarios.filter((s) => s.name.includes("reflux"));
  const svgTexts = report.scenarios.reduce((total, s) => total + (s.svgTextsChecked ?? 0), 0);
  const HANDLED = {
    "color-contrast": `texte des graphiques SVG, que axe ne sait pas mesurer : contraste calculé par le script sur chacun (${svgTexts} textes mesurés sur l'ensemble des écrans, seuil 4,5:1)`,
    "skip-link":
      "lien d'évitement masqué jusqu'au focus : couvert par les scénarios clavier (visible au premier Tab, mène au contenu)",
  };
  // Un « à vérifier » que le script ne sait pas traiter (règle inconnue) empêche de conclure : il faut le regarder à la main.
  const unhandled = report.scenarios
    .flatMap((s) => s.incomplete)
    .filter((i) => !(i.id in HANDLED) || (i.id === "color-contrast" && i.outsideSvgText > 0))
    .map((i) => i.id);
  const verdict =
    blocking.length === 0 &&
    keyFailures.length === 0 &&
    english.length === 0 &&
    unhandled.length === 0 &&
    reflow.every((s) => s.info.overflow <= 1);

  lines.push("# Rapport d'audit d'accessibilité (FE-07, EXG-NFR-15)", "");
  lines.push(
    `**Verdict : ${verdict ? "aucune erreur bloquante" : "il reste des erreurs bloquantes"}.**`,
    "",
  );
  lines.push(
    `Généré par \`frontend/scripts/audit-a11y.mjs\` le ${report.date}. Ce fichier est écrasé à chaque exécution : ne pas le modifier à la main.`,
    "",
  );
  lines.push("## Méthode", "");
  lines.push(
    `- Outil : **axe-core ${report.axeVersion}**, règles WCAG 2.0, 2.1 et 2.2 de niveaux A et AA, plus les bonnes pratiques d'axe.`,
  );
  lines.push(
    `- Navigateur : ${report.browser}, piloté par playwright-core ${report.playwright}. Le contraste est mesuré sur le rendu réel (couleurs calculées, fond réel), pas sur la feuille de style.`,
  );
  lines.push(
    "- Application : version construite (`npm run build`) servie par `vite preview` ; API simulée par le script (aucun service lancé), session factice pour les pages protégées.",
  );
  lines.push(
    `- Étendue : ${report.scenarios.length} écrans mesurés = 7 pages × thèmes clair et sombre × ordinateur (1280 px) et mobile (375 px), la largeur de 320 px (reflux), les états d'erreur, les identifiants refusés, le filtre « toutes les alertes » et le tiroir de navigation ouvert.`,
  );
  lines.push(
    "- Critère : **bloquant** = toute violation rangée par axe sous une étiquette WCAG A ou AA, quelle que soit sa gravité. Les bonnes pratiques hors WCAG sont des avertissements. Les contrôles manuels dont axe ne sait pas conclure (« à vérifier ») sont listés plus bas.",
    "",
  );

  lines.push("## Résultat", "");
  lines.push("| Contrôle | Résultat |", "|---|---|");
  lines.push(
    `| Violations WCAG A/AA (axe-core) | **${blocking.length}** sur ${report.scenarios.length} écrans |`,
  );
  lines.push(`| Bonnes pratiques d'axe (avertissements) | ${advice.length} |`);
  lines.push(
    `| Scénarios clavier | ${report.keyboard.length - keyFailures.length} réussis sur ${report.keyboard.length} |`,
  );
  lines.push(`| Textes en anglais repérés | ${english.length} |`);
  lines.push(
    `| Défilement horizontal à 320 px (WCAG 1.4.10) | ${reflow.filter((s) => s.info.overflow > 1).length} page(s) sur ${reflow.length} |`,
    "",
  );

  if (blocking.length) {
    lines.push("## Erreurs bloquantes", "");
    for (const v of blocking)
      lines.push(
        `- **${v.id}** (${v.impact}) — ${v.help} — écran « ${v.scenario} » — ${v.nodes.map((n) => `\`${n.target}\``).join(", ")}`,
      );
    lines.push("");
  }
  if (advice.length) {
    lines.push("## Avertissements (bonnes pratiques hors WCAG)", "");
    for (const v of advice)
      lines.push(
        `- **${v.id}** (${v.impact}) — ${v.help} — écran « ${v.scenario} » — ${v.nodes.map((n) => `\`${n.target}\``).join(", ")}`,
      );
    lines.push("");
  }

  lines.push("## Scénarios clavier", "", "| Scénario | Résultat | Détail |", "|---|---|---|");
  for (const c of report.keyboard)
    lines.push(
      `| ${c.name} | ${c.passed ? "réussi" : "**ÉCHEC**"} | ${c.detail ? c.detail.replace(/\|/g, "\\|").slice(0, 300) : ""} |`,
    );
  lines.push("");

  lines.push(
    "## Écrans mesurés",
    "",
    "| Écran | Violations WCAG | Avertissements | Défilement horizontal | `lang` | Titre |",
    "|---|---|---|---|---|---|",
  );
  for (const s of report.scenarios) {
    const w = s.violations.filter((v) => v.wcag).length;
    lines.push(
      `| ${s.name} | ${w} | ${s.violations.length - w} | ${s.info.overflow > 1 ? `${s.info.overflow} px` : "aucun"} | ${s.info.lang} | ${s.info.title.replace(/\|/g, "\\|")} |`,
    );
  }
  lines.push("");

  const pending = new Map();
  for (const s of report.scenarios)
    for (const i of s.incomplete)
      pending.set(i.id, {
        help: i.help,
        count: (pending.get(i.id)?.count ?? 0) + i.count,
        screens: (pending.get(i.id)?.screens ?? 0) + 1,
      });
  lines.push("## Contrôles que l'outil ne sait pas conclure (« à vérifier »)", "");
  if (pending.size === 0) lines.push("Aucun.", "");
  else {
    lines.push("| Règle | Éléments (cumul) | Écrans | Traitement |", "|---|---|---|---|");
    for (const [id, p] of pending)
      lines.push(
        `| ${id} — ${p.help} | ${p.count} | ${p.screens} | ${HANDLED[id] ?? "**non traité : à vérifier à la main**"} |`,
      );
    lines.push("");
  }
  lines.push("## Limites", "");
  lines.push(
    "- Un outil automatique ne détecte qu'une partie des défauts d'accessibilité (de l'ordre de 30 à 40 %). Les scénarios clavier et le contrôle du français complètent l'audit ; **aucun essai avec un lecteur d'écran (NVDA, VoiceOver) n'a été fait** : les noms, rôles et annonces sont vérifiés par axe et par les tests, pas écoutés.",
  );
  lines.push(
    "- Les données sont simulées. Un contenu venant du serveur (messages, libellés d'une autre langue) n'est pas couvert.",
  );
  lines.push(
    "- Navigateur unique (celui indiqué plus haut) ; Firefox et Safari ne sont pas mesurés.",
  );
  lines.push(
    "- Les graphiques SVG sont mesurés comme le reste, mais leur lisibilité pour une personne aveugle repose sur le tableau de données qui les accompagne, dont l'équivalence n'est pas vérifiée automatiquement.",
    "",
  );
  return { text: lines.join("\n"), verdict, blockingCount: blocking.length };
}

async function main() {
  const executablePath = BROWSERS.find((path) => existsSync(path));
  if (!executablePath) throw new Error("aucun navigateur trouvé : définir BROWSER_PATH");
  const preview = await startPreview();
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    const browserVersion = `${browser.version()} (${executablePath.includes("msedge") || executablePath.includes("edge") ? "Edge" : "Chrome/Chromium"})`;
    const results = [];
    for (const scenario of scenarios) {
      const result = await measure(browser, preview.base, scenario);
      const wcag = result.violations.filter((v) => v.wcag).length;
      console.log(
        `${wcag === 0 ? "ok " : "KO "} ${scenario.name} : ${wcag} violation(s) WCAG, ${result.violations.length - wcag} avertissement(s)`,
      );
      results.push(result);
    }
    const keyboard = [
      ...(await keyboardChecks(browser, preview.base, "no-preference")),
      ...(await keyboardChecks(browser, preview.base, "reduce")),
    ];
    for (const c of keyboard) console.log(`${c.passed ? "ok " : "KO "} ${c.name}`);
    const playwright = JSON.parse(
      await readFile(require.resolve("playwright-core/package.json"), "utf8"),
    ).version;
    const report = {
      date: new Date().toISOString().slice(0, 10),
      axeVersion,
      playwright,
      browser: browserVersion,
      scenarios: results,
      keyboard,
    };
    const { text, verdict, blockingCount } = markdown(report);
    await mkdir(OUT, { recursive: true });
    await writeFile(new URL("resultats.json", OUT), JSON.stringify(report, null, 2) + "\n");
    await writeFile(new URL("rapport-accessibilite.md", OUT), text + "\n");
    console.log(
      `\n${verdict ? "AUCUNE ERREUR BLOQUANTE" : "ERREURS BLOQUANTES"} (${blockingCount} violation(s) WCAG)`,
    );
    if (CHECK && !verdict) process.exitCode = 1;
  } finally {
    await browser.close();
    preview.stop();
  }
}

await main();
