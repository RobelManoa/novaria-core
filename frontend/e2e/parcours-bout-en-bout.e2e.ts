import { expect, test, type Page } from "@playwright/test";

/**
 * CLD-13 : la fin du parcours de bout en bout, vue du navigateur. `dev.py parcours` envoie une minute de mesures
 * brutes, attend l'entrepôt et l'API, puis lance ce fichier sur le front-end construit (nginx) avec les valeurs
 * qu'il a recalculées depuis les mesures. Rien n'est simulé : le navigateur parle à la passerelle et aux services.
 *
 * Variables (jamais écrites dans un fichier du dépôt) : E2E_USER et E2E_PASSWORD (compte jetable créé par le parcours),
 * E2E_ATTENDU (JSON des valeurs à voir), E2E_TOKEN_EXPIRE (jeton correctement signé mais expiré).
 */
const USER = process.env.E2E_USER;
const PASSWORD = process.env.E2E_PASSWORD;
const ATTENDU = process.env.E2E_ATTENDU;
const EXPIRE = process.env.E2E_TOKEN_EXPIRE;

interface Attendu {
  run_id: string;
  vitesse: string;
  vehicules: string;
  debit: string;
  troncon: string;
}

test.skip(!USER || !PASSWORD, "E2E_USER et E2E_PASSWORD sont requis (dev.py parcours).");

async function cardValue(page: Page, label: string): Promise<string> {
  const region = page.getByRole("region", { name: "Indicateurs clés" });
  const value = region.getByText(label, { exact: true }).locator("xpath=following-sibling::p[1]");
  return ((await value.textContent()) ?? "").replace(/\s+/g, " ").trim();
}

test("le tableau de bord affiche la minute envoyée en donnée brute", async ({ page }) => {
  test.skip(!ATTENDU, "E2E_ATTENDU est requis.");
  const attendu = JSON.parse(ATTENDU as string) as Attendu;

  await page.goto("/");
  await page.getByLabel("Identifiant").fill(USER as string);
  await page.getByLabel("Mot de passe").fill(PASSWORD as string);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Tableau de bord" })).toBeVisible();

  await expect(page.getByText(`exécution ${attendu.run_id}`)).toBeVisible();
  await expect(page.getByText("Données simulées")).toBeVisible();
  expect(await cardValue(page, "Vitesse moyenne")).toBe(attendu.vitesse);
  expect(await cardValue(page, "Véhicules comptés")).toBe(attendu.vehicules);
  expect(await cardValue(page, "Débit moyen")).toBe(attendu.debit);

  const rows = page.getByRole("region", { name: "Détail par tronçon" }).getByRole("row");
  await expect(rows).toHaveCount(2); // l'en-tête et l'unique tronçon du run
  await expect(rows.nth(1)).toContainText(attendu.troncon);
});

test("un jeton expiré renvoie à la connexion sans afficher de donnée", async ({ page }) => {
  test.skip(!EXPIRE, "E2E_TOKEN_EXPIRE est requis.");
  // Le navigateur croit sa session valable : c'est le serveur qui la refuse (401), comme après une longue pause.
  await page.addInitScript((token) => {
    sessionStorage.setItem(
      "novaria-session",
      JSON.stringify({ token, expiresAt: Date.now() + 600_000 }),
    );
  }, EXPIRE as string);

  await page.goto("/");
  await expect(page).toHaveURL(/\/connexion/);
  await expect(page.getByRole("heading", { level: 1, name: "Connexion" })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("novaria-session"))).toBeNull();
  await expect(page.getByRole("region", { name: "Indicateurs clés" })).toHaveCount(0);
});
