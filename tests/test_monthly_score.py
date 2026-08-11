import unittest

from app.reports import calculate_monthly_base_score


def task(task_id, *, completed=True, complexity=1.0, priority=False, rework=0, due="2026-07-20", completion="2026-07-19", description=None):
    return {
        "task_id": task_id,
        "name": task_id,
        "description": description or "A documented result with enough factual detail for appraisal evidence.",
        "complexity_weight": complexity,
        "is_high_priority": priority,
        "rework_count": rework,
        "due_date": due,
        "completion_date": completion if completed else None,
        "completed_in_month": completed,
    }


class MonthlyScoreTests(unittest.TestCase):
    def facts(self, tasks, focus_count=2):
        return {
            "scoring_tasks": tasks,
            "weekly_focus": [{"focus": f"Focus {index}"} for index in range(focus_count)],
        }

    def test_no_tasks_uses_neutral_provisional_score(self):
        result = calculate_monthly_base_score(self.facts([]))
        self.assertEqual(result["base_score"], 3.0)
        self.assertEqual(result["maximum_final_rating"], 3.0)
        self.assertEqual(result["data_sufficiency_flag"], "INSUFFICIENT_EVIDENCE")

    def test_completion_is_weighted_by_complexity_and_priority(self):
        result = calculate_monthly_base_score(self.facts([
            task("CRITICAL", complexity=2.5, priority=True),
            task("LOW", completed=False),
        ]))
        self.assertAlmostEqual(result["completion_score"], 3.79, places=2)
        self.assertEqual(result["quality_score"], 5.0)
        self.assertEqual(result["timeliness_score"], 5.0)
        self.assertAlmostEqual(result["base_score"], 4.39, places=2)

    def test_rework_and_late_delivery_reduce_the_base(self):
        result = calculate_monthly_base_score(self.facts([
            task("LATE", rework=2, completion="2026-07-25"),
        ]))
        self.assertEqual(result["completion_score"], 5.0)
        self.assertEqual(result["quality_score"], 4.0)
        self.assertEqual(result["timeliness_score"], 0.0)
        self.assertEqual(result["base_score"], 3.7)

    def test_missing_due_date_is_neutral_not_late(self):
        result = calculate_monthly_base_score(self.facts([task("NO-DUE", due=None)]))
        self.assertEqual(result["timeliness_score"], 3.0)
        self.assertEqual(result["timeliness_task_count"], 0)

    def test_insufficient_weekly_evidence_caps_final_range(self):
        result = calculate_monthly_base_score(self.facts([task("DONE")], focus_count=1))
        self.assertEqual(result["data_sufficiency_flag"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["maximum_final_rating"], 3.0)


if __name__ == "__main__":
    unittest.main()
