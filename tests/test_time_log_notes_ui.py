import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TimeLogNotesUITests(unittest.TestCase):
    def test_monday_log_forms_use_shared_live_validator(self):
        template = (ROOT / "app/templates/monday_report.html").read_text()

        self.assertIn("data-daylog-form data-log-hours-form", template)
        self.assertIn("data-catchup-form data-log-hours-form", template)
        self.assertEqual(template.count("data-log-notes-helper"), 2)

    def test_dashboard_day_log_uses_shared_live_validator(self):
        template = (ROOT / "app/templates/dashboard.html").read_text()

        self.assertIn("data-dashboard-daylog-form data-log-hours-form", template)
        self.assertIn('id="dashboard-daylog-notes-helper" data-log-notes-helper', template)

    def test_shared_validator_counts_like_backend_normalization(self):
        template = (ROOT / "app/templates/base.html").read_text()

        self.assertIn('value.trim().replace(/\\s+/g, " ").length', template)


if __name__ == "__main__":
    unittest.main()
