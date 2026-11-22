from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.db.engine import init_db
from app.db.models import Department, User
from app.services.current_user import CURRENT_USER_INITIALS


def test_init_db_creates_tables_and_seeds_departments_idempotently():
    test_engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    init_db(test_engine)

    tables = set(inspect(test_engine).get_table_names())
    assert {"case", "case_history", "department", "department_request", "file_data", "user"} <= tables

    with Session(test_engine) as session:
        first_count = len(session.exec(select(Department)).all())
    assert first_count > 0

    # Calling a second time must not duplicate departments.
    init_db(test_engine)
    with Session(test_engine) as session:
        second_count = len(session.exec(select(Department)).all())
    assert second_count == first_count


def test_init_db_seeds_current_user_once():
    test_engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    init_db(test_engine)
    init_db(test_engine)

    with Session(test_engine) as session:
        users = session.exec(select(User).where(User.initials == CURRENT_USER_INITIALS)).all()
    assert len(users) == 1
    assert (users[0].first_name, users[0].last_name, users[0].initials) == ("test", "testowski", "tt")
