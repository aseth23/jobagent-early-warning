from __future__ import annotations

import re
from datetime import date, datetime, timezone

FIXED_INCOME = re.compile(
    r"\bfixed[\s-]?income\b|\bcredit\b|\bbonds?\b|\brates?\b|"
    r"securiti[sz]ed|structured (?:credit|products)|mortgage[- ]backed|"
    r"municipal (?:bond|credit|finance)|\bmunis?\b|\bdebt\b|"
    r"\bratings?\b|credit research|high[- ]yield|investment grade|\bCLO\b|"
    r"\bABS\b|\bCMBS\b|\bRMBS\b|leveraged loan|private credit",
    re.I,
)


def is_fixed_income_role(title: str) -> bool:
    if ": " in title:
        title = title.split(": ", 1)[1]
    return bool(FIXED_INCOME.search(title))


def parse_posted_date(value: object, today: date | None = None) -> date | None:
    today = today or date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 1_000_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    relative = re.search(
        r"\b(today|yesterday|(\d+)\s+days?\s+ago)\b", text, re.I)
    if relative:
        if relative.group(1).lower() == "today":
            return today
        days_ago = 1 if relative.group(1).lower() == "yesterday" else int(relative.group(2))
        return date.fromordinal(today.toordinal() - days_ago)

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for date_format in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def posting_age_days(posted_on: object, today: date | None = None) -> int | None:
    posted_date = parse_posted_date(posted_on, today)
    if posted_date is None:
        return None
    age = ((today or date.today()) - posted_date).days
    return age if age >= 0 else None


def is_recent_posting(
    posted_on: object, max_age_days: int = 30, today: date | None = None
) -> bool:
    age = posting_age_days(posted_on, today)
    return age is not None and age <= max_age_days
