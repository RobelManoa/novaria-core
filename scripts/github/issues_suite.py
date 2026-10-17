#!/usr/bin/env python3
"""Ajoute au backlog Novaria Core les 7 issues apparues pendant la mise en route de la CI.

Réutilise bootstrap.py : les 77 issues existantes sont détectées (par titre) et ignorées,
seules les nouvelles sont créées. Relançable sans risque.

Usage :
  python scripts/github/issues_suite.py --dry-run     # affiche ce qui serait créé
  python scripts/github/issues_suite.py --create      # crée les nouvelles issues
Variables facultatives : DADDY_GH et MANOA_GH pour assigner les issues.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import issues_data  # noqa: E402
from issues_data import I  # noqa: E402

issues_data.ISSUES.extend([
    I("GES-18", "Décision : ouverture du compte AWS, plafond de dépenses et plan B", 1, "gestion", "DM", "decision", "P0",
      ["Choisir qui ouvre le compte AWS et avec quel moyen de paiement ; date limite : 24/10/2026",
       "Activer l'authentification à deux facteurs sur le compte racine et un budget d'alerte avant toute ressource",
       "Si le compte n'est pas ouvert à la date limite : plan B documenté (démonstration locale avec `make up`, Terraform écrit et validé avec `terraform plan`, sans déploiement)",
       "Consigner la décision dans un ADR"],
      "La décision, la date limite et le plan B sont écrits ; sans compte AWS, les issues cloud sont replanifiées.",
      "docs/01-architecture/adr/ADR-007-compte-aws.md", deps=["CLD-01"]),
    I("GES-17", "Règles de travail à deux : revues, délais et répartition de la charge", 1, "gestion", "DM", "decision", "P0",
      ["Convenir du délai de relecture d'une pull request (proposition : 24 h ouvrées) et du moyen de se prévenir",
       "Fixer qui relit quoi (CODEOWNERS) et comment se répartissent les issues sans propriétaire",
       "Point de synchronisation hebdomadaire de 20 minutes : jalon, blocages, semaine suivante",
       "Rééquilibrer la charge : les 12 issues du jalon M2 reposent toutes sur Daddy (par exemple BE-05, BE-06 et BE-08 vers Manoa)"],
      "Les règles tiennent dans une page de CONTRIBUTING.md et les deux membres les ont validées.",
      "CONTRIBUTING.md", deps=["GES-02"]),
    I("CLD-22", "Dependabot : mises à jour mensuelles groupées et secrets dédiés", 1, "cloud", "M", "securite", "P1",
      ["Remplacer `.github/dependabot.yml` : mensuel, groupes minor et patch, versions majeures ignorées",
       "Ajouter SNYK_TOKEN et SONAR_TOKEN comme secrets Dependabot (`gh secret set NOM --app dependabot`)",
       "Fermer les pull requests Dependabot qui ne respectent plus la règle",
       "Fusionner les pull requests groupées une fois vertes et relues"],
      "Quelques pull requests Dependabot au plus sont ouvertes, toutes avec les 6 contrôles verts.",
      "Capture de la liste des pull requests Dependabot", deps=["CLD-06"]),
    I("CLD-23", "Politique de vulnérabilités : correctifs, exceptions datées et scan hebdomadaire", 1, "cloud", "M", "securite", "P1",
      ["Documenter dans `docs/04-devsecops/exceptions.md` : délai de correction, qui décide d'une exception, durée maximale (expiration avant le 10/12/2026)",
       "Ajouter un déclencheur `schedule` hebdomadaire à `ci.yml` pour détecter les nouvelles failles des images de base",
       "Noter dans le registre des risques toute faille sans correctif"],
      "Toute exception de `.snyk` a une raison, une expiration et une entrée dans le registre ; un scan planifié tourne chaque semaine sur `main`.",
      "docs/04-devsecops/exceptions.md", deps=["CLD-05"]),
    I("CLD-24", "Nettoyer les doublons de CI et remplacer les identifiants fictifs", 1, "cloud", "M", "tache", "P1",
      ["Supprimer le workflow « Build » créé par l'assistant SonarQube Cloud (doublon du job `sonarqube`) après vérification",
       "Dans SonarQube Cloud : méthode d'analyse = GitHub Actions, analyse automatique désactivée",
       "Remplacer les identifiants fictifs de `.github/CODEOWNERS` et de `sonar-project.properties`",
       "Versionner `frontend/package-lock.json` s'il manque"],
      "Un seul workflow de CI s'exécute par pull request et CODEOWNERS désigne les vrais comptes.",
      "Capture de l'onglet Actions", deps=["CLD-04"]),
    I("GES-16", "Inventaire des secrets, authentification à deux facteurs et renouvellements", 1, "gestion", "DM", "securite", "P1",
      ["Lister dans `docs/04-devsecops/secrets.md` chaque jeton : usage, lieu de stockage, expiration (jeton Snyk : mi-janvier 2027), sans jamais écrire la valeur",
       "Vérifier qu'aucun jeton n'est resté hors des secrets GitHub (conversation, capture, fichier) et révoquer tout jeton exposé",
       "Activer l'authentification à deux facteurs sur GitHub, Snyk, SonarQube Cloud et AWS"],
      "Chaque secret a un propriétaire et une date de renouvellement ; la double authentification est active partout.",
      "docs/04-devsecops/secrets.md", deps=["CLD-01"]),
    I("DOC-10", "Corriger la diapositive d'architecture du plan d'action v4 (MongoDB, pas DynamoDB)", 1, "docs", "M", "tache", "P2",
      ["Remplacer la mention d'Amazon DynamoDB par MongoDB pour les journaux et les statistiques",
       "Vérifier la cohérence avec ADR-002 et le schéma C4"],
      "La présentation et les ADR citent la même base non relationnelle.",
      "Présentation mise à jour", deps=["DOC-04"]),
])

import bootstrap  # noqa: E402

if __name__ == "__main__":
    bootstrap.main()
