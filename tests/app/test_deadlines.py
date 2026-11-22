from datetime import date

import pytest

from app.services.deadlines import (
    Urgency,
    add_months,
    is_working_day,
    next_working_day,
    query_deadline,
    response_deadline,
    urgency,
)


def test_working_days_and_polish_holidays():
    assert is_working_day(date(2026, 11, 23))  # Monday
    assert not is_working_day(date(2026, 11, 22))  # Sunday
    assert not is_working_day(date(2026, 11, 11))  # Independence Day (Wednesday)
    assert not is_working_day(date(2026, 12, 24))  # Christmas Eve (holiday since 2025)
    assert not is_working_day(date(2026, 4, 6))  # Easter Monday
    assert next_working_day(date(2026, 12, 24)) == date(2026, 12, 28)  # 24-26 Dec + Sunday


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        (date(2026, 1, 12), date(2026, 1, 26)),  # Monday + 14 days = Monday
        (date(2026, 11, 7), date(2026, 11, 23)),  # +14 = Saturday 21.11 -> Monday 23.11
        (date(2026, 10, 28), date(2026, 11, 12)),  # +14 = Wednesday 11.11 (holiday) -> Thursday
        (date(2026, 12, 10), date(2026, 12, 28)),  # +14 = Thursday 24.12 -> 28.12
    ],
)
def test_response_deadline(received, expected):
    assert response_deadline(received) == expected


def test_query_deadline_two_months_and_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 2) == date(2027, 1, 30)
    assert query_deadline(date(2026, 3, 10)) == date(2026, 5, 11)  # 10.05 is a Sunday
    assert query_deadline(date(2026, 1, 15)) == date(2026, 3, 16)  # 15.03 is a Sunday


def test_urgency_levels():
    today = date(2026, 11, 23)
    assert urgency(date(2026, 11, 20), today) == Urgency.OVERDUE
    assert urgency(today, today) == Urgency.TODAY
    assert urgency(date(2026, 11, 24), today) == Urgency.TOMORROW
    assert urgency(date(2026, 11, 26), today) == Urgency.SOON
    assert urgency(date(2026, 11, 27), today) == Urgency.OK
    assert urgency(date(2026, 11, 20), today, done=True) == Urgency.DONE
