import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatCard from "@/components/StatCard";
import StateMessage from "@/components/StateMessage";

describe("StatCard", () => {
  it("affiche le libellé, la valeur avec son unité, et la définition", () => {
    render(<StatCard label="Vitesse moyenne" value="28,6" unit="km/h" hint="Pondérée" />);

    expect(screen.getByText("Vitesse moyenne")).toBeInTheDocument();
    expect(screen.getByText("28,6").parentElement).toHaveTextContent("28,6 km/h");
    expect(screen.getByText("Pondérée")).toBeInTheDocument();
  });

  it("n'écrit ni unité ni définition quand il n'y en a pas", () => {
    const { container } = render(<StatCard label="Véhicules" value="42" />);

    expect(container.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByText("42").parentElement).toHaveTextContent(/^42$/);
  });
});

describe("StateMessage", () => {
  it("annonce un chargement poliment et le marque comme occupé", () => {
    render(<StateMessage kind="loading" title="Chargement…" />);

    const box = screen.getByRole("status");
    expect(box).toHaveAttribute("aria-busy", "true");
    expect(box).toHaveTextContent("Chargement…");
  });

  it("annonce un état vide poliment, sans l'état occupé", () => {
    render(<StateMessage kind="empty" title="Rien" />);

    expect(screen.getByRole("status")).not.toHaveAttribute("aria-busy");
  });

  it("annonce une erreur aussitôt, avec son texte et son action", () => {
    render(
      <StateMessage kind="error" title="Échec" action={<button type="button">Réessayer</button>}>
        Détail de l'erreur
      </StateMessage>,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Échec");
    expect(alert).toHaveTextContent("Détail de l'erreur");
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeInTheDocument();
  });
});
