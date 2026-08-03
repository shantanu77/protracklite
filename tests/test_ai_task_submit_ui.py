import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AITaskSubmitUITests(unittest.TestCase):
    def test_every_ai_task_form_uses_duplicate_submit_guard(self):
        for template_name in ("dashboard.html", "monday_report.html", "task_form.html"):
            with self.subTest(template=template_name):
                template = (ROOT / "app/templates" / template_name).read_text()
                self.assertIn("data-ai-task-form", template)
                self.assertIn("data-ai-task-submit", template)

    def test_shared_handler_disables_and_blocks_repeat_submission(self):
        template = (ROOT / "app/templates/base.html").read_text()

        self.assertIn('form.dataset.submitting === "true"', template)
        self.assertIn("submitButton.disabled = working", template)
        self.assertIn('document.createTextNode("Creating Tasks…")', template)


if __name__ == "__main__":
    unittest.main()
