import unittest
from datetime import date

from job_filters import (
    is_fixed_income_role,
    is_recent_posting,
    parse_posted_date,
    posting_age_days,
)


class JobFilterTests(unittest.TestCase):
    def test_fixed_income_classifier_ignores_company_name(self):
        self.assertFalse(
            is_fixed_income_role(
                "Credit Agricole CIB: Summer Internship - Transaction Banking"
            )
        )
        self.assertTrue(
            is_fixed_income_role("Credit Agricole CIB: Summer Credit Research Intern")
        )

    def test_iso_and_relative_posting_dates_are_parsed(self):
        today = date(2026, 10, 23)

        self.assertEqual(parse_posted_date("2026-10-19T11:30:00Z", today), date(2026, 10, 19))
        self.assertEqual(parse_posted_date("Posted 5 days ago", today), date(2026, 10, 18))
        self.assertEqual(posting_age_days("Yesterday", today), 1)

    def test_unknown_old_and_future_posting_dates_are_not_recent(self):
        today = date(2026, 10, 23)

        self.assertTrue(is_recent_posting("2026-10-16", 30, today))
        self.assertTrue(is_recent_posting("2026-09-24", 30, today))
        self.assertTrue(is_recent_posting("2026-09-23", 30, today))
        self.assertFalse(is_recent_posting("2026-09-22", 30, today))
        self.assertFalse(is_recent_posting("2026-11-01", 30, today))
        self.assertFalse(is_recent_posting(None, 30, today))
        self.assertFalse(is_recent_posting("Posted 40 days ago", 30, today))


if __name__ == "__main__":
    unittest.main()
