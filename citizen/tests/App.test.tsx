import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError } from "../src/api";
import type { SegmentState } from "../src/types";
import { network, segment } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z"); // 2 minutes après la mise à jour de la fixture

type Fetcher = (signal: AbortSignal) => Promise<SegmentState[]>;

/** Une case du résumé se lit « 1 tronçon congestionné » : le nombre et le nom sont deux éléments, le texte de la case est le tout. */
const case_ = (texte: string) => (_: string, element: Element | null) =>
  element?.tagName === "LI" &&
  element.className.includes("resume__case") &&
  element.textContent === texte;

function show(fetcher: Fetcher, now = () => NOW) {
  return render(
    <App fetcher={fetcher} intervalMs={15_000} now={now} alertsFetcher={async () => []} />,
  );
}

function pending() {
  let resolve!: (value: SegmentState[]) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<SegmentState[]>((ok, ko) => {
    resolve = ok;
    reject = ko;
  });
  return { promise, resolve, reject };
}

describe("état de la circulation", () => {
  beforeEach(() => {
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.useRealTimers());

  describe("chargement", () => {
    it("dit qu'il charge, sans liste, et garde la mention des données simulées", () => {
      show(() => new Promise<SegmentState[]>(() => {}));
      expect(screen.getByRole("status")).toHaveTextContent("Chargement de la circulation…");
      expect(screen.getByRole("note")).toHaveTextContent("Données simulées");
      expect(screen.queryByRole("region", { name: "Par carrefour" })).not.toBeInTheDocument();
    });
  });

  describe("vue principale", () => {
    it("montre d'un coup d'œil combien de tronçons sont fluides, ralentis ou congestionnés", async () => {
      show(async () => network());
      const resume = await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(within(resume).getByText(case_("1 tronçon congestionné"))).toBeInTheDocument();
      expect(within(resume).getByText(case_("1 tronçon ralenti"))).toBeInTheDocument();
      expect(within(resume).getByText(case_("3 tronçons fluides"))).toBeInTheDocument();
      expect(within(resume).getByText(case_("1 tronçon sans information"))).toBeInTheDocument();
    });

    it("n'affiche « sans information » que s'il y en a", async () => {
      show(async () => [segment()]);
      const resume = await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(within(resume).queryByText(/sans information/)).not.toBeInTheDocument();
      expect(within(resume).getByText(case_("1 tronçon fluide"))).toBeInTheDocument();
    });

    it("liste les tronçons par carrefour, avec leur côté et un état dit en mots", async () => {
      show(async () => network());
      const premier = await screen.findByRole("region", { name: "Carrefour INT_01" });
      const cartes = within(premier).getAllByRole("listitem");
      expect(cartes).toHaveLength(4);
      expect(within(cartes[0]).getByText("Arrivée par le nord")).toBeInTheDocument();
      expect(within(cartes[0]).getAllByText("Congestionné").length).toBeGreaterThan(0);
      expect(within(cartes[1]).getByText("Arrivée par l'est")).toBeInTheDocument();
      expect(within(cartes[1]).getAllByText("Ralenti").length).toBeGreaterThan(0);
      const second = screen.getByRole("region", { name: "Carrefour INT_02" });
      expect(within(second).getAllByRole("listitem")).toHaveLength(2);
      expect(within(second).getByText("Information indisponible")).toBeInTheDocument();
    });

    it("n'écrit jamais un code technique à l'écran", async () => {
      show(async () => network());
      await screen.findByRole("region", { name: "Carrefour INT_01" });
      const texte = document.body.textContent ?? "";
      for (const code of [
        "FREE_FLOW",
        "SLOW",
        "CONGESTED",
        "UNKNOWN",
        "road_segment_id",
        "undefined",
        "NaN",
        "null",
      ]) {
        expect(texte).not.toContain(code);
      }
    });

    it("dit que chaque tronçon est simulé", async () => {
      show(async () => [segment(), segment({ road_segment_id: "ROAD_002", simulated: false })]);
      await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(screen.getAllByText(/Simulé/)).toHaveLength(1);
      expect(screen.getByRole("note")).toHaveTextContent("ne décrivent pas la circulation réelle");
    });

    it("donne l'heure des données et leur âge, pas l'heure de l'appel", async () => {
      show(async () => network());
      await screen.findByRole("region", { name: "En un coup d'œil" });
      const ligne = screen.getByText(/Données de/);
      expect(ligne).toHaveTextContent("il y a 2 min");
      expect(within(ligne).getByText(/^\d{2}:\d{2}$/)).toHaveAttribute(
        "datetime",
        "2026-11-20T09:10:00Z",
      );
    });

    it("a la structure d'une page : un seul titre 1, un contenu principal, un pied de page, un lien d'évitement", async () => {
      show(async () => network());
      await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.getByRole("main")).toHaveAttribute("id", "contenu");
      expect(screen.getByRole("contentinfo")).toHaveTextContent("Aucun compte, aucun cookie");
      expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveAttribute(
        "href",
        "#contenu",
      );
    });

    it("n'a besoin d'aucune connexion : aucun champ de saisie, aucun lien de connexion", async () => {
      show(async () => network());
      await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/mot de passe|identifiant/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/se connecter|connexion/i)).not.toBeInTheDocument();
    });
  });

  describe("liste vide et information ancienne", () => {
    it("une liste vide est dite sans être une erreur", async () => {
      show(async () => []);
      expect(await screen.findByText("Aucune information pour le moment")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("avertit quand les mesures datent de plus de 10 minutes", async () => {
      show(
        async () => network(),
        () => NOW + 20 * 60_000,
      );
      expect(await screen.findByText(/Information ancienne/)).toBeInTheDocument();
    });

    it("n'avertit pas d'une information récente", async () => {
      show(async () => network());
      await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(screen.queryByText(/Information ancienne/)).not.toBeInTheDocument();
    });
  });

  describe("erreurs", () => {
    it.each([
      ["reseau", /Vérifiez votre connexion/],
      ["limite", /Trop de demandes/],
      ["indisponible", /momentanément indisponible/],
      ["format", /pas exploitable/],
    ] as const)(
      "sans donnée, l'erreur « %s » est dite en français avec un bouton « Réessayer »",
      async (kind, message) => {
        show(async () => {
          throw new ApiError(kind, "détail technique");
        });
        const alerte = await screen.findByRole("alert");
        expect(alerte).toHaveTextContent(message);
        expect(alerte).not.toHaveTextContent("détail technique");
        expect(within(alerte).getByRole("button", { name: "Réessayer" })).toBeEnabled();
        expect(screen.getByRole("note")).toHaveTextContent("Données simulées");
      },
    );

    it("« Réessayer » relit l'API et affiche les données quand elle répond", async () => {
      const fetcher = vi
        .fn<Fetcher>()
        .mockRejectedValueOnce(new ApiError("reseau", "x"))
        .mockResolvedValue(network());
      show(fetcher);
      await userEvent.click(await screen.findByRole("button", { name: "Réessayer" }));
      expect(await screen.findByRole("region", { name: "En un coup d'œil" })).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("une erreur inattendue (pas une ApiError) est dite comme les autres, sans détail", async () => {
      show(async () => {
        throw new Error("boum postgresql://u:p@h");
      });
      const alerte = await screen.findByRole("alert");
      expect(alerte).toHaveTextContent("pas exploitable");
      expect(alerte).not.toHaveTextContent("postgresql");
    });

    it("une erreur après un succès garde les dernières données et le dit", async () => {
      const fetcher = vi
        .fn<Fetcher>()
        .mockResolvedValueOnce(network())
        .mockRejectedValue(new ApiError("indisponible", "x"));
      show(fetcher);
      await screen.findByRole("region", { name: "En un coup d'œil" });
      await userEvent.click(screen.getByRole("button", { name: "Actualiser" }));
      expect(await screen.findByText(/Mise à jour impossible/)).toBeInTheDocument();
      expect(screen.getByText(/dernière information connue/)).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Carrefour INT_01" })).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("l'avertissement disparaît dès qu'une lecture réussit", async () => {
      const fetcher = vi
        .fn<Fetcher>()
        .mockResolvedValueOnce(network())
        .mockRejectedValueOnce(new ApiError("reseau", "x"))
        .mockResolvedValue(network());
      show(fetcher);
      await screen.findByRole("region", { name: "En un coup d'œil" });
      await userEvent.click(screen.getByRole("button", { name: "Actualiser" }));
      await screen.findByText(/Mise à jour impossible/);
      await userEvent.click(screen.getByRole("button", { name: "Actualiser" }));
      await waitFor(() =>
        expect(screen.queryByText(/Mise à jour impossible/)).not.toBeInTheDocument(),
      );
    });
  });

  describe("rafraîchissement", () => {
    it("relit toutes les 15 secondes, sans action de l'usager", async () => {
      vi.useFakeTimers();
      const fetcher = vi.fn<Fetcher>().mockResolvedValue(network());
      show(fetcher);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(fetcher).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(fetcher).toHaveBeenCalledTimes(2);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(fetcher).toHaveBeenCalledTimes(4);
    });

    it("ne relit rien tant que la page est cachée, et relit au retour", async () => {
      vi.useFakeTimers();
      const fetcher = vi.fn<Fetcher>().mockResolvedValue(network());
      show(fetcher);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      Object.defineProperty(document, "hidden", { value: true, configurable: true });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(fetcher).toHaveBeenCalledTimes(1);
      Object.defineProperty(document, "hidden", { value: false, configurable: true });
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("annule la lecture en cours quand la page est quittée", async () => {
      const lecture = pending();
      let signal: AbortSignal | undefined;
      const { unmount } = show((s) => {
        signal = s;
        return lecture.promise;
      });
      expect(signal?.aborted).toBe(false);
      unmount();
      expect(signal?.aborted).toBe(true);
    });

    it("une réponse tardive d'une lecture annulée n'écrase pas la plus récente", async () => {
      vi.useFakeTimers();
      const premiere = pending();
      const fetcher = vi
        .fn<Fetcher>()
        .mockReturnValueOnce(premiere.promise)
        .mockResolvedValue([segment({ state: "SLOW" })]);
      show(fetcher);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(screen.getByText(case_("1 tronçon ralenti"))).toBeInTheDocument();
      await act(async () => {
        premiere.resolve([segment({ state: "CONGESTED" })]);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText(case_("1 tronçon ralenti"))).toBeInTheDocument();
      expect(screen.queryByText(case_("1 tronçon congestionné"))).not.toBeInTheDocument();
    });

    it("le bouton « Actualiser » est occupé pendant la lecture et rend la main ensuite", async () => {
      const seconde = pending();
      const fetcher = vi
        .fn<Fetcher>()
        .mockResolvedValueOnce(network())
        .mockReturnValueOnce(seconde.promise);
      show(fetcher);
      const bouton = await screen.findByRole("button", { name: "Actualiser" });
      await userEvent.click(bouton);
      expect(screen.getByRole("button", { name: "Actualisation…" })).toBeDisabled();
      await act(async () => seconde.resolve(network()));
      expect(await screen.findByRole("button", { name: "Actualiser" })).toBeEnabled();
    });
  });

  describe("vie privée", () => {
    it("ne garde rien sur l'appareil : ni stockage, ni cookie", async () => {
      const ecriture = vi.spyOn(Storage.prototype, "setItem");
      show(async () => network());
      await screen.findByRole("region", { name: "En un coup d'œil" });
      expect(ecriture).not.toHaveBeenCalled();
      expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");
    });
  });
});
