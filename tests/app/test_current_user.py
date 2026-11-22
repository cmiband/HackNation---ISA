from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import User
from app.services.current_user import get_or_create_current_user


def test_get_or_create_current_user_creates_only_when_missing():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = get_or_create_current_user(session)
        second = get_or_create_current_user(session)
        users = session.exec(select(User)).all()

    assert first.id is not None
    assert first.id == second.id
    assert len(users) == 1
    assert (first.first_name, first.last_name, first.initials) == ("test", "testowski", "tt")
