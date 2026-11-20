import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ROLE_LABELS, useAuth } from "@/features/auth/AuthContext";

function Probe() {
  useAuth();
  return <p>dans le fournisseur</p>;
}

describe("useAuth", () => {
  afterEach(() => vi.restoreAllMocks());

  it("échoue en le disant quand il est utilisé hors d'un AuthProvider", () => {
    // React journalise l'erreur d'un composant qui échoue : on la fait taire pour ne pas polluer la sortie.
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow("useAuth doit être utilisé dans un AuthProvider");
    expect(screen.queryByText("dans le fournisseur")).not.toBeInTheDocument();
  });

  it("donne un libellé en français à chaque rôle", () => {
    expect(ROLE_LABELS).toEqual({
      viewer: "Lecteur",
      operator: "Opérateur",
      admin: "Administrateur",
    });
  });
});
