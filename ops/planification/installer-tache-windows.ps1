<#
.SYNOPSIS
    Planifie la sauvegarde de Novaria Core dans le Planificateur de tâches de Windows (CLD-15).
.DESCRIPTION
    Crée deux tâches : « Novaria Sauvegarde » (chaque jour à l'heure demandée : sauvegarde des deux bases, manifeste, conservation
    par paliers) et « Novaria Restauration de controle » (chaque dimanche : restauration dans l'environnement isolé et comparaison
    des totaux). Elles lancent `py -3 scripts\dev\dev.py sauvegarde` et `restauration` depuis le dépôt et ajoutent la sortie à
    var\log\. Elles s'exécutent avec le compte courant, session ouverte (aucun mot de passe n'est stocké). Docker Desktop doit
    tourner et `dev.py db-up` avoir été lancé. Supprimer les tâches ne touche à aucune donnée ni à aucune sauvegarde.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops\planification\installer-tache-windows.ps1 -Heure 02:00
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops\planification\installer-tache-windows.ps1 -Supprimer
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = '02:00',
    [switch]$Supprimer
)

$ErrorActionPreference = 'Stop'
$Nom = 'Novaria Sauvegarde'
$NomControle = 'Novaria Restauration de controle'
$Racine = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if ($Supprimer) {
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false
    Unregister-ScheduledTask -TaskName $NomControle -Confirm:$false
    Write-Output "Tâches « $Nom » et « $NomControle » supprimées."
    return
}

New-Item -ItemType Directory -Force -Path (Join-Path $Racine 'var\log') | Out-Null
$Reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

$Sauvegarde = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c py -3 scripts\dev\dev.py sauvegarde >> var\log\sauvegarde.log 2>&1' -WorkingDirectory $Racine
Register-ScheduledTask -TaskName $Nom -Action $Sauvegarde -Trigger (New-ScheduledTaskTrigger -Daily -At $Heure) -Settings $Reglages `
    -Description 'Sauvegarde Novaria Core : PostgreSQL et MongoDB, manifeste, conservation par paliers (CLD-15).' -Force | Out-Null

$Controle = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c py -3 scripts\dev\dev.py restauration >> var\log\restauration.log 2>&1' -WorkingDirectory $Racine
Register-ScheduledTask -TaskName $NomControle -Action $Controle -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '03:00') -Settings $Reglages `
    -Description 'Restauration de contrôle dans un environnement isolé, comparaison des totaux (CLD-15).' -Force | Out-Null

Write-Output "Tâches créées : « $Nom » chaque jour à $Heure, « $NomControle » chaque dimanche à 03:00, depuis $Racine. Test immédiat : Start-ScheduledTask -TaskName '$Nom'"
