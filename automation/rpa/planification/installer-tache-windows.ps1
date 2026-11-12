<#
.SYNOPSIS
    Planifie le rapport hebdomadaire de Novaria Core dans le Planificateur de tâches de Windows (IA-07).
.DESCRIPTION
    Crée la tâche « Novaria Rapport » : chaque semaine, le jour et à l'heure demandés (lundi 07:00 par défaut), elle lance
    `py -3 scripts\dev\dev.py rpa-report` depuis le dépôt et ajoute la sortie à var\log\rpa-rapport.log. Elle s'exécute avec le
    compte courant, session ouverte (aucun mot de passe n'est stocké dans la tâche). La pile doit tourner (`dev.py up`) et le fichier
    .env contenir NOVARIA_RPA_USER et NOVARIA_RPA_PASSWORD (compte en lecture seule). Un passage manqué (poste éteint) est rattrapé
    au prochain démarrage (StartWhenAvailable). La tâche ne fait rien de plus que la commande à la main ; la supprimer ne touche à
    aucune donnée. Le robot rapporte la semaine ISO précédente en UTC : 07:00 convient aux fuseaux jusqu'à UTC+7.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File automation\rpa\planification\installer-tache-windows.ps1 -Heure 07:00
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File automation\rpa\planification\installer-tache-windows.ps1 -Supprimer
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = '07:00',
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [string]$Jour = 'Monday',
    [switch]$Supprimer
)

$ErrorActionPreference = 'Stop'
$Nom = 'Novaria Rapport'
$Racine = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

if ($Supprimer) {
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false
    Write-Output "Tâche « $Nom » supprimée."
    return
}

New-Item -ItemType Directory -Force -Path (Join-Path $Racine 'var\log') | Out-Null
$Commande = 'py -3 scripts\dev\dev.py rpa-report >> var\log\rpa-rapport.log 2>&1'
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c $Commande" -WorkingDirectory $Racine
$Declencheur = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Jour -At $Heure
$Reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Nom -Action $Action -Trigger $Declencheur -Settings $Reglages `
    -Description 'Rapport hebdomadaire Novaria Core : le robot lit l API et dépose le PDF (IA-07).' -Force | Out-Null
Write-Output "Tâche « $Nom » créée : chaque $Jour à $Heure, depuis $Racine. Test immédiat : Start-ScheduledTask -TaskName '$Nom'"
