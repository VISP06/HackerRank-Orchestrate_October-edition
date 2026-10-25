import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ExplainContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = os.environ.copy()
        cls.env.pop("GEMINI_API_KEY", None)
        cls.env.pop("GEMINI_MODEL", None)
        cls.output = {}
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [sys.executable, "code/main.py", "--explain-all", directory],
                cwd=ROOT, env=cls.env, check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for name in os.listdir(directory):
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    cls.output[name[:-5]] = json.load(handle)

    def test_every_case_has_explanation_and_matching_steps(self):
        with open(os.path.join(ROOT, "dataset", "deletion_requests.csv"), encoding="utf-8") as handle:
            cases = {row["case_id"] for row in csv.DictReader(handle)}
        with open(os.path.join(ROOT, "output.csv"), encoding="utf-8") as handle:
            answers = {row["case_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(set(self.output), cases)
        for case_id, explanation in self.output.items():
            self.assertEqual(explanation["steps"], json.loads(answers[case_id]["steps_json"]))
            self.assertEqual(explanation["status"]["decision"], answers[case_id]["deletion_status"])

    def test_evidence_is_not_after_cutoff(self):
        for explanation in self.output.values():
            cutoff = explanation["timeline"]["audit_at"]
            for resource in explanation["resources"]:
                for observation in resource["observations"]:
                    self.assertLessEqual(observation["capture_time"], cutoff)
                if resource["capture_time"]:
                    self.assertLessEqual(resource["capture_time"], cutoff)

    def test_personal_identifiers_are_masked(self):
        emails, phones = [], []
        with open(os.path.join(ROOT, "dataset/user_identities.csv"), encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                emails.append(row.get("email", ""))
                phones.append(row.get("phone", ""))
        encoded = json.dumps(self.output, sort_keys=True)
        for value in emails + phones:
            if value:
                self.assertNotIn(value, encoded)

    def test_single_case_is_deterministic(self):
        command = [sys.executable, "code/main.py", "--explain", "case_33", "--json"]
        first = subprocess.run(command, cwd=ROOT, env=self.env, check=True, capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, env=self.env, check=True, capture_output=True, text=True)
        self.assertEqual(first.stdout, second.stdout)


if __name__ == "__main__":
    unittest.main()
