import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/app/App";
import { routes } from "@/app/router";
import { getAccessToken, setAccessToken } from "@/services/session";
import { mockApi, renderApp, signIn } from "../utils/renderApp";

const PROTECTED: Array<[path: string, title: string]> = [
  ["/", "Tableau de bord"],
  ["/alertes", "Alertes"],
  ["/feux", "Feux de circulation"],
  ["/previsions", "Prévisions"],
  ["/rapports", "Rapports"],
];

const problem = (status: number, code: string) =>
  new Response(
    JSON.stringify({
      type: `https://novaria.local/problems/${code.toLowerCase()}`,
      title: "Erreur",
      status,
      code,
      correlation_id: "corr-test",
    }),
    { status, headers: { "content-type": "application/problem+json" } },
  );

const hasShell = () => screen.queryByRole("navigation", { name: "Navigation principale" }) !== null;

async function seConnecter(identifiant = "operateur1", motDePasse = "mot-de-passe-d-exemple") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Identifiant"), identifiant);
  await user.type(screen.getByLabelText("Mot de passe"), motDePasse);
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
}

describe("une route protégée est inaccessible sans connexion", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([...PROTECTED.map(([path]) => path), "/page-inconnue", "/alertes?niveau=critique"])(
    "%s renvoie vers la page de connexion, sans rien afficher ni appeler",
    async (path) => {
      const { router, fetchSpy } = renderApp(path, { signedIn: false });

      expect(
        await screen.findByRole("heading", { level: 1, name: "Connexion" }),
      ).toBeInTheDocument();
      expect(router.state.location.pathname).toBe("/connexion");
      expect(hasShell()).toBe(false);
      expect(screen.queryByRole("button", { name: "Se déconnecter" })).not.toBeInTheDocument();
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("retient l'adresse demandée pour y revenir après la connexion", async () => {
    const { router } = renderApp("/alertes?niveau=critique", { signedIn: false });
    await screen.findByRole("heading", { level: 1, name: "Connexion" });
    expect(router.state.location.state).toEqual({ from: "/alertes?niveau=critique" });
  });

  it("n'affiche aucune page protégée dans le routeur, même en navigant par programme", async () => {
    const { router } = renderApp("/connexion", { signedIn: false });
    await screen.findByRole("heading", { level: 1, name: "Connexion" });

    await router.navigate("/rapports");

    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"));
    expect(screen.queryByRole("heading", { level: 1, name: "Rapports" })).not.toBeInTheDocument();
  });

  it("n'accepte pas un jeton expiré déjà présent dans le stockage", async () => {
    setAccessToken("jeton-perime", -60);
    const { router, fetchSpy } = renderApp("/feux", { signedIn: false });

    expect(await screen.findByRole("heading", { level: 1, name: "Connexion" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/connexion");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("renvoie à la connexion quand le jeton expire pendant la session", async () => {
    const { router } = renderApp("/alertes", { signedIn: false });
    await screen.findByRole("heading", { level: 1, name: "Connexion" });
    signIn(0.3);

    expect(await screen.findByRole("heading", { level: 1, name: "Alertes" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"), {
      timeout: 3000,
    });
    expect(getAccessToken()).toBeNull();
  });

  it("renvoie à la connexion quand l'API refuse le jeton (401)", async () => {
    const { router } = renderApp("/", {
      api: { "GET /api/v1/auth/me": () => problem(401, "UNAUTHENTICATED") },
    });

    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"));
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.getItem("novaria-session")).toBeNull();
  });
});

describe("page de connexion", () => {
  afterEach(() => vi.restoreAllMocks());

  it("ouvre la session, garde le jeton de l'onglet et revient à la page demandée", async () => {
    const { router, fetchSpy } = renderApp("/alertes", { signedIn: false });
    await seConnecter();

    expect(await screen.findByRole("heading", { level: 1, name: "Alertes" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/alertes");

    const requests = fetchSpy.mock.calls.map(([input]) => input as Request);
    const login = requests.find(
      (request) => new URL(request.url).pathname === "/api/v1/auth/login",
    );
    expect(login?.method).toBe("POST");
    expect(await login?.clone().json()).toEqual({
      username: "operateur1",
      password: "mot-de-passe-d-exemple",
    });
    expect(getAccessToken()).toBe("jeton-de-test");
    expect(JSON.parse(window.sessionStorage.getItem("novaria-session") ?? "{}")).toMatchObject({
      token: "jeton-de-test",
    });
    expect(window.localStorage.getItem("novaria-session")).toBeNull();
    expect(await screen.findByText("operateur1 · Opérateur")).toBeInTheDocument();
  });

  it("envoie les appels suivants avec le jeton", async () => {
    const { fetchSpy } = renderApp("/", { signedIn: false });
    await seConnecter();
    await screen.findByText("operateur1 · Opérateur");

    const me = fetchSpy.mock.calls
      .map(([input]) => input as Request)
      .find((request) => new URL(request.url).pathname === "/api/v1/auth/me");
    expect(me?.headers.get("Authorization")).toBe("Bearer jeton-de-test");
  });

  it("va au tableau de bord quand aucune adresse n'était demandée", async () => {
    const { router } = renderApp("/connexion", { signedIn: false });
    await seConnecter();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Tableau de bord" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("refuse des identifiants faux : message, aucun jeton, mot de passe vidé", async () => {
    const { router, fetchSpy } = renderApp("/rapports", {
      signedIn: false,
      api: { "POST /api/v1/auth/login": () => problem(401, "INVALID_CREDENTIALS") },
    });
    await seConnecter("operateur1", "mauvais");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Identifiant ou mot de passe incorrect.",
    );
    expect(router.state.location.pathname).toBe("/connexion");
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.getItem("novaria-session")).toBeNull();
    expect(screen.getByLabelText("Mot de passe")).toHaveValue("");
    expect(screen.getByLabelText("Identifiant")).toHaveValue("operateur1");
    const paths = fetchSpy.mock.calls.map(([input]) => new URL((input as Request).url).pathname);
    expect(paths).toEqual(["/api/v1/auth/login"]);
  });

  it("annonce une panne réseau sans ouvrir de session", async () => {
    renderApp("/", { signedIn: false });
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await seConnecter();

    expect(await screen.findByRole("alert")).toHaveTextContent("injoignable");
    expect(getAccessToken()).toBeNull();
  });

  it("empêche un double envoi pendant la connexion", async () => {
    let release: (response: Response) => void = () => {};
    const { fetchSpy } = renderApp("/", {
      signedIn: false,
      api: {
        "POST /api/v1/auth/login": () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      },
    });
    await seConnecter();

    const bouton = await screen.findByRole("button", { name: "Connexion…" });
    expect(bouton).toBeDisabled();
    release(
      new Response(JSON.stringify({ access_token: "t", token_type: "bearer", expires_in: 60 })),
    );
    await screen.findByRole("heading", { level: 1, name: "Tableau de bord" });
    const logins = fetchSpy.mock.calls.filter(
      ([input]) => new URL((input as Request).url).pathname === "/api/v1/auth/login",
    );
    expect(logins).toHaveLength(1);
  });

  it("renvoie un utilisateur déjà connecté vers le tableau de bord", async () => {
    const { router } = renderApp("/connexion");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Tableau de bord" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("ignore une adresse de retour externe", async () => {
    mockApi();
    signIn();
    const router = createMemoryRouter(routes, {
      initialEntries: [{ pathname: "/connexion", state: { from: "//evil.example/piege" } }],
    });
    render(<App router={router} />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Tableau de bord" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("pages protégées avec une session", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(PROTECTED)("%s est accessible", async (path, title) => {
    const { router } = renderApp(path);
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(path);
    expect(hasShell()).toBe(true);
  });

  it("garde la session si le profil ne répond pas (erreur autre que 401)", async () => {
    const { router } = renderApp("/alertes", {
      api: { "GET /api/v1/auth/me": () => problem(503, "UPSTREAM_UNAVAILABLE") },
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Alertes" })).toBeInTheDocument();
    await waitFor(() => expect(getAccessToken()).toBe("jeton-de-test"));
    expect(router.state.location.pathname).toBe("/alertes");
    expect(screen.queryByText(/operateur1/)).not.toBeInTheDocument();
  });

  it("se déconnecte : jeton effacé, retour à la connexion, page de nouveau inaccessible", async () => {
    const { router } = renderApp("/feux");
    await screen.findByText("operateur1 · Opérateur");

    await userEvent.setup().click(screen.getByRole("button", { name: "Se déconnecter" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Connexion" })).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.getItem("novaria-session")).toBeNull();
    expect(hasShell()).toBe(false);

    await router.navigate("/feux");
    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"));
    expect(
      within(document.body).queryByRole("heading", { name: "Feux de circulation" }),
    ).toBeNull();
  });
});
