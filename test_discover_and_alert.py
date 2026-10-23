import unittest

from discover_and_alert import role_priority, want


class FixedIncomePriorityTests(unittest.TestCase):
    def test_fixed_income_internship_titles_are_included_and_prioritized(self):
        for title in (
            "2027 Summer Fixed Income Intern",
            "Fixed-Income Analyst Internship",
            "2027 Credit Research Intern",
        ):
            with self.subTest(title=title):
                self.assertTrue(want(title))
                self.assertEqual(role_priority(title), 0)

    def test_other_investment_roles_remain_included_after_fixed_income(self):
        title = "2027 Equity Research Internship"

        self.assertTrue(want(title))
        self.assertEqual(role_priority(title), 1)

    def test_company_name_does_not_make_a_non_credit_role_fixed_income(self):
        title = "Credit Agricole CIB: 2027 Summer Internship - International Trade and Transaction Banking"

        self.assertEqual(role_priority(title), 2)

    def test_non_investment_internship_remains_excluded(self):
        title = "2027 Software Engineering Internship"

        self.assertFalse(want(title))
        self.assertEqual(role_priority(title), 2)


if __name__ == "__main__":
    unittest.main()
