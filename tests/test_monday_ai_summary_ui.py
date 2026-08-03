import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MondayAISummaryUITests(unittest.TestCase):
    def test_summary_selection_includes_highlight_radio(self):
        template = (ROOT / "app/templates/monday_report.html").read_text()

        self.assertIn('name="highlight_task_code"', template)
        self.assertIn("Highlight of the week", template)
        self.assertIn("report.weekly_ai_summary.summary_bullets", template)

    def test_prompt_requires_bullets_and_specific_highlight(self):
        source = (ROOT / "app/main.py").read_text()

        self.assertIn("Write 3 to 5 concise, standalone bullet points", source)
        self.assertIn("must specifically describe highlight_task", source)
        self.assertIn('"highlight_task": highlight_task', source)

    def test_archived_tasks_are_filtered_from_worked_last_week(self):
        source = (ROOT / "app/reports.py").read_text()

        self.assertIn(".join(Task, Task.id == TimeLog.task_id)", source)
        self.assertIn("Task.is_archived.is_(False)", source)


if __name__ == "__main__":
    unittest.main()
