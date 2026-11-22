"""Response deadlines for requests for public information (UDIP / KPA). Deterministic, unit-tested.

- Regular deadline: received + 14 days (art. 13 ust. 1 UDIP; the day of receipt is not counted).
- Extended deadline ("kwerenda", case status Query): at most received + 2 months (art. 13 ust. 2 UDIP).
- A deadline falling on a Saturday, Sunday or Polish public holiday moves to the next working day
  (art. 57 § 4 KPA). Holidays: `holidays` package (includes 24 December since 2025).
"""

import calendar
from datetime import date, timedelta
from enum import StrEnum
from functools import lru_cache

import holidays

RESPONSE_DAYS = 14
QUERY_MONTHS = 2


@lru_cache(maxsize=32)
def _polish_holidays(year: int) -> frozenset[date]:
    return frozenset(holidays.country_holidays("PL", years=year))


def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _polish_holidays(day.year)


def next_working_day(day: date) -> date:
    """`day` itself if it is a working day, else the next one."""
    while not is_working_day(day):
        day += timedelta(days=1)
    return day


def add_months(day: date, months: int) -> date:
    """Same day `months` later, clamped to the month end (31 Jan + 1 month -> 28/29 Feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def response_deadline(received: date) -> date:
    return next_working_day(received + timedelta(days=RESPONSE_DAYS))


def query_deadline(received: date) -> date:
    """Latest extended deadline (the official may set an earlier one)."""
    return next_working_day(add_months(received, QUERY_MONTHS))


class Urgency(StrEnum):
    OVERDUE = "overdue"
    TODAY = "today"
    TOMORROW = "tomorrow"
    SOON = "soon"  # within 3 days
    OK = "ok"
    DONE = "done"  # reply sent


def urgency(deadline: date, today: date, *, done: bool = False) -> Urgency:
    if done:
        return Urgency.DONE
    days = (deadline - today).days
    if days < 0:
        return Urgency.OVERDUE
    if days == 0:
        return Urgency.TODAY
    if days == 1:
        return Urgency.TOMORROW
    if days <= 3:
        return Urgency.SOON
    return Urgency.OK
