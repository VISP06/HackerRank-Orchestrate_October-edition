import json
import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ExclusiveLinkOptInTest(unittest.TestCase):
    def test_default_explanation_has_no_exclusive_link(self):
        env = os.environ.copy()
        env.pop("GEMINI_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "code/main.py", "--explain", "case_512", "--json"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        )
        self.assertNotIn("workflow_exclusive", result.stdout)

    def test_opt_in_explanation_reports_exclusive_link(self):
        env = os.environ.copy()
        env.pop("GEMINI_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "code/main.py", "--explain", "case_512", "--exclusive-links", "--json"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        )
        explanation = json.loads(result.stdout)
        reasons = [reason for resource in explanation["resources"] for reason in resource["link_reason"]]
        self.assertIn("workflow_exclusive", " ".join(reasons))


if __name__ == "__main__":
    unittest.main()
