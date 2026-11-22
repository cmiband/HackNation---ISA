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
from app.ui.views.case_detail import show_case_detail
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
    return load_dashboard_data(session=session, today=today)[1]


def load_dashboard_data(
    *,
    session: Session | None = None,
    today: date | None = None,
) -> tuple[list[int], pd.DataFrame]:
    """Return case ids (row order) and the dashboard DataFrame (oldest → newest)."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        cases = CaseRepository(db).get_all_cases()
        case_ids = [case.id for case in cases if case.id is not None]
        return case_ids, build_dashboard_frame(cases, today=today)


# Relative column widths: data columns + the "Details" button column.
_COLUMN_WEIGHTS = [0.5, 0.8, 4, 1.2, 1.2, 1.2, 1.2, 1.6, 0.8]


def _format_cell(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    return str(value)


def render() -> None:
    st.subheader("📊 Case Dashboard")
    case_ids, df = load_dashboard_data()
    if df.empty:
        st.caption("No cases registered yet — upload applications in the Upload Request tab.")
        return
    st.caption(f"Showing **{len(df)}** case(s), ordered oldest to newest.")

    header = st.columns(_COLUMN_WEIGHTS)
    for col, name in zip(header, [*DASHBOARD_COLUMNS, ""], strict=True):
        col.markdown(f"**{name}**")

    with st.container(height=600, border=False):
        for case_id, (_, row) in zip(case_ids, df.iterrows(), strict=True):
            cols = st.columns(_COLUMN_WEIGHTS, vertical_alignment="center")
            for col, name in zip(cols, DASHBOARD_COLUMNS, strict=False):
                col.write(_format_cell(row[name]))
            if cols[-1].button("🔍", key=f"case_details_{case_id}", help="Open case details"):
                show_case_detail(case_id)
