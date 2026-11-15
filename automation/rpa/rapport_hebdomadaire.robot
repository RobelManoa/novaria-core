*** Settings ***
Documentation     Rapport hebdomadaire (IA-07, ADR-019). Le robot lit l'API en lecture seule, assemble le PDF
...               et le dépose ; la page « Rapports » du front-end l'affiche (FE-06). Il ne commande aucun équipement.
...               Le compte de service vient de NOVARIA_RPA_USER et NOVARIA_RPA_PASSWORD (environnement).
Library           NovariaRapport.py
Library           OperatingSystem
Test Teardown     Notifier un échec

*** Variables ***
${API}            http://127.0.0.1:8000
${DOSSIER}        var/reports
${DEBUT}          ${EMPTY}
${FIN}            ${EMPTY}

*** Test Cases ***
Produire le rapport hebdomadaire
    [Documentation]    Un rapport est produit sans intervention manuelle ; relancer la même semaine le remplace.
    ${periode}=       Choisir la période    ${DEBUT}    ${FIN}
    Se connecter      ${API}
    ${donnees}=       Lire les indicateurs    ${API}    ${periode}
    ${resume}=        Résumer    ${donnees}    ${periode}
    ${pdf}=           Assembler le rapport    ${resume}
    ${depot}=         Déposer le rapport    ${DOSSIER}    ${periode}    ${resume}    ${pdf}
    Notifier          ${DOSSIER}    INFO    Rapport déposé : ${depot.metadonnees['file_name']}
    File Should Exist    ${depot.chemin_pdf}
    File Should Exist    ${depot.chemin_metadonnees}

*** Keywords ***
Notifier un échec
    Run Keyword If Test Failed    Notifier    ${DOSSIER}    ERREUR    Rapport non produit : ${TEST MESSAGE}
