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
from app.ui.i18n import status_label
from app.ui.views.case_detail import show_case_detail
from contracts.enums import CaseStatus

COL_NO, COL_INITIALS, COL_NUMBER, COL_TOPIC = "Lp.", "Inicjały", "Numer sprawy", "Przedmiot wniosku"
COL_RECEIVED, COL_DEADLINE, COL_DAYS, COL_REPLY, COL_STATUS = (
    "Data wpływu",
    "Termin odpowiedzi",
    "Pozostało dni",
    "Data odpowiedzi",
    "Status",
)
DASHBOARD_COLUMNS = [
    COL_NO,
    COL_INITIALS,
    COL_NUMBER,
    COL_TOPIC,
    COL_RECEIVED,
    COL_DEADLINE,
    COL_DAYS,
    COL_REPLY,
    COL_STATUS,
]

TOP_CASES_LIMIT = 10

_DEADLINE_STYLES: dict[str, str] = {
    "overdue": "background-color: #fca5a5; color: #7f1d1d; font-weight: 700;",
    "today": "background-color: #fecaca; color: #991b1b; font-weight: 700;",
    "tomorrow": "background-color: #fed7aa; color: #9a3412; font-weight: 600;",
    "soon": "background-color: #fef08a; color: #854d0e; font-weight: 600;",
}


def empty_dashboard_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the dashboard schema so column headers render cleanly."""
    return pd.DataFrame(columns=DASHBOARD_COLUMNS)


def deadline_urgency(days_to_deadline: object) -> str | None:
    """Classify deadline urgency from days remaining (`None` when replied or > 3 days away)."""
    if days_to_deadline is None or days_to_deadline is pd.NA:
        return None
    if isinstance(days_to_deadline, float) and pd.isna(days_to_deadline):
        return None
    days = int(days_to_deadline)
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 3:
        return "soon"
    return None


def format_deadline_cell(deadline_value: object, days_to_deadline: object) -> tuple[str, bool]:
    """Return `(content, is_html)` for the Deadline cell with urgency highlighting when applicable."""
    text = _format_cell(deadline_value)
    urgency = deadline_urgency(days_to_deadline)
    if not text or urgency is None:
        return text, False
    style = _DEADLINE_STYLES[urgency]
    html = (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:6px;{style}">'
        f"{text}</span>"
    )
    return html, True


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
                COL_NO: idx,
                COL_INITIALS: case.assignee.initials if case.assignee is not None else "",
                COL_NUMBER: case.document_number or "",
                COL_TOPIC: case.topic or "",
                COL_RECEIVED: case.created_date,
                COL_DEADLINE: case.response_deadline,
                COL_DAYS: days_to_deadline,
                COL_REPLY: case.response_date,
                COL_STATUS: status_label(case.status),
            }
        )

    df = pd.DataFrame(rows, columns=DASHBOARD_COLUMNS)
    df[COL_DAYS] = pd.array(df[COL_DAYS], dtype="Int64")
    return df


def select_dashboard_rows(
    case_ids: Sequence[int],
    df: pd.DataFrame,
    *,
    show_all: bool,
    top_n: int = TOP_CASES_LIMIT,
) -> tuple[list[int], pd.DataFrame]:
    """Return all rows as-is when `show_all=True`, or top `top_n` ordered by nearest deadline.

    Active (unreplied) cases are prioritized ahead of already-replied cases so archived
    `Response_Sent` entries do not crowd out upcoming deadlines.
    """
    if show_all or df.empty:
        return list(case_ids), df

    order = sorted(
        range(len(df)),
        key=lambda i: (
            pd.isna(df.iloc[i][COL_DAYS]),
            df.iloc[i][COL_DEADLINE],
            i,
        ),
    )[:top_n]
    selected_ids = [case_ids[i] for i in order]
    selected_df = df.iloc[order].copy().reset_index(drop=True)
    selected_df[COL_NO] = range(1, len(selected_df) + 1)
    return selected_ids, selected_df


def load_dashboard_frame(
    *,
    session: Session | None = None,
    today: date | None = None,
) -> pd.DataFrame:
    """Query all cases from SQLite (oldest → newest) and return the dashboard DataFrame."""
    return load_dashboard_data(session=session, today=today)[1]


def case_years(cases: Sequence[Case]) -> list[int]:
    """Years of receipt present in the registry, newest first."""
    return sorted({case.created_date.year for case in cases}, reverse=True)


def load_dashboard_data(
    *,
    session: Session | None = None,
    today: date | None = None,
    year: int | None = None,
) -> tuple[list[int], pd.DataFrame]:
    """Return case ids (row order) and the dashboard DataFrame (oldest → newest), optionally one year only."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        cases = CaseRepository(db).get_all_cases()
        if year is not None:
            cases = [case for case in cases if case.created_date.year == year]
        case_ids = [case.id for case in cases if case.id is not None]
        return case_ids, build_dashboard_frame(cases, today=today)


# Relative column widths: data columns + the "Details" button column.
_COLUMN_WEIGHTS = [0.5, 0.8, 1.9, 3.4, 1.1, 1.3, 0.9, 1.1, 1.6, 0.6]


def _format_cell(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    return str(value)


def render() -> None:
    st.subheader("📊 Rejestr wniosków")
    with Session(engine) as db:
        years = case_years(CaseRepository(db).get_all_cases())
    if not years:
        st.caption("Brak spraw w rejestrze — dodaj wnioski w zakładce „Dodaj wnioski”.")
        return

    ctrl_left, ctrl_year, ctrl_right = st.columns([4, 1, 1.2], vertical_alignment="center")
    year_options: list[int | None] = [None, *years]
    year = ctrl_year.selectbox(
        "Rok",
        year_options,
        index=1 if date.today().year in years else 0,
        format_func=lambda y: "Wszystkie lata" if y is None else str(y),
        key="dashboard_year",
    )
    case_ids, df = load_dashboard_data(year=year)
    if df.empty:
        ctrl_left.caption("Brak spraw w wybranym roku.")
        return

    total_cases = len(df)
    show_all = ctrl_right.toggle("Pokaż wszystkie", value=False, key="dashboard_show_all")

    visible_ids, visible_df = select_dashboard_rows(case_ids, df, show_all=show_all)
    if show_all:
        ctrl_left.caption(
            f"Wszystkie sprawy: **{total_cases}**, od najstarszej do najnowszej.  \n"
            "Wyróżnienie terminu: 🔴 po terminie / dziś · 🟠 jutro · 🟡 do 3 dni"
        )
    else:
        ctrl_left.caption(
            f"Najpilniejsze **{len(visible_df)}** z **{total_cases}** spraw (najbliższy termin).  \n"
            "Wyróżnienie terminu: 🔴 po terminie / dziś · 🟠 jutro · 🟡 do 3 dni"
        )

    header = st.columns(_COLUMN_WEIGHTS)
    for col, name in zip(header, [*DASHBOARD_COLUMNS, ""], strict=True):
        col.markdown(f"**{name}**")

    with st.container(height=600, border=False):
        for case_id, (_, row) in zip(visible_ids, visible_df.iterrows(), strict=True):
            cols = st.columns(_COLUMN_WEIGHTS, vertical_alignment="center")
            for col, name in zip(cols, DASHBOARD_COLUMNS, strict=False):
                if name == COL_DEADLINE:
                    content, is_html = format_deadline_cell(row[COL_DEADLINE], row[COL_DAYS])
                    if is_html:
                        col.markdown(content, unsafe_allow_html=True)
                    else:
                        col.write(content)
                else:
                    col.write(_format_cell(row[name]))
            if cols[-1].button("🔍", key=f"case_details_{case_id}", help="Otwórz szczegóły sprawy"):
                show_case_detail(case_id)
