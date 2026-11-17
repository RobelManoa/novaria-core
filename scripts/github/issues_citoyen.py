#!/usr/bin/env python3
"""Ajoute au backlog Novaria Core la partie citoyen (jalon M6) et le site de présentation (jalon M7).

Réutilise bootstrap.py : les issues existantes sont ignorées (détection par titre), seules les nouvelles
sont créées. Relançable sans risque. Les jalons « M6 · Intégration de la partie citoyen » et
« M7 · Soutenance » sont définis dans issues_data.MILESTONES.

Usage :
  python scripts/github/issues_citoyen.py --dry-run     # affiche ce qui serait créé
  python scripts/github/issues_citoyen.py --create      # crée les nouvelles issues
Variables facultatives : DADDY_GH et MANOA_GH pour assigner les issues.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import issues_data  # noqa: E402
from issues_data import I  # noqa: E402

NEW_IDS = ["CIT-01", "CIT-02", "CIT-03", "CIT-04", "CIT-05", "CIT-06", "CIT-07", "CIT-08", "SIT-01", "SIT-02", "SIT-03"]

issues_data.ISSUES.extend([
    I("CIT-01", "Décision : périmètre de l'application citoyenne (usager de la ville)", 6, "gestion", "DM", "decision", "P0",
      ["Définir l'usager : un citoyen qui consulte l'état de la circulation et reçoit des alertes (demande C-03)",
       "Fixer le périmètre v1 : lecture seule, état de congestion par tronçon, alertes en cours, sans compte obligatoire",
       "Choisir l'accès : route publique en lecture seule ou rôle `citizen` ; ce que l'usager ne voit jamais (données brutes, capteurs, commandes)",
       "Consigner la décision dans un ADR et mettre à jour le registre des demandes, `parcours.md` et le journal des changements"],
      "Le périmètre, l'accès et les exclusions sont écrits et validés par les deux membres.",
      "docs/01-architecture/adr/ (nouvel ADR) et docs/07-gestion/registre-des-demandes.md", deps=["MS-11"]),
    I("CIT-02", "Contrat d'API citoyen : état de congestion et alertes publiques", 6, "backend", "D", "tache", "P0",
      ["Décrire en OpenAPI les routes en lecture seule : état par tronçon, alertes en cours (champs minimaux, aucune donnée brute)",
       "Ajouter les routes à `gateway/routes.json` (généré) et à `ops/matrice-acces.json` (CLD-18)",
       "Limiter le débit des routes publiques et fixer l'en-tête de cache",
       "Tests de contrat : champs exposés, refus de toute écriture"],
      "Le contrat est versionné, la matrice d'accès le couvre et aucun champ interne n'est exposé.",
      "contracts/ et sortie de `dev.py acces`", bc05=["architectures"], deps=["CIT-01", "MS-13"]),
    I("CIT-03", "API citoyen : implémentation derrière la passerelle", 6, "backend", "D", "tache", "P0",
      ["Implémenter les routes dans le service d'alerte usager (MS-11) ou un service de lecture dédié, selon l'ADR",
       "Lire l'état de congestion à partir des indicateurs existants (pas de nouvelle source)",
       "Anonymat : aucun identifiant de capteur ni donnée personnelle dans les réponses",
       "Métriques `/metrics` et journaux sans valeur de requête"],
      "La passerelle sert l'état et les alertes publiques ; une écriture ou une route interne est refusée.",
      "Tests de l'API et capture de `curl` via la passerelle", deps=["CIT-02"]),
    I("CIT-04", "Application citoyenne : socle mobile, état de la circulation", 6, "frontend", "DM", "tache", "P0",
      ["Application distincte du tableau de bord de l'équipe, pensée pour téléphone (lecture seule, sans graphique)",
       "Vue principale : état de congestion par tronçon (fluide, dense, saturé) lisible en un coup d'œil",
       "Textes en français, contraste et tailles accessibles (WCAG 2.1 AA), état de chargement et d'erreur",
       "Libellé clair : données simulées en v1"],
      "Un citoyen voit l'état de la circulation sur téléphone sans se connecter.",
      "Captures sur écran mobile", deps=["CIT-03"]),
    I("CIT-05", "Application citoyenne : alertes en cours et notifications simulées", 6, "frontend", "DM", "tache", "P1",
      ["Liste des alertes en cours avec tronçon, gravité et heure",
       "Rafraîchissement automatique (ou événements serveur) sans recharger la page",
       "Abonnement à un tronçon : notification simulée (canal fictif, aucun envoi réel) ; consentement affiché",
       "Aucune donnée personnelle collectée en v1"],
      "Une alerte créée par le service apparaît chez le citoyen en moins de 10 secondes.",
      "Capture et test de bout en bout", deps=["CIT-04"]),
    I("CIT-06", "Sécurité de l'accès public : essais d'abus et de refus", 6, "backend", "D", "securite", "P0",
      ["Essais de refus : écriture, route interne, jeton d'équipe sur route publique, dépassement de débit",
       "Vérifier les en-têtes (CORS limité, pas de fuite d'erreur détaillée) et l'absence de secret dans le front",
       "Étendre la matrice d'accès (`dev.py acces`) aux routes citoyen et la rejouer",
       "Scan Snyk et gitleaks verts sur le nouveau code"],
      "La matrice d'accès passe avec les routes citoyen ; aucun abus testé n'aboutit.",
      "Sortie de `dev.py acces` et de la CI", bc05=["architectures"], deps=["CIT-03"]),
    I("CIT-07", "Tests et parcours de bout en bout avec l'usager", 6, "backend", "DM", "test", "P0",
      ["Ajouter le cas usager à `dev.py parcours` : mesure, indicateur, alerte, affichage citoyen",
       "Test du front citoyen (composants et un parcours), sans réseau extérieur",
       "Cas d'échec : service indisponible, message clair côté citoyen",
       "CI verte sur les deux postes (Linux et Windows)"],
      "Le parcours de bout en bout inclut l'usager et passe deux fois de suite.",
      "Sortie de `dev.py parcours` et de la CI", deps=["CIT-05", "CIT-06"]),
    I("CIT-08", "Documentation de la partie citoyen et mise à jour du périmètre", 6, "docs", "M", "tache", "P1",
      ["Mettre à jour `parcours.md`, le dictionnaire de données, les contrats, le guide d'exploitation et le registre des demandes (C-03 réalisée)",
       "Guide de l'usager : ce que l'application montre et ne montre pas, limites de la donnée simulée",
       "Matrice de preuves BC05 : ligne pour la partie citoyen",
       "Consigner l'usage de l'IA dans `docs/ia/journal-usage-ia.md`"],
      "Les documents décrivent ce qui est réellement livré côté citoyen.",
      "docs/02-specifications/parcours.md et docs/07-gestion/registre-des-demandes.md", deps=["CIT-07"]),
    I("SIT-01", "Site de présentation : cadrage, maquette et récit de la soutenance", 7, "docs", "DM", "decision", "P0",
      ["Définir le récit : problème, architecture, démonstration, résultats, limites et honnêteté sur le simulé",
       "Choisir une page unique statique (HTML, CSS, JavaScript), servie en local, sans service tiers ni secret",
       "Maquette des sections : architecture animée, parcours de la donnée, tableau de bord réel, matrice de preuves BC05",
       "Décider des effets visuels (animations, vue 3D légère) sans alourdir la page"],
      "Le plan du site et le récit sont validés par les deux membres.",
      "docs/09-soutenance/site-plan.md", deps=["GES-14"]),
    I("SIT-02", "Site de présentation : construction", 7, "frontend", "DM", "tache", "P0",
      ["Page statique responsive, thème clair et sombre, navigation par sections",
       "Schémas d'architecture animés et parcours de la donnée de la mesure à l'alerte citoyen",
       "Démonstration intégrée : captures ou pile locale pilotée par `dev.py`, avec repli hors ligne",
       "Accessibilité (clavier, contraste), poids de page raisonnable, aucune ressource externe obligatoire"],
      "Le site s'ouvre hors ligne sur les deux postes et déroule toute la soutenance.",
      "site/ et captures", deps=["SIT-01", "CIT-08"]),
    I("SIT-03", "Site de présentation : répétitions, plan B et gel", 7, "gestion", "DM", "tache", "P0",
      ["Deux répétitions chronométrées avec le site, un jeu de captures de secours si la pile ne démarre pas",
       "Vérifier sur le poste de soutenance et sur un second poste ; sauvegarde du site hors du dépôt public si nécessaire",
       "Geler le site avec le code (tag), mention « données simulées » visible",
       "Relecture croisée du discours et du site"],
      "La présentation tient dans le temps imparti avec le site, et le plan B est testé.",
      "Compte rendu des répétitions", deps=["SIT-02", "GES-15"]),
])

import bootstrap  # noqa: E402

if __name__ == "__main__":
    bootstrap.main()
