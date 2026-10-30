<#
.SYNOPSIS
    Planifie le lot ETL de Novaria Core dans le Planificateur de tâches de Windows (DAT-06).
.DESCRIPTION
    Crée la tâche « Novaria ETL » : chaque jour à l'heure demandée, elle lance `py -3 scripts\dev\dev.py etl-lot` depuis le
    dépôt et ajoute la sortie à var\log\etl-lot.log. Elle s'exécute avec le compte courant, session ouverte (aucun mot de passe
    n'est stocké). Docker Desktop doit tourner et `dev.py db-up` avoir été lancé : le lot a besoin de PostgreSQL et de MongoDB.
    La tâche ne fait rien de plus que la commande à la main ; la supprimer ne touche à aucune donnée.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File data\etl\planification\installer-tache-windows.ps1 -Heure 02:30
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File data\etl\planification\installer-tache-windows.ps1 -Supprimer
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = '02:30',
    [switch]$Supprimer
)

$ErrorActionPreference = 'Stop'
$Nom = 'Novaria ETL'
$Racine = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

if ($Supprimer) {
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false
    Write-Output "Tâche « $Nom » supprimée."
    return
}

New-Item -ItemType Directory -Force -Path (Join-Path $Racine 'var\log') | Out-Null
$Commande = 'py -3 scripts\dev\dev.py etl-lot >> var\log\etl-lot.log 2>&1'
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c $Commande" -WorkingDirectory $Racine
$Declencheur = New-ScheduledTaskTrigger -Daily -At $Heure
$Reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Nom -Action $Action -Trigger $Declencheur -Settings $Reglages `
    -Description 'Lot ETL Novaria Core : ingestion et nettoyage de Paris, chargement des fenêtres (DAT-06).' -Force | Out-Null
Write-Output "Tâche « $Nom » créée : chaque jour à $Heure, depuis $Racine. Test immédiat : Start-ScheduledTask -TaskName '$Nom'"
