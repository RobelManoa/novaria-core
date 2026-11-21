import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError } from "../src/api";
import type { SegmentState } from "../src/types";
import { network, segment } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z"); // 2 minutes après la mise à jour de la fixture

type Fetcher = (signal: AbortSignal) => Promise<SegmentState[]>;

/** Ce que le citoyen voit en premier : au moins un trajet (proposé ou gardé) avec son verdict. */
const attendreLesTrajets = () => screen.findByRole("region", { name: /trajets/i });

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
    window.localStorage.clear();
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.useRealTimers());

  describe("chargement", () => {
    it("dit qu'il charge, sans liste, et garde la mention des données simulées", () => {
      show(() => new Promise<SegmentState[]>(() => {}));
      expect(screen.getByRole("status")).toHaveTextContent("Chargement de la circulation…");
      expect(screen.getByRole("note")).toHaveTextContent("Données simulées");
      expect(screen.queryByRole("region", { name: /trajets/i })).not.toBeInTheDocument();
    });
  });

  describe("vue principale", () => {
    it("montre d'abord des trajets proposés, chacun avec un mot et une phrase pour décider", async () => {
      show(async () => network());
      const region = await attendreLesTrajets();
      expect(within(region).getByRole("heading", { level: 2 })).toHaveTextContent(
        "Des trajets pour essayer",
      );
      const cartes = within(region).getAllByRole("listitem", {
        name: /Aller à la gare|Aller au marché|Déposer les enfants/,
      });
      expect(cartes).toHaveLength(3);
      const gare = within(region).getByRole("listitem", { name: "Aller à la gare" });
      expect(gare).toHaveTextContent("Bloqué"); // ROAD_001 congestionné dans la fixture
      expect(gare).toHaveTextContent("Prévoyez beaucoup de retard");
      expect(gare).toHaveTextContent("Place de la Gare, en venant du nord");
    });

    it("n'écrit jamais un code technique à l'écran", async () => {
      show(async () => network());
      await attendreLesTrajets();
      const details = document.querySelectorAll("details");
      details.forEach((d) => d.setAttribute("open", ""));
      expect(document.body.textContent).not.toMatch(
        /ROAD_|INT_|\bUNKNOWN\b|FREE_FLOW|CONGESTED|\bSLOW\b|undefined|\[object/,
      );
    });

    it("donne l'heure des mesures et leur âge, pas l'heure de l'appel", async () => {
      show(async () => network());
      await attendreLesTrajets();
      expect(screen.getAllByText(/il y a 2 min/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/^\d{2}:\d{2}$/)[0]).toHaveAttribute(
        "datetime",
        "2026-11-20T09:10:00Z",
      );
    });

    it("a la structure d'une page : un seul titre 1, un contenu principal, un pied de page, un lien d'évitement", async () => {
      show(async () => network());
      await attendreLesTrajets();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.getByRole("main")).toBeInTheDocument();
      expect(screen.getByRole("contentinfo")).toHaveTextContent(
        "Vos trajets restent sur cet appareil",
      );
      expect(screen.getByRole("contentinfo")).toHaveTextContent("aucun compte, aucun cookie");
      expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveAttribute(
        "href",
        "#contenu",
      );
    });

    it("n'a besoin d'aucune connexion : aucun champ de mot de passe, aucun lien de connexion", async () => {
      show(async () => network());
      await attendreLesTrajets();
      expect(document.querySelector("input[type=password]")).toBeNull();
      expect(
        screen.queryByRole("link", { name: /connexion|compte|inscri/i }),
      ).not.toBeInTheDocument();
    });
  });

  describe("liste vide et information ancienne", () => {
    it("une liste vide n'est pas une erreur : chaque trajet dit « Information indisponible »", async () => {
      show(async () => []);
      const region = await attendreLesTrajets();
      for (const nom of ["Aller à la gare", "Aller au marché", "Déposer les enfants à l'école"]) {
        expect(within(region).getByRole("listitem", { name: nom })).toHaveTextContent(
          "Information indisponible",
        );
      }
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
      await attendreLesTrajets();
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
      expect(await attendreLesTrajets()).toBeInTheDocument();
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
      await attendreLesTrajets();
      await userEvent.click(screen.getByRole("button", { name: "Actualiser" }));
      expect(await screen.findByText(/Mise à jour impossible/)).toBeInTheDocument();
      expect(screen.getByText(/dernière information connue/)).toBeInTheDocument();
      expect(screen.getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent("Bloqué"); // la dernière information reste
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("l'avertissement disparaît dès qu'une lecture réussit", async () => {
      const fetcher = vi
        .fn<Fetcher>()
        .mockResolvedValueOnce(network())
        .mockRejectedValueOnce(new ApiError("reseau", "x"))
        .mockResolvedValue(network());
      show(fetcher);
      await attendreLesTrajets();
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
        .mockResolvedValue([segment({ road_segment_id: "ROAD_001", state: "SLOW" })]);
      show(fetcher);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      const gare = () => screen.getByRole("listitem", { name: "Aller à la gare" });
      expect(gare()).toHaveTextContent("Ralenti");
      await act(async () => {
        premiere.resolve([segment({ road_segment_id: "ROAD_001", state: "CONGESTED" })]);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(gare()).toHaveTextContent("Ralenti");
      expect(gare()).not.toHaveTextContent("Bloqué");
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
    it("n'écrit rien sur l'appareil tant que le citoyen n'a rien gardé, et n'utilise aucun cookie", async () => {
      const ecriture = vi.spyOn(Storage.prototype, "setItem");
      show(async () => network());
      await attendreLesTrajets();
      expect(ecriture.mock.calls.filter(([cle]) => cle !== "novaria-citoyen-sonde")).toEqual([]);
      expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");
    });
  });
});
