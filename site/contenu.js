/* Contenu du site de soutenance Novaria Core (SIT-02).
 *
 * Tout ce qui est dit, montré ou chiffré est ici ; la mise en page est dans style.css et le comportement dans app.js.
 * Ce fichier est du JavaScript (et non du JSON) pour que le site s'ouvre aussi par un double-clic sur index.html, sans serveur.
 * Chaque chiffre vient d'un fichier du dépôt, cité dans « preuves ». Une donnée simulée est toujours dite simulée.
 */
window.CONTENU = {
  marque: "NOVARIA CORE",
  titre: "Behind the Intelligence",
  simule: "Données simulées ou historiques (METR-LA, 2012) : jamais présentées comme réelles d'aujourd'hui.",
  signature: [
    "Every interaction tells a story.",
    "Every data point has a purpose.",
    "Behind the intelligence, there is Novaria Core.",
  ],

  /* Les sept parties du film. `secs` : temps prévu à l'oral (total 20:00) ; `longueur` : hauteur de la partie en écrans. */
  scenes: [
    {
      id: "prologue", nav: "Le cadre", secs: 60, longueur: 1.1,
      kicker: "Novaria Core · socle d'UrbanHub",
      chapeau: "Une journée dans la vie d'un citoyen, vue des deux côtés de l'écran : ce qu'il voit, et tout ce qui se passe pour que ce soit vrai.",
      faits: [
        { t: "Local d'abord", d: "tout tourne sur le poste" },
        { t: "Simulé ou réel", d: "toujours dit à l'écran" },
      ],
      orateur: [
        "Qui : deux étudiants du M2 EADL, bloc BC05. Quoi : une plateforme de mobilité urbaine (détection de congestion, alertes, recommandations).",
        "Comment : tout tourne en local avec Docker Compose, sur le poste.",
        "Promesse : ce qui est simulé est dit simulé.",
      ],
      preuves: ["docs/00-cadrage/note-de-cadrage.md", "ADR-023 (exécution locale d'abord)"],
      docs: ["docs/00-cadrage/note-de-cadrage.md"],
      limites: ["Aucune donnée réelle d'aujourd'hui : le simulateur (ville fictive) et METR-LA (Los Angeles, 2012)."],
    },
    {
      id: "citoyen", nav: "Le citoyen", secs: 120, longueur: 2.5,
      kicker: "Scène 1 · Le citoyen",
      titre: "« Est-ce que ça circule ? »",
      chapeau: "Avant de partir, il ouvre « Mes trajets ». Un mot, un conseil, l'heure de la mesure. Libre, Ralenti ou Bloqué : pas de chiffre à interpréter.",
      etiquette: "Données simulées · ville fictive",
      question: "D'où viennent ces informations ?",
      image: { src: "assets/capture-liste.png", alt: "Écran « Mes trajets » de l'application citoyenne : le trajet « Aller à la gare » est bloqué" },
      orateur: [
        "Un usager anonyme ouvre « Mes trajets » : il suit ses trajets, jamais ses déplacements ; rien n'est envoyé.",
        "Trois mots seulement : Libre, Ralenti, Bloqué ; un conseil sans durée promise.",
        "La question qui lance la suite : d'où vient cette information ?",
      ],
      preuves: [
        "docs/08-exploitation/application-citoyenne.md §9",
        "ADR-030 (usager anonyme, lecture seule)",
        "ADR-031 (« Mes trajets », vocabulaire)",
        "Captures : docs/Capture d'ecran/CIT-10-*",
      ],
      docs: ["docs/08-exploitation/application-citoyenne.md#9-version-2---mes-trajets--adr-031-phase-1-21112026", "docs/01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md", "docs/01-architecture/adr/ADR-031-application-citoyenne-v2-mes-trajets.md"],
      limites: [
        "Lecteur d'écran et téléphone réels non essayés.",
        "Critère d'usage (3 personnes, 30 s) non mesuré.",
        "Pas d'itinéraire alternatif ni de durée : l'application n'en promet pas.",
      ],
    },
    {
      id: "capteur", nav: "Le capteur", secs: 120, longueur: 2.6,
      kicker: "Scène 2 · Derrière l'écran",
      titre: "La ville devient un signal.",
      chapeau: "Un capteur ne voit pas la ville : il voit des véhicules passer. De ce passage, il tire une vitesse toutes les cinq minutes.",
      etapes: [
        "Une boucle de fil est noyée dans la chaussée.",
        "Un véhicule qui la traverse change son champ magnétique.",
        "L'armoire au bord de la route compte les passages et mesure le temps d'occupation.",
        "La vitesse moyenne en est déduite, par pas de 5 minutes.",
      ],
      photo: {
        src: "assets/capteur-boucle.jpg",
        alt: "Compteur de trafic à boucles inductives relié à une armoire équipée d'un panneau solaire",
        legende: "Boucles inductives reliées à une armoire avec panneau solaire et modem 3G (compteur MetroCount). Un exemple du principe : ce n'est pas le capteur de METR-LA, dont la fiche ne précise pas le modèle.",
        credit: "Photo : Louis van Senden, CC BY-SA 4.0, via Wikimedia Commons (image non modifiée).",
        lien: "https://commons.wikimedia.org/wiki/File:Inductive_Loop_Traffic_Counter.jpg",
      },
      nomCapteur: "Boucle inductive (inductive loop detector) : c'est ce que la littérature décrit pour METR-LA, sans producteur qui le confirme.",
      mesure: {
        titre: "CAPTEUR / 773869", etat: "● RÉEL",
        lignes: [
          ["HORODATAGE", "2012-05-23 00:00"],
          ["VITESSE", "63,38 mph (102,0 km/h)"],
          ["PAS DE TEMPS", "5 min"],
          ["FLUX · ÉTAT", "non fournis"],
        ],
        pied: "La source ne donne que la vitesse.",
      },
      etiquette: "Réel · Los Angeles · autoroutes · 2012",
      noteVille: "L'application de démonstration montre une ville fictive : le système traite les deux sources de la même façon.",
      carrefour: {
        titre: "Est-ce un carrefour ?",
        cas: {
          mt: {
            nom: "METR-LA",
            chaine: [["capteur 773869", "hi"], ["pas de carrefour", "no"]],
            texte: "METR-LA est un réseau de vitesse : il ne contient que des capteurs sur des autoroutes. Ses mesures vivent dans d'autres tables (speed_network, speed_sensor) qui ne connaissent ni carrefour ni feux. L'application ne cherche donc pas de carrefour pour lui.",
          },
          demo: {
            nom: "Réseau de démonstration",
            chaine: [["SENSOR_001", "hi"], ["ROAD_001 · approche", "hi"], ["INT_01 · carrefour", "hi"]],
            texte: "Chaque mesure du réseau de démonstration porte trois identifiants, vérifiés contre le référentiel. Un tronçon est l'approche d'un carrefour (N, E, S, W) ; le carrefour dit s'il a des feux. C'est ce qui permet le filtre « Carrefour INT_01 » de l'interface d'administration.",
          },
        },
      },
      orateur: [
        "Un capteur voit passer des véhicules : une boucle noyée dans la chaussée, une armoire au bord de la route.",
        "Une mesure METR-LA : un capteur, une heure, une vitesse, toutes les 5 minutes (207 capteurs, Los Angeles, 2012).",
        "Comment l'application sait si c'est un carrefour : chaque mesure du réseau de démonstration porte INT_, ROAD_ et SENSOR_, vérifiés contre le référentiel ; un réseau de vitesse comme METR-LA n'a que des capteurs.",
        "Le label d'entraînement vient de la vérité terrain du simulateur, pas de nos règles.",
      ],
      preuves: [
        "data/datasets/metr-la/PROVENANCE.md (contenu décrit par la littérature, non confirmé par un producteur)",
        "docs/03-donnees/dictionnaire-de-donnees.md (carrefour, tronçon, capteur)",
        "ADR-027 (label = vérité terrain du simulateur)",
        "ADR-032 (réseaux de vitesse, réseau extensible)",
      ],
      docs: ["data/datasets/metr-la/PROVENANCE.md", "docs/03-donnees/dictionnaire-de-donnees.md#4-référentiel-du-réseau-dwhdim", "docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md", "docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md"],
      limites: [
        "Licence de METR-LA non établie : les données restent locales, jamais commitées.",
        "Le modèle exact des capteurs de METR-LA n'est pas connu : la photo montre le principe d'une boucle inductive.",
        "Le réseau à carrefours est fictif (6 carrefours, 24 tronçons).",
      ],
    },
    {
      id: "parcours", nav: "Le parcours", secs: 240, longueur: 3,
      kicker: "Scène 3 · Le parcours de la donnée",
      titre: "Une mesure entre dans Novaria.",
      chapeau: "Cinq composants, dans l'ordre où la donnée les traverse. Clique un composant pour lire ce qu'il fait vraiment.",
      composants: [
        { k: "Collecte", n: "01 / RECEIVE", s: "Réception, validation", p: "Reçoit les mesures du simulateur, contrôle chaque ligne et refuse ce qui est invalide, avec un code de rejet documenté.", l: ["Rejets comptés par motif", "Dictionnaire de données"] },
        { k: "Kafka", n: "02 / STREAM", s: "Transport", p: "Bus d'événements : les services ne s'appellent pas entre eux, ils publient et lisent. Un service qui tombe n'arrête pas les autres.", l: ["Contrats d'événements", "Rejeu après panne"] },
        { k: "Traitement", n: "03 / PROCESS", s: "Nettoyage, états", p: "Agrège en fenêtres de 5 minutes, classe l'état de chaque tronçon avec la règle de seuils, écrit dans l'entrepôt PostgreSQL.", l: ["Règle seuils-v0 (ADR-028)", "Entrepôt dwh"] },
        { k: "Alerte", n: "04 / ALERT", s: "Détection", p: "Confirme une congestion sur deux fenêtres de suite, crée l'alerte et la tient à disposition de l'usager.", l: ["Schéma alertes", "Lecture toutes les 5 s côté usager"] },
        { k: "Réponse", n: "05 / RESPOND", s: "Décision, restitution", p: "Transmet une recommandation de signalisation à l'extérieur et ignore toute recommandation plus ancienne que la dernière reçue.", l: ["Service de réponse extérieure", "Jamais d'ordre périmé"] },
      ],
      ia: {
        bouton: "Où intervient l'IA ?",
        puces: [
          { t: "HORS LIGNE", d: "Entraîner et évaluer sur l'historique : classifieur, prévision, anomalies. Rien de tout cela ne tourne dans le flux.", c: "c12" },
          { t: "RÈGLE DE SEUILS", d: "En service dans le traitement : classe chaque tronçon.", t2: "PRÉVISION DE VITESSE", d2: "Lit l'entrepôt, répond à l'API. Hors alertes.", c: "c3" },
          { t: "GARDE-FOUS", d: "Le modèle ne commande rien · repli sur la règle · dérive des entrées surveillée (PSI) · une fiche dit ce qu'il regarde et ses limites.", c: "c45" },
        ],
        carte: [
          { t: "Où", d: "À deux endroits seulement. Dans le traitement, une règle de seuils classe l'état de chaque tronçon. À côté du flux, un modèle de prévision lit l'entrepôt. Aucun modèle appris ne décide d'une alerte." },
          { t: "Pourquoi", d: "Détecter la congestion d'abord, l'anticiper ensuite. Un modèle appris ne remplace la règle que s'il la bat sur des jours jamais vus : le classifieur testé a été rejeté, la règle reste." },
          { t: "Comment il se comporte", d: "Il apprend l'écart à la persistance : sans information utile, il retombe sur elle. Il ne sert que le réseau sur lequel il a été entraîné, et la fiche du modèle annonce ses limites." },
        ],
      },
      orateur: [
        "Suivre une mesure de bout en bout : collecte, Kafka, traitement, alerte, réponse.",
        "Chaque composant est un service indépendant : il publie et lit sur le bus, il ne s'appelle pas.",
        "Où intervient l'IA : une règle dans le traitement, une prévision à côté, jamais en commande.",
        "Preuve vivante : le flux complet se rejoue en une commande, avec son délai.",
        "Montrer l'Observatoire des pannes : arrêter un service, voir le système réagir.",
      ],
      preuves: [
        "dev.py flux-complet",
        "dev.py parcours (14 cas, dont 5 côté usager)",
        "dev.py citoyen delai : création de l'alerte à l'écran, max 4,1 s sur 6 mesures",
        "dev.py observatoire (pannes, démonstrations)",
        "docs/04-devsecops/tests-integration.md §10",
        "docs/06-ia-mlops/cadrage-ml.md (le modèle ne commande rien, repli sur la règle)",
        "ADR-015, ADR-028 (un modèle appris ne remplace la règle que s'il la bat)",
        "docs/03-donnees/surveillance-derive.md",
      ],
      limites: ["Délais mesurés en local, sur 6 essais.", "Windows non vérifié partout.", "Aucun job de CI pour citizen/."],
    },
    {
      id: "intelligence", nav: "L'intelligence", secs: 390, longueur: 3.6,
      kicker: "Scène 4 · L'intelligence",
      onglets: ["ETL", "Entrepôt", "Règle de seuils", "Classifieur appris", "Prévision"],
      etl: {
        t: "Préparer sans rien perdre",
        d: "Un fichier entre, chaque ligne est contrôlée. Le valide est chargé ; le refusé est compté par motif. Rejouer le même fichier ne change rien.",
        cases: [["Brut", "le fichier tel que reçu"], ["Propre", "lignes valides, clé unique"], ["Rejets", "motif compté, jamais en silence"]],
        note: "Exemple tiré des tests (test_vitesses.py) : 3 lignes chargées ; refusées : capteur inconnu 1, instant mal formé 2, instant non aligné 1, vitesse hors bornes 3, colonnes 1.",
      },
      entrepot: {
        t: "Garder l'historique",
        d: "PostgreSQL 16 (schémas app, dwh, alertes, ops) pour les faits et indicateurs ; MongoDB 7 pour les journaux et statistiques. Un réseau de capteurs s'ajoute par un fichier, sans changer le code.",
        entete: ["Champ", "Exemple (simulé)"],
        lignes: [["road_segment_id", "ROAD_001"], ["window_start", "2026-10-30T07:05:00Z"], ["average_speed_kmh", "18,9"], ["speed_ratio", "0,378"], ["congestion_state", "CONGESTED"]],
      },
      regle: {
        t: "La règle qui tourne vraiment",
        d: "Le rapport vitesse mesurée / vitesse libre décide de l'état. Sous 0,60 : Ralenti. Sous 0,35 : Bloqué. Chaque changement est confirmé sur deux fenêtres.",
        curseur: "Rapport de vitesse",
        etats: { f: "FREE_FLOW (Libre)", s: "SLOW (Ralenti)", c: "CONGESTED (Bloqué)" },
        note: "Règle de seuils : en service (ADR-028). Aucun modèle appris ne la remplace.",
      },
      classifieur: {
        t: "Un classifieur appris, évalué, puis rejeté",
        d: "Régression logistique, confirmation sur 2 fenêtres, jugée sur le test contre la règle de seuils (F1 macro 0,968 ; fausses alertes 0,07).",
        entete: ["Condition", "Modèle", "Exigé", ""],
        conditions: [
          ["A1 F1 macro", "0,9814", "≥ 0,9781", true],
          ["A2 Rappel CONGESTED", "0,9799", "≥ 0,9885", false],
          ["A3 Délai médian", "1 min", "≤ 1 min", true],
          ["A4 Épisodes manqués", "0", "0", true],
          ["A5 Fausses alertes / tronçon / jour", "0,2143", "≤ 0,10", false],
        ],
        verdict: "REJETÉ", verdictTexte: "3 conditions sur 5 remplies : la règle de seuils reste en service.",
      },
      prevision: {
        t: "Prévoir la vitesse : un réseau de neurones à graphe",
        d: "Entraîné sur METR-LA (207 capteurs, 2012), 38 854 poids. Erreur moyenne en mph sur la période de test, plus petit = mieux.",
        series: ["Persistance", "Arbres (HistGradientBoosting)", "Réseau à graphe"],
        horizons: { 5: { mae: [2.784, 2.307, 2.230], gain: "19,9" }, 15: { mae: [3.457, 2.876, 2.702], gain: "21,8" }, 30: { mae: [4.145, 3.337, 3.099], gain: "25,2" } },
        intervalle: "(intervalle à 95 % entièrement sous zéro)",
        note: "Limites dites à l'écran : test lu 3 fois, vitesses seules (ni incident ni météo), servi par l'API et l'admin, pas utilisé pour les alertes.",
      },
      orateur: [
        "ETL : rejouable, les refus sont comptés, jamais perdus.",
        "Entrepôt : PostgreSQL (app, dwh, alertes, ops) et MongoDB pour les journaux.",
        "En service : la règle de seuils. Appris : un classifieur, évalué puis rejeté ; un modèle de prévision, évalué et branché sur l'API.",
        "Dire pourquoi le classifieur est rejeté montre la rigueur autant que le modèle retenu.",
        "Ajouter 100 capteurs ne demande aucun changement de code (test à l'appui).",
      ],
      docs: ["docs/08-exploitation/tests-integration.md", "docs/04-devsecops/tests-integration.md#10-le-parcours-avec-lusager-cit-07-21112026", "docs/06-ia-mlops/cadrage-ml.md", "docs/03-donnees/surveillance-derive.md", "docs/01-architecture/adr/ADR-015-modeles-ia.md", "docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md"],
      preuves: [
        "ml/evaluation/resultats.md (5 conditions d'acceptation)",
        "ml/evaluation/prevision-reseau.md (test, intervalle à 95 %, limites)",
        "ADR-028 (seuils et alertes) · ADR-015 (détection d'abord)",
        "ADR-032 · data/etl/tests/test_vitesses.py (capteurs ajoutés sans code)",
      ],
      docs: ["ml/evaluation/resultats.md", "ml/evaluation/prevision-reseau.md", "docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md", "docs/01-architecture/adr/ADR-015-modeles-ia.md", "docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md"],
      limites: [
        "Classifieur appris : rejeté, jamais en service.",
        "Prévision : test de METR-LA lu 3 fois (pas un test vierge), vitesses seules (ni incident ni météo), non utilisée pour les alertes.",
        "LOF et One-Class SVM non faits.",
      ],
    },
    {
      id: "reponse", nav: "La réponse", secs: 150, longueur: 2.1,
      kicker: "Scène 5 · La réponse",
      titre: "Le système passe à l'action.",
      etapes: [
        ["Congestion confirmée", "Deux fenêtres de suite sous le seuil : ce n'est plus un accident de mesure."],
        ["Alerte créée", "Le service d'alerte l'enregistre et la rend lisible pour l'usager."],
        ["Recommandation de signalisation transmise", "Le service de réponse l'envoie à l'extérieur, sans jamais rien ré-appliquer d'ancien."],
        ["État public mis à jour", "Lecture seule, six champs, rien de brut ni de capteur."],
      ],
      alerte: { kicker: "ALERTE · ÉTAT PUBLIC", titre: "Un trajet est bloqué.", delai: "De la mesure à l'écran : ", valeur: "4,1 s au plus", fin: ", sur 6 mesures en local.", etiquette: "Données simulées" },
      orateur: [
        "Une congestion confirmée devient une alerte, puis une recommandation, puis un état public.",
        "L'accès public est en lecture seule, avec une liste blanche de six champs, des en-têtes de sécurité et une matrice d'accès testée.",
        "Le délai de bout en bout est mesuré, pas promis.",
      ],
      preuves: ["ADR-030 · docs/03-donnees/api-citoyen.md", "docs/04-devsecops/securite-acces-public.md", "dev.py acces (matrice d'accès, essais d'abus)"],
      docs: ["docs/01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md", "docs/03-donnees/api-citoyen.md", "docs/04-devsecops/securite-acces-public.md"],
      limites: ["La notification de l'usager est simulée.", "Le service des feux ignore une recommandation plus ancienne que la dernière reçue."],
    },
    {
      id: "retour", nav: "Le retour", secs: 120, longueur: 1.9,
      kicker: "Scène 6 · Retour au citoyen",
      titre: "Il sait maintenant ce qu'il y a derrière.",
      chapeau: "Même écran, autre regard. Le conseil « attendez ou choisissez un autre trajet » est la fin d'une chaîne qu'il peut maintenant suivre de la rue jusqu'à lui.",
      image: { src: "assets/capture-detail.png", alt: "Détail du trajet « Aller à la gare » : bloqué, avec le conseil partir maintenant ou attendre" },
      orateur: ["On retrouve l'écran du début : même conseil, autre regard.", "Conclusion en trois phrases, puis les questions."],
      preuves: ["Captures de l'application (même dossier que la scène 1)"],
      docs: ["docs/08-exploitation/application-citoyenne.md#9-version-2---mes-trajets--adr-031-phase-1-21112026"],
      limites: [],
    },
  ],

  /* Menu « Questions du jury » : chaque question mène à la partie qui y répond (indice dans `scenes`). */
  jury: [
    { q: "Pourquoi votre classifieur appris est-il rejeté ?", scene: 4, preuve: "ml/evaluation/resultats.md", docs: ["ml/evaluation/resultats.md", "docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md", "docs/01-architecture/adr/ADR-015-modeles-ia.md"] },
    { q: "Où intervient l'IA dans le flux ?", scene: 3, preuve: "docs/06-ia-mlops/cadrage-ml.md, ADR-028", docs: ["docs/06-ia-mlops/cadrage-ml.md", "docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md", "docs/01-architecture/adr/ADR-015-modeles-ia.md", "docs/03-donnees/surveillance-derive.md"] },
    { q: "Mesurez-vous un gain réel de la prévision ?", scene: 4, preuve: "ml/evaluation/prevision-reseau.md", docs: ["ml/evaluation/prevision-reseau.md", "docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md"] },
    { q: "Vos données sont-elles réelles ?", scene: 2, preuve: "ADR-027, ADR-032, PROVENANCE.md", docs: ["docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md", "docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md", "data/datasets/metr-la/PROVENANCE.md"] },
    { q: "Comment sait-on qu'un capteur est sur un carrefour ?", scene: 2, preuve: "dictionnaire de données", docs: ["docs/03-donnees/dictionnaire-de-donnees.md#4-référentiel-du-réseau-dwhdim", "docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md"] },
    { q: "Combien de temps entre la mesure et l'écran ?", scene: 3, preuve: "dev.py citoyen delai", docs: ["docs/08-exploitation/application-citoyenne.md#83-preuve--délai-mesuré-de-bout-en-bout", "docs/04-devsecops/tests-integration.md#10-le-parcours-avec-lusager-cit-07-21112026"] },
    { q: "Que se passe-t-il si un service tombe ?", scene: 3, preuve: "dev.py observatoire", docs: ["docs/08-exploitation/tests-integration.md", "docs/04-devsecops/tests-integration.md"] },
    { q: "Comment ajouter 100 capteurs ?", scene: 4, preuve: "ADR-032, data/etl/tests/test_vitesses.py", docs: ["docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md", "docs/03-donnees/dictionnaire-de-donnees.md#4-référentiel-du-réseau-dwhdim"] },
  ],

  /* Démonstration : captures de secours (la pile locale se lance à côté). */
  demo: {
    titre: "Démonstration",
    chapeau: "Les captures ci-dessous sont le plan B si la pile locale ne démarre pas. Elles montrent des données simulées.",
    captures: [
      { id: "liste", nom: "Application : Mes trajets", src: "assets/capture-liste.png", alt: "Application citoyenne, liste des trajets", legende: "Un trajet bloqué, avec le conseil et l'heure de la mesure." },
      { id: "detail", nom: "Application : détail", src: "assets/capture-detail.png", alt: "Application citoyenne, détail d'un trajet", legende: "Partir maintenant ou attendre, sans durée promise." },
      { id: "tdb", nom: "Interface d'administration", src: "assets/capture-tableau-de-bord.png", alt: "Tableau de bord d'administration : indicateurs, évolution, état des tronçons", legende: "Tableau de bord sur la période simulée « demo-fe04 » : 24 tronçons, 288 indicateurs." },
    ],
    pile: {
      titre: "Lancer la pile locale",
      lignes: [
        ["Vérifier le poste", "python3 scripts/dev/dev.py check-tools", "py -3 scripts/dev/dev.py check-tools"],
        ["Démarrer la pile", "python3 scripts/dev/dev.py up", "py -3 scripts/dev/dev.py up"],
        ["Rejouer le flux complet", "python3 scripts/dev/dev.py flux-complet", "py -3 scripts/dev/dev.py flux-complet"],
        ["Application citoyenne", "python3 scripts/dev/dev.py citoyen dev", "py -3 scripts/dev/dev.py citoyen dev"],
        ["Observatoire des pannes", "python3 scripts/dev/dev.py observatoire", "py -3 scripts/dev/dev.py observatoire"],
      ],
    },
  },

  /* Matrice de preuves BC05 (note de cadrage, section 3). */
  matrice: {
    titre: "Compétences BC05 et preuves",
    chapeau: "Neuf compétences, un niveau annoncé et une preuve pour chacune. « Implémenté » : fonctionnalité complète, intégrée et testée. « Prototype ciblé » : réalisation limitée, dont le rapport dit ce qu'elle démontre et ce qu'elle ne démontre pas.",
    entete: ["Compétence", "Niveau", "Preuve", "Issues"],
    lignes: [
      ["Architectures de données décisionnelles", "Implémenté", "Entrepôt en étoile PostgreSQL, diagrammes C4", "DAT-02, DAT-05, DOC-03", ["docs/03-donnees/entrepot.md"]],
      ["Processus ETL et intégration de données", "Implémenté", "Scripts d'ingestion, de nettoyage et de chargement", "DAT-03 à DAT-06", ["docs/03-donnees/ingestion-paris.md", "docs/03-donnees/rapport-rejeu-etl.md"]],
      ["Processus décisionnels et modèles de données", "Implémenté", "Indicateurs, requêtes SQL, endpoints, dashboard", "DAT-07, BE-04, FE-04", ["docs/03-donnees/tableau-de-bord.md"]],
      ["Machine Learning et modélisation", "Implémenté", "Cadrage du cas d'usage, préparation, évaluation", "IA-01 à IA-03, FE-05", ["docs/06-ia-mlops/cadrage-ml.md", "ml/evaluation/resultats.md"]],
      ["Pipelines MLOps", "Implémenté", "Registre de modèles, pipeline d'entraînement, surveillance de dérive", "IA-04 à IA-06", ["docs/06-ia-mlops/fiche-modele.md", "docs/03-donnees/surveillance-derive.md"]],
      ["Documentation et spécifications techniques", "Implémenté", "Spécifications, contrat OpenAPI, ADR", "DOC-05, DOC-07, DOC-08"],
      ["Big Data et traitement massif (Hadoop, Spark)", "Prototype ciblé", "Prototype Spark et son rapport", "DAT-08"],
      ["Traitement de flux en temps réel (Kafka, Flink)", "Prototype ciblé", "Prototype Kafka et Flink et son rapport", "DAT-09", ["docs/08-exploitation/kafka-local.md"]],
      ["RPA (automatisation des tâches)", "Prototype ciblé", "Robot dans automation/rpa/", "IA-07, FE-06", ["automation/rpa/README.md"]],
    ],
    pied: "Source : docs/00-cadrage/note-de-cadrage.md, section 3.",
  },
};
