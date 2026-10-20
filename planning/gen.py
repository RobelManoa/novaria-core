import datetime as dt
import os
import sys
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as m  # noqa: E402

NS = "http://schemas.microsoft.com/project"
ET.register_namespace("", NS)
def E(parent, tag, text=None):
    e = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        e.text = str(text)
    return e

ISS, PLAN, DONE = m.ISS, m.PLAN, dict(m.DONE)
cpm, done_end = m.cpm()
# créneaux [début, fin) pour chaque tâche
slots = {}
t = 0
for tid, d in m.DONE:
    slots[tid] = (t, t + int(d * 2)); t += int(d * 2)
slots.update(cpm)
fmt = lambda x: x.strftime("%Y-%m-%dT%H:%M:%S")
hrs = lambda days: f"PT{int(round(days*8))}H0M0S"
TEAMS = [("gestion", "Gestion de projet"), ("docs", "Documentation"), ("cloud", "Cloud et DevSecOps"),
         ("data", "Données"), ("backend", "Back-end et microservices"), ("frontend", "Front-end"),
         ("ia", "IA et automatisation")]
PRIO = {"P0": 800, "P1": 500, "P2": 300}
OWN = {"D": "Daddy Luciano", "M": "Manoa Robel", "DM": "les deux (50 % chacun)"}
dur_of = lambda k: (DONE[k] if k in DONE else PLAN[k][0])
preds_of = lambda k: [] if k in DONE else PLAN[k][1]
MSN = [x[0] for x in m.issues_data.MILESTONES]
MSD = [x[1] for x in m.issues_data.MILESTONES]

# ---- UID et numéros
rows = []   # (kind, key, level, wbs)
uid = {}
nxt = 1
def new(key):
    global nxt
    uid[key] = nxt; nxt += 1
    return uid[key]
rows.append(("sum", "JALONS", 1, "1")); new("JALONS")
for i in range(7):
    rows.append(("ms", f"M{i}", 2, f"1.{i+1}")); new(f"M{i}")
for ti, (tk, tn) in enumerate(TEAMS):
    w = f"{ti+2}"
    rows.append(("team", tk, 1, w)); new("T:" + tk)
    ks = [k for k in list(DONE) + list(PLAN) if ISS[k]["team"] == tk]
    ks.sort(key=lambda k: (ISS[k]["ms"], (list(DONE) + list(PLAN)).index(k)))
    for j, k in enumerate(ks):
        rows.append(("task", k, 2, f"{w}.{j+1}")); new(k)

def real_preds(k):
    return preds_of(k)

# ---- dates
start_of = lambda k: m.slot_start(slots[k][0])
end_of = lambda k: m.slot_end(slots[k][1] - 1)
ms_members = {i: [k for k in list(DONE) + list(PLAN) if ISS[k]["ms"] == i] for i in range(7)}
ms_members[6] = ["GES-14", "GES-15"]
ms_when = {}
for i in range(7):
    ms_when[i] = max(end_of(k) for k in ms_members[i])
ms_when[6] = max(ms_when[6], dt.datetime(2026, 12, 10, 8))

root = ET.Element(f"{{{NS}}}Project")
E(root, "SaveVersion", 12)
E(root, "Name", "Novaria Core - Plan DevSecOps BC05")
E(root, "Title", "Novaria Core : plan DevSecOps par équipe (socle d'UrbanHub, BC05)")
E(root, "Subject", "Planning du projet du 12/10/2026 à la soutenance du 10/12/2026")
E(root, "Author", "Manoa Robel et Daddy Luciano")
E(root, "CreationDate", "2026-10-17T18:30:00")
E(root, "ScheduleFromStart", 1)
E(root, "StartDate", "2026-10-12T08:00:00")
fin_all = max(end_of(k) for k in slots if k in PLAN or k in DONE)
E(root, "FinishDate", fmt(max(fin_all, ms_when[6])))
E(root, "FYStartDate", 1)
E(root, "CriticalSlackLimit", 0)
E(root, "CurrencyDigits", 2)
E(root, "CalendarUID", 1)
E(root, "DefaultStartTime", "08:00:00")
E(root, "DefaultFinishTime", "17:00:00")
E(root, "MinutesPerDay", 480)
E(root, "MinutesPerWeek", 2400)
E(root, "DaysPerMonth", 20)
E(root, "DefaultTaskType", 0)
E(root, "DefaultFixedCostAccrual", 3)
E(root, "DefaultStandardRate", 0)
E(root, "DefaultOvertimeRate", 0)
E(root, "DurationFormat", 7)
E(root, "WorkFormat", 2)
E(root, "NewTasksAreManual", 0)
E(root, "ProjectExternallyEdited", 0)
E(root, "ExtendedCreationDate", "2026-10-17T18:30:00")
E(root, "ActualsInSync", 0)
E(root, "RemoveFileProperties", 0)
E(root, "AdminProject", 0)

cals = E(root, "Calendars")
c = E(cals, "Calendar")
E(c, "UID", 1); E(c, "Name", "Standard"); E(c, "IsBaseCalendar", 1); E(c, "IsBaselineCalendar", 0); E(c, "BaseCalendarUID", -1)
wd = E(c, "WeekDays")
for day in range(1, 8):
    w = E(wd, "WeekDay"); E(w, "DayType", day)
    if day in (1, 7):
        E(w, "DayWorking", 0)
    else:
        E(w, "DayWorking", 1)
        wt = E(w, "WorkingTimes")
        for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
            x = E(wt, "WorkingTime"); E(x, "FromTime", a); E(x, "ToTime", b)

# ---- notes
def note(k):
    i = ISS[k]
    L = [f"{k} · {i['title']}", f"Équipe : {dict(TEAMS)[i['team']]} · Jalon : {MSN[i['ms']]} · Priorité : {i['prio']} · Responsable : {OWN[i['owner']]}"]
    if k in DONE:
        L.append("État : réalisé (hypothèse de planification à vérifier dans le dépôt).")
    base_d = m.BASE_DURATIONS.get(k)
    if k not in DONE and base_d is not None and base_d != dur_of(k):
        L.append(f"Durée estimée : {dur_of(k)} j avec assistance de Claude (hypothèse, facteur {m.FACTEUR_ASSISTANCE}) ; {base_d} j sans assistance.")
    else:
        L.append("Durée estimée : " + f"{dur_of(k)} j" + " (estimation à ajuster)")
    if i.get("tasks"):
        L.append("Tâches :"); L += [f"- {x}" for x in i["tasks"]]
    if i.get("done"):
        L.append("Critère d'acceptation : " + i["done"])
    if i.get("proof"):
        L.append("Preuve attendue : " + i["proof"])
    if i.get("bc05"):
        L.append("Briques BC05 : " + ", ".join(i["bc05"]))
    if k in m.REPRIS:
        L.append("Reprend les issues : " + ", ".join(sorted(m.REPRIS[k])))
    if ISS[k].get("id", k).startswith("LOC-") or k in ("DAT-10", "GES-19"):
        L.append("Issue ajoutée le 20/10/2026 par le passage à l'exécution locale (ADR-023).")
    if k in ("MS-01","MS-02","MS-03","MS-04","MS-05","MS-06","MS-07","MS-08","MS-09","MS-10","MS-11","MS-12","MS-13","MS-14","MS-15","MS-16","MS-17"):
        L.append("Issue de la proposition microservices (17/10/2026), à valider avec le professeur (GES-06).")
    return "\n".join(L)

README = """Novaria Core : plan DevSecOps du binôme (Manoa Robel, Daddy Luciano), du 12/10/2026 à la soutenance du 10/12/2026. Mise à jour du 20/10/2026.
Structure : une section Jalons (M0 à M6) et une section par équipe (Gestion, Documentation, Cloud et DevSecOps, Données, Back-end et microservices, Front-end, IA).
Chaque tâche porte l'identifiant de l'issue GitHub (ex. [MS-08]) ; la description détaillée est dans la note de la tâche.
Hypothèses :
- Durées en jours ouvrés : estimations de départ, à corriger par le binôme.
- Calendrier : du lundi au vendredi, 8 h/jour (08:00-12:00, 13:00-17:00), disponibilité pleine pour les deux personnes (à confirmer).
- Exécution locale d'abord (consigne orale du professeur, ADR-023) : les tâches AWS (CLD-09 à CLD-12, CLD-15 à CLD-18, CLD-21, GES-18, MS-17) sont retirées de ce plan ; elles restent dans le backlog avec l'étiquette aws:differe. CLD-15 est remplacée par LOC-03.
- Assistance de Claude pour les DEUX membres : les tâches de construction (code, scripts, tests des équipes Données, Back-end, Front-end, IA, Cloud) sont comptées à 75 % de leur durée sans assistance. C'EST UNE HYPOTHÈSE, non mesurée : à corriger après LOC-01, LOC-02 et IA-08. Les premiers essais réels, relectures croisées et tris de résultats ne sont pas raccourcis.
- 19 et 20/10/2026 : préparation du kit (ADR 023 à 028, bases locales, contrats v0) ; les durées de DAT-02 et MS-03 sont réduites en conséquence, et le plan démarre le 21/10/2026.
- IA-11 (prototype SUMO) est conditionnelle et hors plan tant que le générateur v0 n'est pas livré et testé.
- Tâches réalisées avant le 17/10/2026 : GES-01, GES-02, GES-03, CLD-02 à CLD-06 (à vérifier).
- Tâche « les deux » (DM) : réparties à 50 % sur chaque personne.
- Les issues absorbées par une issue MS (BE-01 à BE-08, DAT-03 à DAT-05, DAT-07, DAT-09, FE-02, FE-04, FE-08, CLD-07, CLD-13, CLD-14) ne sont pas comptées deux fois.
- Les 17 issues MS-01 à MS-17 (microservices) attendent la validation du professeur.
ATTENTION - capacité : les dates de ce fichier suivent les dépendances sans limite de charge. La charge totale dépasse la capacité des deux personnes d'ici au 10/12/2026 (voir docs/07-gestion/charge-et-calendrier.md). Dans ProjectLibre, lancer « Niveler les ressources » pour voir la date réelle.
Coûts : aucun tarif n'est saisi. Le taux journalier et la devise sont à fixer avec le professeur (issue GES-06). Pour obtenir le coût du projet : colonne « Taux standard » de la feuille Ressources, puis lire le coût dans le tableau des tâches.
Les échéances des jalons sont des dates limites (colonne Date limite) : un jalon qui dépasse sa date limite indique un dépassement du calendrier."""

tasks = E(root, "Tasks")
def child_info(wbs):
    return [r for r in rows if r[0] == "task" and r[3].startswith(wbs + ".")]

for kind, key, lvl, wbs in rows:
    t = E(tasks, "Task")
    E(t, "UID", uid[key if kind in ("task", "ms", "sum") else "T:" + key])
    E(t, "ID", uid[key if kind in ("task", "ms", "sum") else "T:" + key])
    if kind == "sum":
        name = "Jalons du projet"
    elif kind == "ms":
        i = int(key[1]); name = MSN[i]
    elif kind == "team":
        name = "Équipe · " + dict(TEAMS)[key]
    else:
        name = f"[{key}] {ISS[key]['title']}"
    E(t, "Name", name)
    E(t, "Type", 0); E(t, "IsNull", 0); E(t, "CreateDate", "2026-10-17T18:30:00")
    E(t, "WBS", wbs); E(t, "OutlineNumber", wbs); E(t, "OutlineLevel", lvl)
    E(t, "Priority", PRIO[ISS[key]["prio"]] if kind == "task" else 500)
    if kind == "task":
        s, f = start_of(key), end_of(key)
        d = dur_of(key)
        E(t, "Start", fmt(s)); E(t, "Finish", fmt(f)); E(t, "Duration", hrs(d)); E(t, "DurationFormat", 7)
        E(t, "Work", hrs(d)); E(t, "EffortDriven", 0); E(t, "Estimated", 1); E(t, "Milestone", 0); E(t, "Summary", 0)
        E(t, "PercentComplete", 100 if key in DONE else 0)
        if key in DONE:
            E(t, "ActualStart", fmt(s)); E(t, "ActualFinish", fmt(f))
        E(t, "ConstraintType", 0)
        E(t, "Notes", note(key))
        for p in real_preds(key):
            pl = E(t, "PredecessorLink")
            E(pl, "PredecessorUID", uid[p]); E(pl, "Type", 1); E(pl, "CrossProject", 0); E(pl, "LinkLag", 0); E(pl, "LagFormat", 7)
    elif kind == "ms":
        i = int(key[1]); w = ms_when[i]
        E(t, "Start", fmt(w)); E(t, "Finish", fmt(w)); E(t, "Duration", "PT0H0M0S"); E(t, "DurationFormat", 7)
        E(t, "Work", "PT0H0M0S"); E(t, "Estimated", 0); E(t, "Milestone", 1); E(t, "Summary", 0)
        E(t, "PercentComplete", 0)
        if i == 6:
            E(t, "ConstraintType", 4); E(t, "ConstraintDate", "2026-12-10T08:00:00")
        else:
            E(t, "ConstraintType", 0)
        E(t, "Deadline", MSD[i] + "T17:00:00")
        E(t, "Notes", f"{MSN[i]}\nÉchéance : {MSD[i]}\n{m.issues_data.MILESTONES[i][2]}\nCe jalon est atteint quand toutes les tâches du jalon sont terminées.")
        for k in ms_members[i]:
            pl = E(t, "PredecessorLink")
            E(pl, "PredecessorUID", uid[k]); E(pl, "Type", 1); E(pl, "CrossProject", 0); E(pl, "LinkLag", 0); E(pl, "LagFormat", 7)
    else:
        if kind == "sum":
            ks = [f"M{i}" for i in range(7)]
            s = min(ms_when[i] for i in range(7)); f = max(ms_when[i] for i in range(7))
            work = 0
            E(t, "Start", fmt(dt.datetime(2026, 10, 12, 8))); E(t, "Finish", fmt(f))
            span = (f - dt.datetime(2026, 10, 12, 8)).days
            E(t, "Duration", hrs(max(1, len([x for x in m.DAYS if dt.date(2026,10,12) <= x <= f.date()])))); E(t, "DurationFormat", 7)
            E(t, "Work", "PT0H0M0S")
            E(t, "Milestone", 0); E(t, "Summary", 1); E(t, "PercentComplete", 0); E(t, "ConstraintType", 0)
            E(t, "Notes", README)
        else:
            kids = [r[1] for r in rows if r[0] == "task" and ISS[r[1]]["team"] == key]
            s = min(start_of(k) for k in kids); f = max(end_of(k) for k in kids)
            E(t, "Start", fmt(s)); E(t, "Finish", fmt(f))
            ndays = len([x for x in m.DAYS if s.date() <= x <= f.date()])
            E(t, "Duration", hrs(ndays)); E(t, "DurationFormat", 7)
            E(t, "Work", hrs(sum(dur_of(k) for k in kids)))
            E(t, "Milestone", 0); E(t, "Summary", 1)
            E(t, "PercentComplete", int(round(100 * sum(dur_of(k) for k in kids if k in DONE) / sum(dur_of(k) for k in kids))))
            E(t, "ConstraintType", 0)
            E(t, "Notes", f"Équipe {dict(TEAMS)[key]} : {len(kids)} tâches. Le plan DevSecOps de cette équipe regroupe ses tâches de tous les jalons.")

res = E(root, "Resources")
for ruid, name, ini in ((1, "Daddy Luciano", "DL"), (2, "Manoa Robel", "MR")):
    r = E(res, "Resource")
    E(r, "UID", ruid); E(r, "ID", ruid); E(r, "Name", name); E(r, "Type", 1); E(r, "IsNull", 0)
    E(r, "Initials", ini); E(r, "Group", "Binôme Novaria Core"); E(r, "MaxUnits", "1.00")
    E(r, "PeakUnits", "1.00"); E(r, "OverAllocated", 0); E(r, "CanLevel", 1)
    E(r, "AccrueAt", 3); E(r, "StandardRate", 0); E(r, "StandardRateFormat", 2); E(r, "OvertimeRate", 0)
    E(r, "OvertimeRateFormat", 2); E(r, "CostPerUse", 0); E(r, "CalendarUID", 1)

asg = E(root, "Assignments")
au = 1
for kind, key, lvl, wbs in rows:
    if kind != "task":
        continue
    for rid, share in m.RES[ISS[key]["owner"]]:
        a = E(asg, "Assignment")
        E(a, "UID", au); au += 1
        E(a, "TaskUID", uid[key]); E(a, "ResourceUID", 1 if rid == "D" else 2)
        E(a, "PercentWorkComplete", 100 if key in DONE else 0)
        E(a, "Cost", 0); E(a, "Start", fmt(start_of(key))); E(a, "Finish", fmt(end_of(key)))
        E(a, "Units", f"{share:.2f}")
        E(a, "Work", hrs(dur_of(key) * share))

ET.indent(root)
import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "novaria-core-projectlibre.xml")
ET.ElementTree(root).write(out, encoding="UTF-8", xml_declaration=True)
print("écrit", out, "tâches:", nxt - 1, "affectations:", au - 1)
print("fin CPM :", fin_all, "M6 :", ms_when[6])
for i in range(7):
    print(MSN[i][:30], "échéance", MSD[i], "prévu", ms_when[i].date())
