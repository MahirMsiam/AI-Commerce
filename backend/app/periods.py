"""Date ranges, all relative to DEMO_TODAY (never the system clock)."""
from datetime import date, timedelta

from .config import DEMO_TODAY


def month_start(d: date) -> date:
    return d.replace(day=1)


def prev_month_start(d: date) -> date:
    return month_start(month_start(d) - timedelta(days=1))


def period_range(name: str, today: date = DEMO_TODAY) -> tuple[date, date]:
    """Inclusive (start, end). 'prev_same_days' is last month up to the same day number (Plan.md §7)."""
    if name == "today":
        return today, today
    if name == "this_week":
        return today - timedelta(days=today.weekday()), today
    if name == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    if name == "mtd":
        return month_start(today), today
    if name == "last_month":
        return prev_month_start(today), month_start(today) - timedelta(days=1)
    if name == "prev_same_days":
        start = prev_month_start(today)
        end = min(start.replace(day=28) + timedelta(days=4), month_start(today)) - timedelta(days=1)
        return start, min(start + timedelta(days=today.day - 1), end)
    if name == "last_3_months":
        return prev_month_start(prev_month_start(month_start(today))), today
    raise ValueError(name)


def last_n_weeks(n: int, today: date = DEMO_TODAY) -> tuple[date, date]:
    return today - timedelta(days=today.weekday() + 7 * (n - 1)), today
