import { expect, test, type Page } from "@playwright/test";
import {
  french,
  installFakeApi,
  PASSWORD,
  scenario,
  TOKEN,
  USERNAME,
  type Expected,
} from "./support";

// Parcours de bout en bout de FE-08 : connexion → tableau de bord. Un vrai navigateur, l'application construite,
// une API simulée avec les réponses réelles enregistrées (voir support.ts).

const network = scenario("reseau-1h-5min").expected as Expected;
const zone = scenario("zone-INT_02-6h-5min").expected as Expected;

async function cardValue(page: Page, label: string): Promise<string> {
  const region = page.getByRole("region", { name: "Indicateurs clés" });
  const value = region.getByText(label, { exact: true }).locator("xpath=following-sibling::p[1]");
  return ((await value.textContent()) ?? "").replace(/\s+/g, " ").trim();
}

async function signIn(page: Page, password = PASSWORD) {
  await page.getByLabel("Identifiant").fill(USERNAME);
  await page.getByLabel("Mot de passe").fill(password);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

test("connexion puis tableau de bord, avec les valeurs de l'API", async ({ page }) => {
  const api = await installFakeApi(page);

  await test.step("sans session, la page protégée renvoie à la connexion et n'appelle aucune donnée", async () => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/connexion$/);
    await expect(page.getByRole("heading", { level: 1, name: "Connexion" })).toBeVisible();
    await expect(page).toHaveTitle("Connexion · Novaria Core");
    expect(api.calls.filter((call) => call.path.includes("/indicators"))).toEqual([]);
  });

  await test.step("un mauvais mot de passe est refusé, sans ouvrir de session", async () => {
    await signIn(page, "pas-le-bon");
    await expect(page.getByRole("alert")).toHaveText("Identifiant ou mot de passe incorrect.");
    await expect(page).toHaveURL(/\/connexion$/);
    await expect(page.getByLabel("Mot de passe")).toHaveValue("");
    expect(await page.evaluate(() => sessionStorage.getItem("novaria-session"))).toBeNull();
  });

  await test.step("les bons identifiants ouvrent le tableau de bord", async () => {
    await signIn(page);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1, name: "Tableau de bord" })).toBeVisible();
    await expect(page.getByText("operateur1 · Opérateur")).toBeVisible();
    await expect(page).toHaveTitle("Tableau de bord · Novaria Core");
  });

  await test.step("le jeton est gardé pour l'onglet seulement et part dans chaque appel de données", async () => {
    const session = await page.evaluate(() => ({
      tab: sessionStorage.getItem("novaria-session"),
      persistent: localStorage.getItem("novaria-session"),
    }));
    expect(JSON.parse(session.tab as string).token).toBe(TOKEN);
    expect(session.persistent).toBeNull();
    const data = api.calls.filter((call) => call.path.startsWith("/api/v1/indicators"));
    expect(data.length).toBeGreaterThan(0);
    for (const call of data) expect(call.authorization).toBe(`Bearer ${TOKEN}`);
  });

  await test.step("les fenêtres d'une minute sont vides : l'écran le dit et propose les 5 minutes", async () => {
    await page.getByRole("button", { name: "Essayer les fenêtres de 5 minutes" }).click();
    await expect(page.getByRole("region", { name: "Indicateurs clés" })).toBeVisible();
  });

  await test.step("les valeurs affichées sont celles de l'API : cartes, tronçons, origine", async () => {
    expect(await cardValue(page, "Vitesse moyenne")).toBe(`${french(network.cards.speed)} km/h`);
    expect(await cardValue(page, "Véhicules comptés")).toBe(french(network.cards.vehicles));
    expect(await cardValue(page, "Débit moyen")).toBe(`${french(network.cards.flow)} véh/min`);
    expect(await cardValue(page, "Tronçons congestionnés")).toBe(network.cards.congested);

    const rows = page.getByRole("region", { name: "Détail par tronçon" }).getByRole("row");
    await expect(rows).toHaveCount(network.meta.segment_count + 1); // + l'en-tête
    const first = network.segments[0];
    await expect(rows.nth(1)).toContainText(first.road_segment_id);
    await expect(rows.nth(1)).toContainText(first.intersection_id);

    await expect(page.getByText("Données simulées")).toBeVisible();
    await expect(page.getByText(`exécution ${network.meta.run_id}`)).toBeVisible();
    await expect(
      page.getByText(`${french(String(network.meta.indicator_count))} indicateurs`),
    ).toBeVisible();
  });

  await test.step("changer la zone et la période relit l'API et change l'écran", async () => {
    await page.getByLabel("Période").selectOption("6");
    await page.getByLabel("Zone").selectOption("INT_02");
    await expect(
      page.getByRole("region", { name: "Détail par tronçon" }).getByRole("row"),
    ).toHaveCount(zone.meta.segment_count + 1);
    expect(await cardValue(page, "Vitesse moyenne")).toBe(`${french(zone.cards.speed)} km/h`);
    expect(await cardValue(page, "Tronçons congestionnés")).toBe(zone.cards.congested);
  });

  await test.step("la navigation mène à une autre page protégée, sans nouvelle connexion", async () => {
    await page
      .getByRole("navigation", { name: "Navigation principale" })
      .getByRole("link", { name: "Alertes" })
      .click();
    await expect(page).toHaveURL(/\/alertes$/);
    await expect(page.getByRole("heading", { level: 1, name: "Alertes" })).toBeFocused();
  });

  await test.step("un rechargement garde la session", async () => {
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Alertes" })).toBeVisible();
    await expect(page).toHaveURL(/\/alertes$/);
  });

  await test.step("se déconnecter efface la session et referme les pages protégées", async () => {
    await page.getByRole("button", { name: "Se déconnecter" }).click();
    await expect(page).toHaveURL(/\/connexion/);
    expect(await page.evaluate(() => sessionStorage.getItem("novaria-session"))).toBeNull();
    await page.goto("/");
    await expect(page).toHaveURL(/\/connexion/);
  });

  expect(api.unexpected, "appels d'API sans réponse prévue").toEqual([]);
  // Choisir la période (6 h) avant la zone passe par « 6 h, tout le réseau », que l'API n'a pas enregistré : c'est
  // la seule lecture sans réponse enregistrée, et l'écran final est bien celui de « 6 h, INT_02 ».
  expect(api.unrecordedIndicators).toEqual([expect.objectContaining({ window_size_s: "300" })]);
  expect(api.unrecordedIndicators[0]).not.toHaveProperty("intersection_id");
});

test("une session refusée par le serveur renvoie à la connexion", async ({ page }) => {
  await installFakeApi(page, { rejectToken: true });
  await page.goto("/connexion");
  await signIn(page);
  // La connexion réussit, mais le serveur refuse ensuite le jeton : on revient à la connexion, sans écran de données.
  await expect(page).toHaveURL(/\/connexion/);
  await expect(page.getByRole("heading", { level: 1, name: "Connexion" })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("novaria-session"))).toBeNull();
  // Aucune donnée n'est affichée : le serveur a refusé le jeton, toute lecture reçoit un 401.
  await expect(page.getByRole("region", { name: "Indicateurs clés" })).toHaveCount(0);
});

test("une panne de l'API est dite, puis « Réessayer » relit les données", async ({ page }) => {
  const api = await installFakeApi(page, { indicatorFailures: 1 });
  await page.goto("/connexion");
  await signIn(page);

  await expect(page.getByText("Impossible de charger les indicateurs")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("momentanément indisponible");
  await expect(page.getByRole("alert")).toContainText("e2e-corr");

  await page.getByRole("button", { name: "Réessayer" }).click();
  await expect(
    page.getByRole("button", { name: "Essayer les fenêtres de 5 minutes" }),
  ).toBeVisible();
  expect(api.unexpected).toEqual([]);
});
