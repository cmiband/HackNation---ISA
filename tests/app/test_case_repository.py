from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import Case, CaseHistory, FileData
from app.db.repository import CaseRepository
from contracts.enums import CaseStatus, FileType


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _new_case(repo: CaseRepository) -> Case:
    return repo.add_with_application(
        Case(created_date=date(2026, 1, 1), response_deadline=date(2026, 1, 15)),
        FileData(filename="a.pdf", file_type=FileType.APPLICATION),
    )


def test_add_does_not_write_history(session):
    _new_case(CaseRepository(session))
    assert session.exec(select(CaseHistory)).all() == []


def test_update_writes_history_snapshot(session):
    repo = CaseRepository(session)
    case = _new_case(repo)
    case.status = CaseStatus.PROCESSED
    repo.update(case)

    rows = session.exec(select(CaseHistory)).all()
    assert len(rows) == 1
    assert rows[0].case_id == case.id
    assert rows[0].status == CaseStatus.PROCESSED
    assert rows[0].application_id == case.application_id


def test_update_requires_persisted_case(session):
    case = Case(created_date=date(2026, 1, 1), response_deadline=date(2026, 1, 15), application_id=1)
    with pytest.raises(ValueError):
        CaseRepository(session).update(case)
