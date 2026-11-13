import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

/**
 * MS-14, critère d'acceptation : « Le tableau de bord affiche en direct les données des quatre services et
 * une commande manuelle y est appliquée et journalisée. » Le parcours va de la connexion à la vérification
 * du journal, sur la pile réelle (passerelle → services → bases).
 */
const OPERATOR = process.env.E2E_OPERATOR_USER;
const VIEWER = process.env.E2E_VIEWER_USER;
const PASSWORD = process.env.E2E_PASSWORD;
const SHOTS = process.env.E2E_SHOTS ?? "";

test.skip(
  !OPERATOR || !VIEWER || !PASSWORD,
  "E2E_OPERATOR_USER, E2E_VIEWER_USER et E2E_PASSWORD sont requis.",
);

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/MS-14-${name}.png` });
}

async function signIn(page: Page, username: string) {
  // Une fenêtre haute : la capture montre toute la page sans défilement (l'en-tête reste à sa place).
  await page.setViewportSize({ width: 1280, height: 1900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  await page.getByLabel("Identifiant").fill(username);
  await page.getByLabel("Mot de passe").fill(PASSWORD as string);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Tableau de bord" })).toBeVisible();
}

/** Jeton de l'API pour lire le journal et appeler la passerelle sans passer par l'interface. */
async function apiToken(request: APIRequestContext, username: string): Promise<string> {
  const response = await request.post("/api/v1/auth/login", {
    data: { username, password: PASSWORD },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).access_token;
}

const card = (overview: Locator, label: string) =>
  overview.getByText(label, { exact: true }).locator("xpath=ancestor::div[1]");

interface Signal {
  current_phase_id: string;
  signal: string;
  mode: string;
  phase_started_at: string;
  phase_ends_at: string;
  phases: { phase_id: string }[];
}

/**
 * Les garde-fous refusent un changement de phase avant 10 s de vert ou pendant le dégagement. Le parcours
 * attend un moment où la commande est permise : le carrefour n'est pas simulé, son temps est celui du service.
 */
async function waitForCommandWindow(
  request: APIRequestContext,
  headers: Record<string, string>,
  intersection: string,
  phase?: string,
) {
  await expect
    .poll(
      async () => {
        const body = await (
          await request.get(`/api/v1/signals/${intersection}`, { headers })
        ).json();
        const state = body as Signal;
        const elapsed = (Date.now() - Date.parse(state.phase_started_at)) / 1000;
        const remaining = (Date.parse(state.phase_ends_at) - Date.now()) / 1000;
        const right = phase === undefined || state.current_phase_id === phase;
        return right && state.signal === "GREEN" && elapsed >= 11 && remaining >= 12;
      },
      { timeout: 60_000, intervals: [500] },
    )
    .toBe(true);
}

test.describe.configure({ mode: "serial" });

test("tableau de bord en direct, commande manuelle appliquée et journalisée", async ({
  page,
  request,
}) => {
  await signIn(page, OPERATOR as string);

  // 1. Les quatre services répondent dans la vue d'ensemble : aucun n'est « Indisponible ».
  const overview = page.getByRole("region", { name: "En direct" });
  await expect(overview).toBeVisible();
  for (const service of ["Collecte", "Traitement", "Alertes", "Réponse"]) {
    await expect(card(overview, service)).toBeVisible();
    await expect(card(overview, service)).not.toContainText("Indisponible");
  }
  await expect(overview.getByRole("table")).toContainText("INT_01");
  await expect(page.getByRole("heading", { name: "Indicateurs clés" })).toBeVisible();
  await shot(page, "01-tableau-de-bord");

  // 2. L'état des feux vient du service de réponse : le même carrefour, la même phase que l'API.
  await page.getByRole("link", { name: "Feux de circulation" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Feux de circulation" })).toBeVisible();
  const intersection = page.getByRole("article", { name: "INT_01" });
  await expect(intersection).toBeVisible();
  await expect(page.getByText(/En direct · mis à jour/)).toBeVisible();

  const token = await apiToken(request, OPERATOR as string);
  const headers = { Authorization: `Bearer ${token}` };
  const states = await (await request.get("/api/v1/signals", { headers })).json();
  const api = states.items.find(
    (item: { intersection_id: string }) => item.intersection_id === "INT_01",
  );
  expect(api).toBeTruthy();
  await expect(intersection.getByTestId("current-phase")).toHaveText(api.current_phase_id);
  await shot(page, "02-etat-des-feux");

  // 3. Commande manuelle : imposer une autre phase, avec confirmation.
  const target = api.phases.find(
    (phase: { phase_id: string }) => phase.phase_id !== api.current_phase_id,
  );
  await waitForCommandWindow(request, headers, "INT_01");
  const reason = `Essai de bout en bout ${Date.now()}`;
  await page.getByRole("combobox", { name: "Phase" }).selectOption(target.phase_id);
  await page.getByLabel(/Durée/).fill("30");
  await page.getByLabel(/Motif/).fill(reason);
  await page.getByRole("button", { name: "Préparer la commande" }).click();
  await expect(page.getByRole("group", { name: "Confirmation" })).toContainText(
    `Imposer la phase ${target.phase_id} pendant 30 s sur INT_01 ?`,
  );
  await shot(page, "03-confirmation");
  await page.getByRole("button", { name: "Confirmer la commande" }).click();
  await expect(page.getByText(/Commande appliquée et journalisée/)).toBeVisible();

  // 4. L'effet se voit sans rechargement : mode manuel et phase imposée.
  await expect(intersection.getByText("Manuel", { exact: true })).toBeVisible();
  await expect(intersection.getByTestId("current-phase")).toHaveText(target.phase_id);
  await expect(intersection.getByText("Commande manuelle", { exact: true })).toBeVisible();

  // 5. Le journal montre la commande : opérateur, motif, statut « Appliquée ».
  const history = page.getByRole("table", { name: /Commandes de INT_01/ });
  const row = history.getByRole("row", { name: new RegExp(reason) });
  await expect(row).toContainText("Vous");
  await expect(row).toContainText("Appliquée");
  await shot(page, "04-commande-appliquee-et-journal");

  // 6. Une commande dangereuse est refusée et journalisée (garde-fou de 10 s minimum, hors interface).
  const refusedReason = `Refus de bout en bout ${Date.now()}`;
  const refused = await request.post("/api/v1/signals/INT_01/commands", {
    headers,
    data: { action: "SET_PHASE", phase_id: target.phase_id, duration_s: 5, reason: refusedReason },
  });
  expect([409, 422]).toContain(refused.status());
  const journal = await (
    await request.get("/api/v1/signals/INT_01/commands?limit=20", { headers })
  ).json();
  const applied = journal.items.find((item: { reason: string }) => item.reason === reason);
  const me = await (await request.get("/api/v1/auth/me", { headers })).json();
  expect(applied).toMatchObject({ status: "APPLIED", requested_by: me.user_id });
  if (refused.status() === 422) {
    expect(
      journal.items.find((item: { reason: string }) => item.reason === refusedReason),
    ).toMatchObject({
      status: "REFUSED",
    });
  }

  // 7. Rendre la main (permis après 10 s de vert de la phase tenue) : le carrefour quitte le mode
  // manuel, et la commande est journalisée aussi.
  await waitForCommandWindow(request, headers, "INT_01", target.phase_id);
  await page.getByRole("radio", { name: "Rendre la main" }).check();
  await page.getByLabel(/Motif/).fill(`Fin de l'essai ${Date.now()}`);
  await page.getByRole("button", { name: "Préparer la commande" }).click();
  await page.getByRole("button", { name: "Confirmer la commande" }).click();
  await expect(page.getByText(/Commande appliquée et journalisée/)).toBeVisible();
  // Sans recommandation récente, le service retombe sur son plan fixe : « Automatique » n'est pas assuré.
  await expect(intersection.getByText("Manuel", { exact: true })).toHaveCount(0);
  await expect(intersection.getByText(/Automatique|Plan fixe/).first()).toBeVisible();
  await shot(page, "05-retour-automatique");
});

test("le lecteur voit l'état et l'historique, mais ne peut pas commander", async ({
  page,
  request,
}) => {
  await signIn(page, VIEWER as string);
  await page.getByRole("link", { name: "Feux de circulation" }).first().click();
  await expect(page.getByRole("article", { name: "INT_01" })).toBeVisible();
  await expect(page.getByText(/réservée aux opérateurs/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Préparer la commande" })).toHaveCount(0);
  await shot(page, "06-lecteur-sans-commande");

  // La passerelle refuse aussi la requête directe : le rôle n'est pas qu'un détail d'affichage.
  const token = await apiToken(request, VIEWER as string);
  const response = await request.post("/api/v1/signals/INT_01/commands", {
    headers: { Authorization: `Bearer ${token}` },
    data: { action: "RESUME_AUTOMATIC", reason: "Tentative du lecteur" },
  });
  expect(response.status()).toBe(403);
});
