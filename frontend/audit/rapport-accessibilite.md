# Rapport d'audit d'accessibilité (FE-07, EXG-NFR-15)

**Verdict : aucune erreur bloquante.**

Généré par `frontend/scripts/audit-a11y.mjs` le 2026-11-12. Ce fichier est écrasé à chaque exécution : ne pas le modifier à la main.

## Méthode

- Outil : **axe-core 4.10.3**, règles WCAG 2.0, 2.1 et 2.2 de niveaux A et AA, plus les bonnes pratiques d'axe.
- Navigateur : 157.0.4341.46 (Edge), piloté par playwright-core 1.52.0. Le contraste est mesuré sur le rendu réel (couleurs calculées, fond réel), pas sur la feuille de style.
- Application : version construite (`npm run build`) servie par `vite preview` ; API simulée par le script (aucun service lancé), session factice pour les pages protégées.
- Étendue : 44 écrans mesurés = 7 pages × thèmes clair et sombre × ordinateur (1280 px) et mobile (375 px), la largeur de 320 px (reflux), les états d'erreur, les identifiants refusés, le filtre « toutes les alertes » et le tiroir de navigation ouvert.
- Critère : **bloquant** = toute violation rangée par axe sous une étiquette WCAG A ou AA, quelle que soit sa gravité. Les bonnes pratiques hors WCAG sont des avertissements. Les contrôles manuels dont axe ne sait pas conclure (« à vérifier ») sont listés plus bas.

## Résultat

| Contrôle | Résultat |
|---|---|
| Violations WCAG A/AA (axe-core) | **0** sur 44 écrans |
| Bonnes pratiques d'axe (avertissements) | 0 |
| Scénarios clavier | 34 réussis sur 34 |
| Textes en anglais repérés | 0 |
| Défilement horizontal à 320 px (WCAG 1.4.10) | 0 page(s) sur 7 |

## Scénarios clavier

| Scénario | Résultat | Détail |
|---|---|---|
| ordinateur : le premier Tab atteint le lien « Aller au contenu » | réussi | {"tag":"a","name":"Aller au contenu","visibleIndicator":true,"onScreen":true,"id":null} |
| ordinateur : Entrée sur le lien d'évitement place le focus sur le contenu principal | réussi | focus sur « contenu » |
| ordinateur : 15 arrêts de tabulation sur le tableau de bord, tous nommés | réussi | Aller au contenu → Novaria Core → Clair → Se déconnecter → Tableau de bord → Alertes → Feux de circulation → Prévisions → Rapports → PériodeDernière heure6 dernières heures24 dernières heures → Taille des fenêtres1 minute5 minutes → ZoneTout le réseauCarrefour INT_01Carrefour INT_02Carrefour INT_03C |
| ordinateur : chaque arrêt de tabulation a un indicateur de focus visible | réussi |  |
| ordinateur : aucun arrêt de tabulation n'est hors de l'écran | réussi |  |
| mobile : le premier Tab atteint le lien « Aller au contenu » | réussi | {"tag":"a","name":"Aller au contenu","visibleIndicator":true,"onScreen":true,"id":null} |
| mobile : Entrée sur le lien d'évitement place le focus sur le contenu principal | réussi | focus sur « contenu » |
| mobile : 11 arrêts de tabulation sur le tableau de bord, tous nommés | réussi | Aller au contenu → Ouvrir le menu → Novaria Core → Clair → Se déconnecter → PériodeDernière heure6 dernières heures24 dernières heures → Taille des fenêtres1 minute5 minutes → ZoneTout le réseauCarrefour INT_01Carrefour INT_02Carrefour INT_03Carrefour INT_04Carrefour INT_05Carrefour INT_06 → Voir le |
| mobile : chaque arrêt de tabulation a un indicateur de focus visible | réussi |  |
| mobile : aucun arrêt de tabulation n'est hors de l'écran | réussi |  |
| mobile : ouvrir le menu au clavier place le focus dans la navigation | réussi | focus dans « Navigation principale » |
| mobile : douze Tab de suite restent dans le tiroir (focus piégé) | réussi |  |
| mobile : douze Maj+Tab de suite restent dans le tiroir | réussi |  |
| mobile : Échap ferme le tiroir et rend le focus au bouton de menu | réussi | focus sur « Ouvrir le menu » |
| mobile : le tiroir fermé n'est plus atteignable (inert) | réussi |  |
| ordinateur : après un changement de page, le focus est sur le titre (h1) de la nouvelle page | réussi | {"tag":"H1","text":"Alertes","title":"Alertes · Novaria Core"} |
| ordinateur : le titre du document change avec la page | réussi | Alertes · Novaria Core |
| ordinateur : le formulaire de connexion s'envoie avec Entrée et l'erreur est annoncée (role=alert, en français) | réussi | Identifiant ou mot de passe incorrect. |
| ordinateur : texte à 200 % sans défilement horizontal de la page (1.4.4) | réussi | débordement de 0 px |
| ordinateur : le premier Tab atteint le lien « Aller au contenu » [mouvement réduit] | réussi | {"tag":"a","name":"Aller au contenu","visibleIndicator":true,"onScreen":true,"id":null} |
| ordinateur : Entrée sur le lien d'évitement place le focus sur le contenu principal [mouvement réduit] | réussi | focus sur « contenu » |
| ordinateur : 15 arrêts de tabulation sur le tableau de bord, tous nommés [mouvement réduit] | réussi | Aller au contenu → Novaria Core → Clair → Se déconnecter → Tableau de bord → Alertes → Feux de circulation → Prévisions → Rapports → PériodeDernière heure6 dernières heures24 dernières heures → Taille des fenêtres1 minute5 minutes → ZoneTout le réseauCarrefour INT_01Carrefour INT_02Carrefour INT_03C |
| ordinateur : chaque arrêt de tabulation a un indicateur de focus visible [mouvement réduit] | réussi |  |
| ordinateur : aucun arrêt de tabulation n'est hors de l'écran [mouvement réduit] | réussi |  |
| mobile : le premier Tab atteint le lien « Aller au contenu » [mouvement réduit] | réussi | {"tag":"a","name":"Aller au contenu","visibleIndicator":true,"onScreen":true,"id":null} |
| mobile : Entrée sur le lien d'évitement place le focus sur le contenu principal [mouvement réduit] | réussi | focus sur « contenu » |
| mobile : 11 arrêts de tabulation sur le tableau de bord, tous nommés [mouvement réduit] | réussi | Aller au contenu → Ouvrir le menu → Novaria Core → Clair → Se déconnecter → PériodeDernière heure6 dernières heures24 dernières heures → Taille des fenêtres1 minute5 minutes → ZoneTout le réseauCarrefour INT_01Carrefour INT_02Carrefour INT_03Carrefour INT_04Carrefour INT_05Carrefour INT_06 → Voir le |
| mobile : chaque arrêt de tabulation a un indicateur de focus visible [mouvement réduit] | réussi |  |
| mobile : aucun arrêt de tabulation n'est hors de l'écran [mouvement réduit] | réussi |  |
| mobile : ouvrir le menu au clavier place le focus dans la navigation [mouvement réduit] | réussi | focus dans « Navigation principale » |
| mobile : douze Tab de suite restent dans le tiroir (focus piégé) [mouvement réduit] | réussi |  |
| mobile : douze Maj+Tab de suite restent dans le tiroir [mouvement réduit] | réussi |  |
| mobile : Échap ferme le tiroir et rend le focus au bouton de menu [mouvement réduit] | réussi | focus sur « Ouvrir le menu » |
| mobile : le tiroir fermé n'est plus atteignable (inert) [mouvement réduit] | réussi |  |

## Écrans mesurés

| Écran | Violations WCAG | Avertissements | Défilement horizontal | `lang` | Titre |
|---|---|---|---|---|---|
| connexion · clair · ordinateur | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| connexion · clair · mobile | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| connexion · sombre · ordinateur | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| connexion · sombre · mobile | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| connexion · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| tableau-de-bord · clair · ordinateur | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tableau-de-bord · clair · mobile | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tableau-de-bord · sombre · ordinateur | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tableau-de-bord · sombre · mobile | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tableau-de-bord · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| alertes · clair · ordinateur | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| alertes · clair · mobile | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| alertes · sombre · ordinateur | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| alertes · sombre · mobile | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| alertes · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| feux · clair · ordinateur | 0 | 0 | aucun | fr | Feux de circulation · Novaria Core |
| feux · clair · mobile | 0 | 0 | aucun | fr | Feux de circulation · Novaria Core |
| feux · sombre · ordinateur | 0 | 0 | aucun | fr | Feux de circulation · Novaria Core |
| feux · sombre · mobile | 0 | 0 | aucun | fr | Feux de circulation · Novaria Core |
| feux · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Feux de circulation · Novaria Core |
| previsions · clair · ordinateur | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| previsions · clair · mobile | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| previsions · sombre · ordinateur | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| previsions · sombre · mobile | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| previsions · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| rapports · clair · ordinateur | 0 | 0 | aucun | fr | Rapports · Novaria Core |
| rapports · clair · mobile | 0 | 0 | aucun | fr | Rapports · Novaria Core |
| rapports · sombre · ordinateur | 0 | 0 | aucun | fr | Rapports · Novaria Core |
| rapports · sombre · mobile | 0 | 0 | aucun | fr | Rapports · Novaria Core |
| rapports · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Rapports · Novaria Core |
| page-introuvable · clair · ordinateur | 0 | 0 | aucun | fr | Page introuvable · Novaria Core |
| page-introuvable · clair · mobile | 0 | 0 | aucun | fr | Page introuvable · Novaria Core |
| page-introuvable · sombre · ordinateur | 0 | 0 | aucun | fr | Page introuvable · Novaria Core |
| page-introuvable · sombre · mobile | 0 | 0 | aucun | fr | Page introuvable · Novaria Core |
| page-introuvable · clair · 320 px (reflux) | 0 | 0 | aucun | fr | Page introuvable · Novaria Core |
| connexion · identifiants refusés · clair · ordinateur | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| connexion · identifiants refusés · sombre · mobile | 0 | 0 | aucun | fr | Connexion · Novaria Core |
| tableau-de-bord · erreur du serveur · clair · ordinateur | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tableau-de-bord · erreur du serveur · sombre · ordinateur | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| previsions · service absent · clair · ordinateur | 0 | 0 | aucun | fr | Prévisions · Novaria Core |
| alertes · toutes les alertes · clair · ordinateur | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| alertes · toutes les alertes · sombre · ordinateur | 0 | 0 | aucun | fr | Alertes · Novaria Core |
| tiroir de navigation ouvert · clair · mobile | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |
| tiroir de navigation ouvert · sombre · mobile | 0 | 0 | aucun | fr | Tableau de bord · Novaria Core |

## Contrôles que l'outil ne sait pas conclure (« à vérifier »)

| Règle | Éléments (cumul) | Écrans | Traitement |
|---|---|---|---|
| color-contrast — Elements must meet minimum color contrast ratio thresholds | 125 | 10 | texte des graphiques SVG, que axe ne sait pas mesurer : contraste calculé par le script sur chacun (157 textes mesurés sur l'ensemble des écrans, seuil 4,5:1) |
| skip-link — The skip-link target should exist and be focusable | 2 | 2 | lien d'évitement masqué jusqu'au focus : couvert par les scénarios clavier (visible au premier Tab, mène au contenu) |

## Limites

- Un outil automatique ne détecte qu'une partie des défauts d'accessibilité (de l'ordre de 30 à 40 %). Les scénarios clavier et le contrôle du français complètent l'audit ; **aucun essai avec un lecteur d'écran (NVDA, VoiceOver) n'a été fait** : les noms, rôles et annonces sont vérifiés par axe et par les tests, pas écoutés.
- Les données sont simulées. Un contenu venant du serveur (messages, libellés d'une autre langue) n'est pas couvert.
- Navigateur unique (celui indiqué plus haut) ; Firefox et Safari ne sont pas mesurés.
- Les graphiques SVG sont mesurés comme le reste, mais leur lisibilité pour une personne aveugle repose sur le tableau de données qui les accompagne, dont l'équivalence n'est pas vérifiée automatiquement.

