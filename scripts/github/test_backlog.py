"""Contrôles du backlog sans réseau : py -3 -m unittest scripts/github/test_backlog.py (Windows) ou python3 -m unittest ... (Linux)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import issues_data  # noqa: E402
import issues_microservices  # noqa: E402,F401
import issues_suite  # noqa: E402,F401
import issues_v3  # noqa: E402


class BacklogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.touched = issues_v3.apply_amendments(issues_data.ISSUES)
        cls.issues = issues_data.ISSUES
        cls.ids = [i["id"] for i in cls.issues]

    def test_identifiants_uniques(self):
        self.assertEqual(len(self.ids), len(set(self.ids)))

    def test_dependances_connues_et_sans_cycle(self):
        known = set(self.ids)
        graph = {i["id"]: i["deps"] for i in self.issues}
        for k, deps in graph.items():
            for d in deps:
                self.assertIn(d, known, f"{k} dépend de {d}, inconnue")
        state = {}

        def visit(node, path):
            if state.get(node) == 1:
                self.fail("cycle : " + " -> ".join(path + [node]))
            if state.get(node) == 2:
                return
            state[node] = 1
            for d in graph[node]:
                visit(d, path + [node])
            state[node] = 2

        for k in graph:
            visit(k, [])

    def test_champs_valides(self):
        for i in self.issues:
            self.assertIn(i["team"], issues_data.TEAMS, i["id"])
            self.assertIn(i["type"], issues_data.TYPES, i["id"])
            self.assertIn(i["prio"], issues_data.PRIOS, i["id"])
            self.assertIn(i["owner"], ("D", "M", "DM"), i["id"])
            self.assertTrue(0 <= i["ms"] < len(issues_data.MILESTONES), i["id"])
            self.assertTrue(i["tasks"] and i["done"], i["id"])
            for k in i["bc05"]:
                self.assertIn(k, issues_data.BC05, i["id"])

    def test_nouvelles_issues_presentes(self):
        self.assertEqual(len(issues_v3.NEW_IDS), 13)
        for k in issues_v3.NEW_IDS:
            self.assertIn(k, self.ids)

    def test_dependance_a_un_jalon_ulterieur(self):
        """Une issue ne dépend pas d'une issue d'un jalon plus tardif."""
        by = {i["id"]: i for i in self.issues}
        for i in self.issues:
            for d in i["deps"]:
                self.assertLessEqual(by[d]["ms"], i["ms"], f"{i['id']} (M{i['ms']}) dépend de {d} (M{by[d]['ms']})")

    def test_amendements_idempotents_a_la_relecture(self):
        with self.assertRaises(issues_v3.AmendmentError):
            issues_v3.apply_amendments(issues_data.ISSUES)  # les textes à remplacer n'existent plus : détecté

    def test_aucun_make_up_dans_les_taches(self):
        for i in self.issues:
            for t in i["tasks"]:
                self.assertNotIn("make up", t, i["id"])


if __name__ == "__main__":
    unittest.main()
