"""Regression tests for the fixed-income-only alerting path.

Every case here comes from a real posting that the scanner got wrong at some
point, so each one pins down a specific past bug rather than a hypothetical.
Kept in its own file so it sits alongside, not on top of, the existing
test_discover_and_alert.py / test_job_filters.py suites.
"""
import unittest
from datetime import date

from discover_and_alert import role_priority, want
from job_filters import is_fixed_income_role, is_recent_posting, parse_posted_date


class FalsePositivesStayOut(unittest.TestCase):
    """Roles that read as fixed income but are not investment work at all."""

    def test_surety_bond_insurance_is_not_fixed_income(self):
        # Travelers posts these by the half dozen. They matched relevance on
        # "underwrit" and then ranked as fixed income on "bond" -- but a
        # surety bond is an insurance product, not a debt security.
        for title in (
            "Travelers: Bond & Specialty Insurance Underwriting Professional "
            "Development Program (BSI UPDP) Internship",
            "Travelers: Bond and Specialty Insurance Intern: Underwriting "
            "Professional Development Program",
            "Travelers: Construction Surety Underwriter (Account Executive) - Credit",
        ):
            with self.subTest(title=title):
                self.assertFalse(want(title))

    def test_insurance_adjacent_support_roles_stay_out(self):
        for title in (
            "Travelers: Claim Professional Development Program Intern",
            "Columbia Threadneedle: Actuarial Intern",
        ):
            with self.subTest(title=title):
                self.assertFalse(want(title))

    def test_accounting_and_it_roles_stay_out(self):
        # Both slipped through on an investment-sounding word: "Mutual Fund
        # Accountant" on "fund", the engineer role on "Investments".
        for title in (
            "Thrivent: Mutual Fund Accountant Intern - Summer 2027",
            "Thrivent: IT Application Engineer Intern, Investments - Summer 2027",
            "Moody's: Ratings Multimedia Summer Intern",
        ):
            with self.subTest(title=title):
                self.assertFalse(want(title))

    def test_graduate_school_only_internships_stay_out(self):
        # Freddie Mac requires "a full-time graduate degree program (MBA...)";
        # the user is an undergraduate.
        for title in (
            "Freddie Mac: Risk Management Graduate Intern - Business Summer 2027",
            "Thrivent: Credit Research MBA/Graduate Internship - Investment Grade",
            "PIMCO: 2027 MBA Summer Intern - Credit Research Analyst",
        ):
            with self.subTest(title=title):
                self.assertFalse(want(title))

    def test_company_name_alone_never_makes_a_role_fixed_income(self):
        # "Credit Agricole" and "Moody's Ratings" both carry fixed-income words
        # in the employer name. Classification must read the role only.
        for title in (
            "Credit Agricole CIB: 2027 Summer Internship - International Trade "
            "and Transaction Banking",
            "Credit Agricole CIB: Summer Analyst - Energy and Real Assets - Advisory",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_fixed_income_role(title))
                self.assertNotEqual(role_priority(title), 0)

    def test_equity_and_generic_banking_are_not_fixed_income(self):
        # These are relevant roles but must not be alerted on a
        # fixed-income-only run.
        for title in (
            "CIBC: 2027 Summer Analyst, Equity Solutions Group",
            "Piper Sandler: 2027 Investment Banking Summer Analyst - Financial Sponsors",
            "JLL: Capital Markets Summer 2027 Internship - Boston, MA",
            "Northern Trust: Wealth Management Intern - Atlanta",
        ):
            with self.subTest(title=title):
                self.assertNotEqual(role_priority(title), 0)


class RelevantFixedIncomeStaysIn(unittest.TestCase):
    def test_core_fixed_income_roles_are_kept_and_ranked_first(self):
        for title in (
            "Truist: 2027 Structured Credit Summer Analyst Program",
            "Piper Sandler: 2027 Summer Internship Program - Fixed Income Services",
            "Baird: Internship - Fixed Income Asset Management, Baird Advisors (Summer 2027)",
            "Ameriprise: Investments Intern - Fixed Income Investment Grade",
            "Thrivent: Commercial Mortgages and Securitized Real Estate Assets "
            "Intern - Summer 2027",
            "KeyBank: 2027 Summer Commercial Bank Internship - New York City (Credit)",
        ):
            with self.subTest(title=title):
                self.assertTrue(want(title))
                self.assertEqual(role_priority(title), 0)

    def test_credit_ratings_work_counts_as_fixed_income(self):
        # Rating agencies analyse bond issuers. These titles never say
        # "fixed income", which is exactly why they were being missed.
        for title in (
            "S&P Global: Ratings Analytical Intern - Americas",
            "Moody's: Ratings and Research Support Summer Intern - Sovereign "
            "and Sub-Sovereign Group",
            "Moody's: Credit Strategy & Standard Summer Intern",
        ):
            with self.subTest(title=title):
                self.assertTrue(want(title))
                self.assertEqual(role_priority(title), 0)

    def test_debt_and_high_yield_roles_count_as_fixed_income(self):
        for title in (
            "William Blair: 2027 Investment Banking Summer Analyst, Enterprise Value Debt",
            "Blackstone: 2027 Blackstone Real Estate Debt Strategies Summer Analyst",
            "StepStone: 2027 Private Debt Summer Analyst",
            "High Yield Summer Analyst Intern 2027",
            "BMO: BMO Capital Markets Summer 2027 Sophomore Analyst, "
            "Infrastructure Debt Capital Markets",
        ):
            with self.subTest(title=title):
                self.assertEqual(role_priority(title), 0)

    def test_graduation_year_wording_is_not_mistaken_for_grad_school(self):
        # The grad-school exclusion must not eat these: 2028 is the user's
        # graduation year and these are the roles he most wants.
        for title in (
            "D.A. Davidson: Consumer Group, Investment Banking - Summer Analyst - 2028 Grads",
            "D.A. Davidson: Class of 2028 Equity Capital Markets Research Intern",
            "Summer 2027 Credit Internship (Class of 2028)",
        ):
            with self.subTest(title=title):
                self.assertTrue(want(title))


class PostingDateHandling(unittest.TestCase):
    TODAY = date(2026, 10, 23)

    def test_real_ats_date_formats_parse(self):
        # One sample per platform, taken from live payloads.
        cases = {
            "2026-06-09T16:56:01-04:00": date(2026, 6, 9),    # Greenhouse first_published
            1789667479593: date(2026, 9, 17),                  # Lever createdAt (epoch ms)
            "Posted 3 Days Ago": date(2026, 10, 20),           # Workday postedOn
            "2026-10-16": date(2026, 10, 16),                  # Oracle HCM PostedDate
            "2026-10-23T04:47:00+0000": date(2026, 10, 23),    # SIG posted_date
            "2026-08-06": date(2026, 8, 6),                    # JSON-LD datePosted
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_posted_date(raw, self.TODAY), expected)

    def test_unparseable_dates_are_not_treated_as_recent(self):
        # Workday says "Posted 30+ Days Ago" once a posting ages out. It must
        # not parse to something recent, and an undated role must never be
        # presented as new.
        for raw in ("Posted 30+ Days Ago", "", None, "n/a", "Posted recently"):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_posted_date(raw, self.TODAY))
                self.assertFalse(is_recent_posting(raw, 30, self.TODAY))

    def test_day_first_dates_are_refused_rather_than_misread(self):
        # Credit Agricole renders "22/10/2026" (22 October) and is the only
        # source with no publication date at all -- it exposes an "Update
        # date" instead. Guessing month-first would silently turn that into
        # a different date, so it must parse to None.
        self.assertIsNone(parse_posted_date("22/10/2026", self.TODAY))

    def test_boundaries_of_the_thirty_and_seven_day_windows(self):
        self.assertTrue(is_recent_posting("2026-09-23", 30, self.TODAY))   # exactly 30
        self.assertFalse(is_recent_posting("2026-09-22", 30, self.TODAY))  # 31
        self.assertTrue(is_recent_posting("2026-10-16", 7, self.TODAY))    # exactly 7
        self.assertFalse(is_recent_posting("2026-10-15", 7, self.TODAY))   # 8
        self.assertFalse(is_recent_posting("2026-11-01", 30, self.TODAY))  # future


if __name__ == "__main__":
    unittest.main()
