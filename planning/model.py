"""Modèle du planning Novaria Core : tâches, durées, prédécesseurs, ordonnancement avec capacité."""
import datetime as dt
import os
import sys

for _f in (sys.stdout, sys.stderr):  # accents corrects sous Windows
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8", errors="replace")

KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "github")
sys.path.insert(0, KIT)
import issues_data  # noqa: E402
import issues_suite  # noqa: E402,F401  (ajoute 7 issues)
import issues_microservices  # noqa: E402,F401  (ajoute 17 issues)
import issues_v3  # noqa: E402  (ajoute 13 issues locales et applique les amendements du 20/10/2026)

issues_v3.apply_amendments(issues_data.ISSUES)
ISS = {i["id"]: i for i in issues_data.ISSUES}
MS_NAMES = [m[0] for m in issues_data.MILESTONES]

# Issues absorbées par une issue MS (non planifiées séparément pour ne pas compter deux fois)
ABSORBED = {
    "BE-01": "MS-03", "BE-02": "MS-10 et MS-11", "BE-03": "MS-13", "BE-04": "MS-10", "BE-05": "MS-08 et MS-12",
    "BE-06": "MS-04 (gabarit)", "BE-07": "chaque service (tests)", "BE-08": "MS-13",
    "DAT-03": "MS-08", "DAT-04": "MS-09", "DAT-05": "MS-10", "DAT-07": "MS-10", "DAT-09": "MS-09",
    "FE-02": "MS-14", "FE-04": "MS-14", "FE-08": "MS-14",
    "CLD-07": "MS-06", "CLD-13": "MS-15", "CLD-14": "MS-16",
}
REPRIS = {}
for old, new in ABSORBED.items():
    for n in new.replace(" et ", ",").split(","):
        n = n.strip().split(" ")[0]
        if n.startswith("MS-"):
            REPRIS.setdefault(n, []).append(old)

# Tâches déjà réalisées (semaine du 12 au 16 octobre), durées en jours, enchaînées dans l'ordre
DONE = [("GES-01", 0.5), ("GES-03", 0.5), ("GES-02", 0.5), ("CLD-02", 0.5), ("CLD-03", 1), ("CLD-04", 0.5), ("CLD-05", 1), ("CLD-06", 0.5)]

# id: (jours restants, prédécesseurs)
PLAN = {
    "GES-04": (1, []), "DOC-01": (1, []), "GES-05": (0.5, []), "GES-06": (1, ["GES-05", "DOC-01"]),
    "CLD-01": (0.5, []), "DOC-02": (1, []), "GES-18": (1, []), "GES-17": (1, []), "GES-16": (1, ["CLD-01"]),
    "CLD-22": (1, ["CLD-06"]), "CLD-23": (1, ["CLD-05"]), "CLD-24": (1, ["CLD-04"]), "DOC-10": (0.5, []),
    "GES-07": (1, ["GES-06"]), "GES-08": (2, ["GES-06"]), "CLD-08": (1, ["CLD-03", "GES-02"]),
    "MS-01": (2, ["GES-06"]), "MS-02": (2, ["GES-06"]), "DAT-01": (1, ["GES-06"]),
    "MS-03": (3, ["MS-01", "MS-02"]), "DAT-02": (3, ["DAT-01", "MS-01"]), "DOC-03": (3, ["MS-01"]),
    "DOC-04": (2, ["MS-01"]), "DOC-05": (3, ["MS-03"]), "MS-04": (2, ["MS-01"]), "MS-05": (2, ["MS-04"]),
    "MS-06": (2, ["MS-04", "MS-02"]), "CLD-09": (2, ["GES-18", "CLD-01"]), "CLD-10": (2, ["CLD-09"]),
    "CLD-11": (4, ["CLD-10", "MS-01"]), "CLD-12": (3, ["CLD-11", "MS-05"]),
    "MS-07": (3, ["MS-03"]), "MS-08": (4, ["MS-07", "MS-06"]), "MS-09": (5, ["MS-08", "DAT-02"]),
    "MS-10": (5, ["MS-09"]), "MS-11": (4, ["MS-09"]), "MS-12": (5, ["MS-10", "MS-03"]), "MS-13": (2, ["MS-04"]),
    "DAT-06": (3, ["MS-10", "CLD-11"]),
    "FE-01": (3, ["MS-03"]), "FE-03": (2, ["FE-01", "MS-13"]),
    "MS-14": (5, ["MS-10", "MS-11", "MS-12", "MS-13", "FE-01", "FE-03"]),
    "FE-05": (2, ["FE-01", "IA-06"]), "FE-06": (2, ["FE-01", "IA-07"]), "FE-07": (1, ["MS-14"]),
    "IA-01": (2, ["DAT-02", "MS-09"]), "IA-02": (2, ["IA-01", "MS-10"]), "IA-03": (3, ["IA-02"]),
    "IA-04": (2, ["IA-03"]), "IA-05": (3, ["IA-04"]), "IA-06": (3, ["IA-05", "MS-10"]),
    "DAT-08": (3, ["MS-10", "CLD-11"]), "IA-07": (2, ["MS-10"]),
    "MS-15": (3, ["MS-14"]), "MS-16": (2, ["MS-06", "MS-12"]), "MS-17": (3, ["CLD-11", "MS-05", "MS-12"]),
    "CLD-15": (2, ["CLD-11", "MS-10"]), "CLD-16": (1, ["CLD-12", "MS-17"]), "CLD-17": (1, ["CLD-11"]),
    "CLD-18": (2, ["CLD-09", "CLD-11"]), "CLD-19": (2, ["MS-15"]),
    "GES-09": (2, ["MS-17", "CLD-15"]), "GES-10": (1, ["GES-09"]), "DOC-06": (3, ["CLD-15"]),
    "DOC-07": (3, ["MS-15"]), "GES-11": (1, ["GES-08"]), "CLD-20": (2, ["CLD-05"]),
    "DOC-08": (2, ["CLD-19", "IA-05"]), "GES-12": (1, ["CLD-19"]), "DOC-09": (1, ["DOC-02", "DOC-08"]),
    "GES-13": (1, ["CLD-19", "DOC-07", "GES-10", "MS-17"]), "GES-14": (2, ["GES-13"]),
    "GES-15": (2, ["GES-14"]), "CLD-21": (1, ["GES-15"]),
}

# ---------------------------------------------------------------- version 3 (20/10/2026) : exécution locale d'abord
# Tâches différées (AWS non utilisé, ADR-023) : retirées du plan, conservées dans le backlog avec l'étiquette aws:differe.
DEFERRED = ["CLD-09", "CLD-10", "CLD-11", "CLD-12", "CLD-15", "CLD-16", "CLD-17", "CLD-18", "CLD-21", "GES-18", "MS-17"]
# Tâche conditionnelle, hors plan tant que le générateur v0 n'est pas livré et testé (ADR-027).
OPTIONAL = ["IA-11"]
for _k in DEFERRED:
    PLAN.pop(_k, None)
for _k, (_d, _ps) in list(PLAN.items()):
    PLAN[_k] = (_d, [p for p in _ps if p not in DEFERRED])

# Nouvelles tâches : (jours avant effet de l'assistance, prédécesseurs)
PLAN.update({
    "LOC-01": (1, ["GES-04"]), "LOC-02": (1, ["GES-04"]), "DAT-10": (1, ["GES-04"]), "GES-19": (0.5, ["DOC-02"]),
    "LOC-04": (2, ["MS-02", "LOC-01"]), "LOC-03": (1, ["LOC-01", "LOC-02"]), "LOC-06": (1, ["CLD-05"]),
    "IA-08": (4, ["MS-07", "DAT-10"]), "LOC-05": (2, ["LOC-01"]), "IA-09": (3, ["IA-08"]),
    "IA-10": (3, ["IA-03"]), "DOC-11": (1, ["LOC-05"]),
})
# Tâches existantes dont le contenu ou les prérequis changent
PLAN["DAT-02"] = (2, PLAN["DAT-02"][1])                       # migrations déjà écrites ; reste la validation
PLAN["MS-03"] = (2, PLAN["MS-03"][1])                         # contrats v0 déjà écrits
PLAN["MS-06"] = (1.5, PLAN["MS-06"][1] + ["LOC-01", "LOC-02", "LOC-04"])
PLAN["DAT-06"] = (2, PLAN["DAT-06"][1])                       # ETL local, pas de Glue
PLAN["DAT-08"] = (2, PLAN["DAT-08"][1])                       # PySpark local, pas d'EMR
PLAN["IA-05"] = (2, PLAN["IA-05"][1])                         # entraînement local, pas de SageMaker
PLAN["GES-09"] = (1, ["LOC-03"])                              # coût projeté, aucune ressource déployée
PLAN["DOC-06"] = (3, ["LOC-03"])
PLAN["IA-01"] = (2, PLAN["IA-01"][1] + ["IA-08"])
PLAN["IA-02"] = (2, PLAN["IA-02"][1] + ["IA-08"])
PLAN["FE-05"] = (2, PLAN["FE-05"][1])

# Gain attendu de l'usage de Claude par les DEUX membres sur les tâches de construction (code, scripts, tests).
# HYPOTHÈSE à mesurer sur les trois premières issues terminées (LOC-01, LOC-02, IA-08), puis à corriger ;
# 1.0 = aucun gain. Surcharge : variable d'environnement FACTEUR_ASSISTANCE.
FACTEUR_ASSISTANCE = float(os.environ.get("FACTEUR_ASSISTANCE", "0.75"))
BUILD_TEAMS = {"backend", "frontend", "data", "ia", "cloud"}
BUILD_TYPES = {"tache", "prototype", "test", "securite"}
# Tâches où l'assistance ne raccourcit pas le travail : premiers essais réels, relectures croisées, tri de résultats.
NO_ASSIST = {"LOC-01", "LOC-02", "LOC-03", "DAT-10", "CLD-08", "CLD-19", "MS-15", "GES-19"}


def assisted(k, days, factor=None):
    f = FACTEUR_ASSISTANCE if factor is None else factor
    i = ISS[k]
    if f == 1.0 or k in NO_ASSIST or i["team"] not in BUILD_TEAMS or i["type"] not in BUILD_TYPES:
        return days
    return max(0.5, round(days * f * 2) / 2)


def apply_assistance(factor=None):
    for _k, (_d, _ps) in list(PLAN.items()):
        PLAN[_k] = (assisted(_k, BASE_DURATIONS[_k], factor), _ps)


BASE_DURATIONS = {k: v[0] for k, v in PLAN.items()}  # avant effet de l'assistance
apply_assistance()

# ---------------------------------------------------------------- calendrier en demi-journées
START = dt.date(2026, 10, 12)
DAYS = []
d = START
while len(DAYS) < 200:
    if d.weekday() < 5:
        DAYS.append(d)
    d += dt.timedelta(days=1)


def slot_start(i):
    return dt.datetime.combine(DAYS[i // 2], dt.time(8) if i % 2 == 0 else dt.time(13))


def slot_end(i):  # fin (exclusive) du créneau i
    return dt.datetime.combine(DAYS[i // 2], dt.time(12) if i % 2 == 0 else dt.time(17))


GAP_SLOTS = 4  # 19/10 et 20/10 écoulés
PR = {"P0": 0, "P1": 1, "P2": 2}
RES = {"D": [("D", 1.0)], "M": [("M", 1.0)], "DM": [("D", 0.5), ("M", 0.5)]}


def build(durations=None):
    dur = {k: v[0] for k, v in PLAN.items()}
    if durations:
        dur.update(durations)
    preds = {k: v[1] for k, v in PLAN.items()}
    succ = {k: [] for k in PLAN}
    for k, ps in preds.items():
        for p in ps:
            if p in succ:
                succ[p].append(k)
    order = list(PLAN)
    eff = {k: PR[ISS[k]["prio"]] for k in PLAN}
    tail = {}

    def get_tail(k):
        if k in tail:
            return tail[k]
        tail[k] = dur[k] + max([get_tail(s) for s in succ[k]] or [0])
        return tail[k]

    changed = True
    while changed:
        changed = False
        for k in PLAN:
            for s in succ[k]:
                if eff[s] < eff[k]:
                    eff[k] = eff[s]
                    changed = True
    for k in PLAN:
        get_tail(k)

    used = {"D": {}, "M": {}}
    sched = {}
    t = 0
    for tid, days in DONE:
        n = int(days * 2)
        own = ISS[tid]["owner"]
        sched[tid] = (t, t + n, True)
        for r, u in RES[own]:
            for s in range(t, t + n):
                used[r][s] = used[r].get(s, 0) + u
        t += n
    base = t + GAP_SLOTS  # premier créneau libre = 21/10 08:00 (19 et 20/10 : préparation du kit, déjà absorbée)
    left = set(PLAN)
    while left:
        elig = [k for k in left if all((p in sched) for p in preds[k] if p in PLAN or p in dict(DONE))]
        elig.sort(key=lambda k: (ISS[k]["ms"], eff[k], -tail[k], order.index(k)))
        k = elig[0]
        n = int(round(dur[k] * 2))
        earliest = max([sched[p][1] for p in preds[k] if p in sched] + [base])
        s = earliest
        while True:
            if all(used[r].get(x, 0) + u <= 1.0 + 1e-9 for r, u in RES[ISS[k]["owner"]] for x in range(s, s + n)):
                break
            s += 1
        for r, u in RES[ISS[k]["owner"]]:
            for x in range(s, s + n):
                used[r][x] = used[r].get(x, 0) + u
        sched[k] = (s, s + n, False)
        left.remove(k)
    return dur, preds, sched, used, eff


def working_days(a, b):
    return len([x for x in DAYS if a <= x <= b])


def charge(res):
    """Jours de travail restants pour une personne (tâches du plan, hors tâches déjà réalisées)."""
    tot = 0.0
    for k, (d, _) in PLAN.items():
        for r, u in RES[ISS[k]["owner"]]:
            if r == res:
                tot += d * u
    return tot


def report(factor, label):
    apply_assistance(factor)
    dur, preds, sched, used, eff = build()
    deadline = dt.date(2026, 12, 10)
    first = DAYS[(sum(int(d * 2) for _, d in DONE) + GAP_SLOTS) // 2]
    cap = working_days(first, deadline)
    end = max(v[1] for k, v in sched.items() if k in PLAN)
    late = [k for k, v in sched.items() if k in PLAN and slot_end(v[1] - 1).date() > deadline]
    late_p0 = [k for k in late if ISS[k]["prio"] == "P0"]
    print(f"== {label} (facteur d'assistance {factor}) ==")
    print(f"  Fin du plan complet, avec capacité       : {slot_end(end - 1).date()}")
    print(f"  Jours ouvrés du {first} au 10/12/2026     : {cap}")
    for r, name in (("D", "Daddy"), ("M", "Manoa")):
        c = charge(r)
        print(f"  Charge de {name:<5}                        : {c:5.1f} j ({100 * c / cap:3.0f} % de la capacité)")
    print(f"  Tâches finissant après le 10/12          : {len(late)} sur {len(PLAN)} (dont P0 : {len(late_p0)})")
    return late, late_p0, sched


if __name__ == "__main__":
    for f, lab in ((1.0, "Sans effet d'assistance"), (FACTEUR_ASSISTANCE, "Avec assistance de Claude pour les deux")):
        late, late_p0, sched = report(f, lab)
    print("\nTâches en retard au scénario avec assistance :")
    for k in sorted(late, key=lambda k: sched[k][1]):
        print("  ", k, slot_end(sched[k][1] - 1).date(), ISS[k]["prio"], ISS[k]["title"][:62])


def cpm(durations=None):
    """Ordonnancement au plus tôt sans contrainte de capacité (créneaux de demi-journée)."""
    dur = {k: v[0] for k, v in PLAN.items()}
    base = sum(int(d * 2) for _, d in DONE) + GAP_SLOTS
    es = {}
    done_end = {}
    t = 0
    for tid, d in DONE:
        t += int(d * 2)
        done_end[tid] = t
    def get(k):
        if k in es:
            return es[k]
        ps = [get_end(p) for p in PLAN[k][1]]
        es[k] = max(ps + [base])
        return es[k]
    def get_end(p):
        if p in done_end:
            return done_end[p]
        return get(p) + int(round(dur[p] * 2))
    for k in PLAN:
        get(k)
    return {k: (es[k], es[k] + int(round(dur[k] * 2))) for k in PLAN}, done_end
