import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Reports from "@/features/reports/Reports";
import { saveBlob } from "@/features/reports/save";
import { clearSession, setAccessToken } from "@/services/session";
import type { Report } from "@/services/traitement";

// Réponses construites d'après le contrat (types générés : un champ manquant ou d'un autre type ne compile
// pas). La route /reports n'existe pas encore côté serveur et le robot (IA-07) non plus : ces tests prouvent
// le rendu et le téléchargement contre le contrat, pas le serveur.

vi.mock("@/features/reports/save", () => ({ saveBlob: vi.fn() }));

const HASH = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";

function report(index: number, overrides: Partial<Report> = {}): Report {
  const day = String(20 - index).padStart(2, "0");
  return {
    report_id: `3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d${String(index).padStart(2, "0")}`,
    title: `Rapport de supervision du ${day}/10/2026`,
    period_start: `2026-10-${day}T00:00:00Z`,
    period_end: `2026-10-${day}T23:59:59Z`,
    generated_at: `2026-10-${day}T23:30:00Z`,
    file_name: `rapport-2026-10-${day}.pdf`,
    size_bytes: 123_456,
    content_type: "application/pdf",
    sha256: HASH,
    ...overrides,
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const problem = (status: number, code: string) =>
  new Response(
    JSON.stringify({
      type: "about:blank",
      title: "Erreur",
      status,
      code,
      correlation_id: "corr-7",
    }),
    { status, headers: { "content-type": "application/problem+json" } },
  );

const PDF = new TextEncoder().encode("%PDF-1.7 contenu du rapport");
const pdf = () =>
  new Response(PDF, { status: 200, headers: { "content-type": "application/pdf" } });

interface Api {
  list?: (url: URL) => Response;
  content?: (reportId: string, request: Request) => Response;
}

function serve({ list, content }: Api = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (url.pathname === "/api/v1/reports") {
      return list ? list(url) : json({ items: [], next_cursor: null });
    }
    const match = /^\/api\/v1\/reports\/([^/]+)\/content$/.exec(url.pathname);
    if (match) return content ? content(match[1], request) : pdf();
    throw new Error(`Appel non prévu : ${url.pathname}`);
  });
}

/** Octets d'un Blob (jsdom n'a pas `Blob.arrayBuffer`). */
const bytesOf = (blob: Blob) =>
  new Promise<Uint8Array>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });

/** Les cellules de chaque ligne de données du tableau. */
const rows = () =>
  Array.from(screen.getAllByRole("row").slice(1), (row) =>
    Array.from(row.querySelectorAll("th, td"), (cell) =>
      (cell.textContent ?? "").replace(/\s+/g, " ").trim(),
    ),
  );

describe("Reports : un rapport produit par le robot apparaît dans la liste", () => {
  beforeEach(() => setAccessToken("jeton-de-test", 1800));
  afterEach(() => {
    vi.restoreAllMocks();
    vi.mocked(saveBlob).mockReset();
    clearSession();
  });

  it("affiche le rapport rendu par l'API avec son titre, sa période, sa date, sa taille et son empreinte", async () => {
    serve({ list: () => json({ items: [report(0)], next_cursor: null }) });
    render(<Reports />);

    await screen.findByRole("table", { name: "Rapports générés par le robot" });
    expect(rows()).toEqual([
      [
        "Rapport de supervision du 20/10/2026rapport-2026-10-20.pdf",
        "du 20/10/2026 00:00 au 20/10/2026 23:59",
        "20/10/2026 23:30",
        "123,5 ko",
        "9f86d081884c",
        "Télécharger",
      ],
    ]);
    expect(screen.getByText("9f86d081884c")).toHaveAttribute("title", HASH);
    expect(screen.getByRole("status")).toHaveTextContent("1 rapport affiché");
  });

  it("garde l'ordre de l'API (du plus récent au plus ancien) et lit une page de 20", async () => {
    const spy = serve({
      list: () => json({ items: [report(0), report(1), report(2)], next_cursor: null }),
    });
    render(<Reports />);

    await screen.findByRole("table");
    expect(rows().map((row) => row[2])).toEqual([
      "20/10/2026 23:30",
      "19/10/2026 23:30",
      "18/10/2026 23:30",
    ]);
    const asked = new URL((spy.mock.calls[0][0] as Request).url);
    expect(asked.searchParams.get("limit")).toBe("20");
    expect(asked.searchParams.has("cursor")).toBe(false);
  });

  it("affiche l'état vide tant que le robot n'a rien déposé", async () => {
    serve();
    render(<Reports />);

    expect(await screen.findByText("Aucun rapport généré pour le moment")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("dit que la route est absente du serveur (404) et propose de réessayer", async () => {
    let calls = 0;
    serve({
      list: () => {
        calls += 1;
        return calls === 1
          ? problem(404, "NOT_FOUND")
          : json({ items: [report(0)], next_cursor: null });
      },
    });
    render(<Reports />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le service des rapports n'est pas encore disponible sur ce serveur",
    );
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    await screen.findByRole("table");
    expect(rows()).toHaveLength(1);
  });

  it("cite la référence de corrélation d'une erreur serveur", async () => {
    serve({ list: () => problem(500, "INTERNAL_ERROR") });
    render(<Reports />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Une erreur est survenue côté serveur. Référence à citer : corr-7.",
    );
  });

  it("lit la page suivante par son curseur, sans doubler un rapport déjà affiché", async () => {
    const spy = serve({
      list: (url) =>
        url.searchParams.get("cursor") === "page-2"
          ? json({ items: [report(1), report(2)], next_cursor: null })
          : json({ items: [report(0), report(1)], next_cursor: "page-2" }),
    });
    render(<Reports />);
    await screen.findByRole("table");
    expect(screen.getByRole("status")).toHaveTextContent(
      "2 rapports affichés, d'autres sont disponibles",
    );

    await userEvent.click(screen.getByRole("button", { name: "Afficher la suite" }));

    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(rows().map((row) => row[1])).toEqual([
      "du 20/10/2026 00:00 au 20/10/2026 23:59",
      "du 19/10/2026 00:00 au 19/10/2026 23:59",
      "du 18/10/2026 00:00 au 18/10/2026 23:59",
    ]);
    expect(screen.queryByRole("button", { name: "Afficher la suite" })).not.toBeInTheDocument();
    const cursors = spy.mock.calls.map(([request]) =>
      new URL((request as Request).url).searchParams.get("cursor"),
    );
    expect(cursors).toEqual([null, "page-2"]);
  });

  it("garde la liste et dit l'échec quand la page suivante ne peut pas être lue", async () => {
    serve({
      list: (url) =>
        url.searchParams.has("cursor")
          ? problem(503, "UPSTREAM_UNAVAILABLE")
          : json({ items: [report(0)], next_cursor: "page-2" }),
    });
    render(<Reports />);
    await screen.findByRole("table");

    await userEvent.click(screen.getByRole("button", { name: "Afficher la suite" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "La page suivante n'a pas pu être lue.",
    );
    expect(rows()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Afficher la suite" })).toBeEnabled();
  });

  it("« Actualiser » relit la première page et montre le rapport apparu depuis", async () => {
    let calls = 0;
    serve({
      list: () => {
        calls += 1;
        return json({
          items: calls === 1 ? [report(1)] : [report(0), report(1)],
          next_cursor: null,
        });
      },
    });
    render(<Reports />);
    await screen.findByRole("table");
    expect(rows()).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Actualiser" }));

    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0][2]).toBe("20/10/2026 23:30");
  });
});

describe("Reports : téléchargement", () => {
  beforeEach(() => setAccessToken("jeton-de-test", 1800));
  afterEach(() => {
    vi.restoreAllMocks();
    vi.mocked(saveBlob).mockReset();
    clearSession();
  });

  it("lit le PDF avec le jeton puis l'enregistre sous le nom de fichier du rapport", async () => {
    const target = report(0);
    const seen: Array<{ id: string; authorization: string | null; method: string }> = [];
    serve({
      list: () => json({ items: [target], next_cursor: null }),
      content: (id, request) => {
        seen.push({
          id,
          authorization: request.headers.get("Authorization"),
          method: request.method,
        });
        return pdf();
      },
    });
    render(<Reports />);

    await userEvent.click(
      await screen.findByRole("button", { name: `Télécharger ${target.title}` }),
    );

    await waitFor(() => expect(saveBlob).toHaveBeenCalledTimes(1));
    expect(seen).toEqual([
      { id: target.report_id, authorization: "Bearer jeton-de-test", method: "GET" },
    ]);
    const [blob, fileName] = vi.mocked(saveBlob).mock.calls[0];
    expect(fileName).toBe("rapport-2026-10-20.pdf");
    expect(Array.from(await bytesOf(blob))).toEqual(Array.from(PDF));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("désactive le bouton du rapport pendant la lecture", async () => {
    let release: (response: Response) => void = () => undefined;
    const target = report(0);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      if (url.pathname === "/api/v1/reports") return json({ items: [target], next_cursor: null });
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    });
    render(<Reports />);

    await userEvent.click(
      await screen.findByRole("button", { name: `Télécharger ${target.title}` }),
    );

    const pending = await screen.findByRole("button", { name: `Télécharger ${target.title}` });
    expect(pending).toBeDisabled();
    expect(pending).toHaveTextContent("Téléchargement…");
    release(pdf());
    await waitFor(() => expect(pending).toBeEnabled());
  });

  it("dit l'échec, nomme le rapport et n'enregistre rien", async () => {
    const target = report(0);
    serve({
      list: () => json({ items: [target], next_cursor: null }),
      content: () => problem(404, "NOT_FOUND"),
    });
    render(<Reports />);

    await userEvent.click(
      await screen.findByRole("button", { name: `Télécharger ${target.title}` }),
    );

    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText(
        /Le téléchargement de « Rapport de supervision du 20\/10\/2026 » a échoué/,
      ),
    ).toBeInTheDocument();
    expect(alert).toHaveTextContent("Ce rapport est introuvable : il a peut-être été supprimé.");
    expect(alert).not.toHaveTextContent("pas encore disponible");
    expect(saveBlob).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: `Télécharger ${target.title}` })).toBeEnabled();
  });
});
