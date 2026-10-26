import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ComingSoon from "@/components/ComingSoon";
import Container from "@/components/Container";
import IconButton from "@/components/IconButton";
import PageHeader from "@/components/PageHeader";
import SkipLink from "@/components/SkipLink";
import VisuallyHidden from "@/components/VisuallyHidden";

describe("composants génériques", () => {
  it("PageHeader affiche un h1 focalisable par programme et son introduction", () => {
    render(<PageHeader title="Alertes" intro="Texte d'introduction." />);
    const heading = screen.getByRole("heading", { level: 1, name: "Alertes" });
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(screen.getByText("Texte d'introduction.")).toBeInTheDocument();
  });

  it("SkipLink pointe vers la cible", () => {
    render(<SkipLink targetId="contenu">Aller au contenu</SkipLink>);
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveAttribute(
      "href",
      "#contenu",
    );
  });

  it("IconButton porte un nom accessible et un type bouton", () => {
    render(
      <IconButton label="Ouvrir le menu" className="extra">
        <svg aria-hidden="true" />
      </IconButton>,
    );
    const button = screen.getByRole("button", { name: "Ouvrir le menu" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("extra");
  });

  it("IconButton sans classe supplémentaire reste utilisable", () => {
    render(<IconButton label="Fermer">x</IconButton>);
    expect(screen.getByRole("button", { name: "Fermer" })).toBeInTheDocument();
  });

  it("VisuallyHidden garde le texte dans l'arbre d'accessibilité", () => {
    render(<VisuallyHidden>Texte pour lecteur d'écran</VisuallyHidden>);
    expect(screen.getByText("Texte pour lecteur d'écran")).toBeInTheDocument();
  });

  it("Container et ComingSoon affichent leur contenu", () => {
    render(
      <Container>
        <ComingSoon />
      </Container>,
    );
    expect(screen.getByText("Cette section sera disponible prochainement.")).toBeInTheDocument();
  });
});
