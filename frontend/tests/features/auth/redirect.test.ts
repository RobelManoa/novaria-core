import { describe, expect, it } from "vitest";
import { redirectTarget } from "@/features/auth/redirect";

describe("redirectTarget", () => {
  it.each([
    ["/alertes", "/alertes"],
    ["/alertes?niveau=critique#haut", "/alertes?niveau=critique#haut"],
    ["/", "/"],
  ])("garde le chemin interne %s", (from, attendu) => {
    expect(redirectTarget({ from })).toBe(attendu);
  });

  it.each([
    ["adresse externe", { from: "https://evil.example" }],
    ["adresse sans protocole", { from: "//evil.example/piege" }],
    ["barre oblique inverse", { from: "/\\evil.example" }],
    ["chemin relatif", { from: "alertes" }],
    ["la page de connexion elle-même", { from: "/connexion" }],
    ["la page de connexion avec paramètres", { from: "/connexion?x=1" }],
    ["valeur qui n'est pas un texte", { from: 42 }],
    ["objet sans from", {}],
    ["état absent", null],
    ["état indéfini", undefined],
    ["état qui n'est pas un objet", "/alertes"],
  ])("renvoie au tableau de bord pour %s", (_cas, state) => {
    expect(redirectTarget(state)).toBe("/");
  });
});
