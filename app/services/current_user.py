"""Hardcoded "current user" for the MVP (no login yet).

``init_db()`` seeds this user after the archive load; the UI caches the id (see
``app/ui/current_user.py``) and uses it as ``assignee_id`` for newly created cases.
"""

from sqlmodel import Session

from app.db.models import User
from app.db.repository import UserRepository

CURRENT_USER_FIRST_NAME = "test"
CURRENT_USER_LAST_NAME = "testowski"
CURRENT_USER_INITIALS = "tt"


def get_or_create_current_user(session: Session) -> User:
    """Return the current user (matched by initials), creating it only if it does not exist."""
    return UserRepository(session).get_or_create(
        first_name=CURRENT_USER_FIRST_NAME,
        last_name=CURRENT_USER_LAST_NAME,
        initials=CURRENT_USER_INITIALS,
    )
