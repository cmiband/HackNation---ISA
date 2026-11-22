"""Dashboard tab: full-width table of UDIP cases queried from SQLite."""

from collections.abc import Sequence
from contextlib import ExitStack
from datetime import date

import pandas as pd
import streamlit as st
from sqlmodel import Session

from app.db.engine import engine
from app.db.models import Case
from app.db.repository import CaseRepository
from contracts.enums import CaseStatus

DASHBOARD_COLUMNS = [
    "#",
    "Initials",
    "Topic",
    "Upload date",
    "Deadline",
    "Days to deadline",
    "Reply date",
    "Status",
]


def empty_dashboard_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the dashboard schema so column headers render cleanly."""
    return pd.DataFrame(columns=DASHBOARD_COLUMNS)


def build_dashboard_frame(
    cases: Sequence[Case],
    *,
    today: date | None = None,
) -> pd.DataFrame:
    """Convert ORM `Case` rows into a display DataFrame preserving native date/int types."""
    if not cases:
        return empty_dashboard_frame()

    ref_today = today or date.today()
    rows = []
    for idx, case in enumerate(cases, start=1):
        replied = case.response_date is not None or case.status == CaseStatus.RESPONSE_SENT
        days_to_deadline = None if replied else (case.response_deadline - ref_today).days
        rows.append(
            {
                "#": idx,
                "Initials": case.assignee.initials if case.assignee is not None else "",
                "Topic": case.topic or "",
                "Upload date": case.created_date,
                "Deadline": case.response_deadline,
                "Days to deadline": days_to_deadline,
                "Reply date": case.response_date,
                "Status": case.status.value,
            }
        )

    df = pd.DataFrame(rows, columns=DASHBOARD_COLUMNS)
    df["Days to deadline"] = pd.array(df["Days to deadline"], dtype="Int64")
    return df


def load_dashboard_frame(
    *,
    session: Session | None = None,
    today: date | None = None,
) -> pd.DataFrame:
    """Query all cases from SQLite (oldest → newest) and return the dashboard DataFrame."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        cases = CaseRepository(db).get_all_cases()
        return build_dashboard_frame(cases, today=today)


def render() -> None:
    st.subheader("📊 Case Dashboard")
    df = load_dashboard_frame()
    if df.empty:
        st.caption("No cases registered yet — upload applications in the Upload Request tab.")
    else:
        st.caption(f"Showing **{len(df)}** case(s), ordered oldest to newest.")

    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        height=600,
        column_config={
            "#": st.column_config.NumberColumn("#", format="%d", width="small"),
            "Initials": st.column_config.TextColumn("Initials", width="small"),
            "Topic": st.column_config.TextColumn("Topic", width="large"),
            "Upload date": st.column_config.DateColumn("Upload date", format="YYYY-MM-DD"),
            "Deadline": st.column_config.DateColumn("Deadline", format="YYYY-MM-DD"),
            "Days to deadline": st.column_config.NumberColumn("Days to deadline", format="%d"),
            "Reply date": st.column_config.DateColumn("Reply date", format="YYYY-MM-DD"),
            "Status": st.column_config.TextColumn("Status"),
        },
    )
