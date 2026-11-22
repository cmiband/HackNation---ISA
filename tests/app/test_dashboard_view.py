from datetime import date

import pandas as pd
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import Case, FileData, User
from app.db.repository import CaseRepository
from app.ui.views.dashboard import (
    DASHBOARD_COLUMNS,
    empty_dashboard_frame,
    load_dashboard_frame,
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
