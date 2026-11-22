from datetime import date

import pandas as pd
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import Case, FileData, User
from app.db.repository import CaseRepository
from app.ui.views.dashboard import (
    DASHBOARD_COLUMNS,
    deadline_urgency,
    empty_dashboard_frame,
    format_deadline_cell,
    load_dashboard_data,
    load_dashboard_frame,
    select_dashboard_rows,
)
from contracts.enums import CaseStatus, FileType


def test_empty_dashboard_frame_has_expected_columns():
    df = empty_dashboard_frame()
    assert list(df.columns) == DASHBOARD_COLUMNS
    assert len(df) == 0
    assert DASHBOARD_COLUMNS == [
        "#",
        "Initials",
        "Topic",
        "Upload date",
        "Deadline",
        "Days to deadline",
        "Reply date",
        "Status",
    ]


def test_load_dashboard_frame_queries_and_maps_columns():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(initials="DB", first_name="Dominik", last_name="Banach")
        session.add(user)
        session.commit()
        session.refresh(user)

        repo = CaseRepository(session)
        repo.add_with_application(
            Case(
                topic="Road repairs",
                created_date=date(2026, 11, 10),
                response_deadline=date(2026, 11, 24),
                status=CaseStatus.NEW,
                assignee_id=user.id,
            ),
            FileData(filename="road.pdf", file_type=FileType.APPLICATION),
        )
        repo.add_with_application(
            Case(
                topic=None,
                created_date=date(2026, 11, 1),
                response_deadline=date(2026, 11, 15),
                response_date=date(2026, 11, 14),
                status=CaseStatus.RESPONSE_SENT,
            ),
            FileData(filename="done.docx", file_type=FileType.APPLICATION),
        )

        df = load_dashboard_frame(session=session, today=date(2026, 11, 22))

    assert list(df.columns) == DASHBOARD_COLUMNS
    assert len(df) == 2

    # Row 1: older case (2026-11-01), already replied -> Days to deadline is NA.
    row1 = df.iloc[0]
    assert row1["#"] == 1
    assert row1["Initials"] == ""
    assert row1["Topic"] == ""
    assert row1["Upload date"] == date(2026, 11, 1)
    assert row1["Deadline"] == date(2026, 11, 15)
    assert pd.isna(row1["Days to deadline"])
    assert row1["Reply date"] == date(2026, 11, 14)
    assert row1["Status"] == "Response_Sent"

    # Row 2: newer case (2026-11-10), due in 2 days from 2026-11-22.
    row2 = df.iloc[1]
    assert row2["#"] == 2
    assert row2["Initials"] == "DB"
    assert row2["Topic"] == "Road repairs"
    assert row2["Upload date"] == date(2026, 11, 10)
    assert row2["Deadline"] == date(2026, 11, 24)
    assert row2["Days to deadline"] == 2
    assert row2["Reply date"] is None
    assert row2["Status"] == "New"


def test_load_dashboard_data_returns_case_ids_in_row_order():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        repo = CaseRepository(session)
        newer = repo.add_with_application(
            Case(created_date=date(2026, 11, 10), response_deadline=date(2026, 11, 24)),
            FileData(filename="b.pdf", file_type=FileType.APPLICATION),
        )
        older = repo.add_with_application(
            Case(created_date=date(2026, 11, 1), response_deadline=date(2026, 11, 15)),
            FileData(filename="a.pdf", file_type=FileType.APPLICATION),
        )

        case_ids, df = load_dashboard_data(session=session, today=date(2026, 11, 22))

    assert case_ids == [older.id, newer.id]
    assert len(df) == 2


def test_deadline_urgency_and_formatting():
    assert deadline_urgency(-2) == "overdue"
    assert deadline_urgency(0) == "today"
    assert deadline_urgency(1) == "tomorrow"
    assert deadline_urgency(3) == "soon"
    assert deadline_urgency(4) is None
    assert deadline_urgency(None) is None
    assert deadline_urgency(pd.NA) is None

    html, is_html = format_deadline_cell(date(2026, 11, 22), 0)
    assert is_html is True
    assert "2026-11-22" in html
    assert "#fecaca" in html

    plain, is_html = format_deadline_cell(date(2026, 11, 30), 8)
    assert is_html is False
    assert plain == "2026-11-30"

    replied_plain, is_html = format_deadline_cell(date(2026, 10, 22), pd.NA)
    assert is_html is False
    assert replied_plain == "2026-10-22"


def test_select_dashboard_rows_top_10_by_deadline_and_show_all():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        repo = CaseRepository(session)
        # 2 archived (replied) cases with old deadlines that must not crowd out active cases.
        for day in (1, 2):
            repo.add_with_application(
                Case(
                    topic=f"Archived {day}",
                    created_date=date(2026, 10, day),
                    response_deadline=date(2026, 10, day),
                    response_date=date(2026, 10, day),
                    status=CaseStatus.RESPONSE_SENT,
                ),
                FileData(filename=f"arch_{day}.pdf", file_type=FileType.APPLICATION),
            )
        # 12 active cases with staggered deadlines in reverse creation order.
        for i in range(12):
            repo.add_with_application(
                Case(
                    topic=f"Active {i}",
                    created_date=date(2026, 11, 1 + i),
                    response_deadline=date(2026, 11, 28 - i),
                    status=CaseStatus.NEW,
                ),
                FileData(filename=f"act_{i}.pdf", file_type=FileType.APPLICATION),
            )

        case_ids, df = load_dashboard_data(session=session, today=date(2026, 11, 22))

    # Default view: top 10 active cases by earliest deadline, renumbered 1..10.
    top_ids, top_df = select_dashboard_rows(case_ids, df, show_all=False)
    assert len(top_df) == 10
    assert len(top_ids) == 10
    assert list(top_df["#"]) == list(range(1, 11))
    assert list(top_df["Deadline"]) == sorted(top_df["Deadline"])
    assert all(top_df["Status"] == "New")
    assert top_df.iloc[0]["Topic"] == "Active 11"  # deadline 2026-11-17 (earliest active)

    # Show all: returns all 14 rows in original oldest -> newest order.
    all_ids, all_df = select_dashboard_rows(case_ids, df, show_all=True)
    assert len(all_df) == 14
    assert all_ids == case_ids
    assert all_df.iloc[0]["Topic"] == "Archived 1"
