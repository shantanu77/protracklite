import unittest

from app.main import management_assignment_creates_cycle


class HierarchyCycleTests(unittest.TestCase):
    def test_top_level_assignment_is_safe(self):
        self.assertFalse(management_assignment_creates_cycle({1: None, 2: 1}, 2, None))

    def test_normal_manager_assignment_is_safe(self):
        self.assertFalse(management_assignment_creates_cycle({1: None, 2: None, 3: 2}, 3, 1))

    def test_self_management_is_rejected(self):
        self.assertTrue(management_assignment_creates_cycle({1: None}, 1, 1))

    def test_indirect_cycle_is_rejected(self):
        self.assertTrue(management_assignment_creates_cycle({1: None, 2: 1, 3: 2}, 1, 3))

    def test_existing_broken_chain_is_treated_as_cycle(self):
        self.assertTrue(management_assignment_creates_cycle({1: 2, 2: 1, 3: None}, 3, 1))


if __name__ == "__main__":
    unittest.main()
