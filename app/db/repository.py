"""Repository classes for database operations.

Each repository wraps one SQLModel table and takes a ``Session`` (one per thread /
Streamlit session, see ``app.db.engine.get_session``). Every write commits and
refreshes the returned objects, so callers get persisted rows with ids.

Business rules (status transitions, writing ``CaseHistory`` snapshots on every
``Case`` change) belong in ``app/services/registry.py``, not here.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db.models import Case, CaseHistory, Department, DepartmentRequest, FileData, User
from contracts.enums import FileType

DEPARTMENTS_JSON = Path(__file__).resolve().parents[2] / "data" / "departments.json"


class CaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def is_empty(self) -> bool:
        return self.session.exec(select(Case.id).limit(1)).first() is None

    def add(self, case: Case) -> Case:
        self.session.add(case)
        self.session.commit()
        self.session.refresh(case)
        self.session.refresh(case.application)
        return case

    def add_with_application(self, case: Case, application: FileData) -> Case:
        """Insert a new case and its application file in one transaction.

        ``application`` must be unsaved. It is linked through the relationship, so
        SQLAlchemy inserts ``file_data`` first and fills ``case.application_id``.
        """
        if application.file_type != FileType.APPLICATION:
            raise ValueError("application must have file_type FileType.APPLICATION.")
        case.application = application
        self.session.add(case)
        self.session.commit()
        self.session.refresh(case)
        self.session.refresh(application)
        return case

    def add_case_with_application_and_response(
        self, case: Case, application: FileData, response: FileData
    ) -> Case:
        """Insert a new case with both its application and response files in one transaction.

        Both files must be unsaved. They are linked through the relationships, so SQLAlchemy
        inserts ``file_data`` first and fills ``case.application_id`` / ``case.response_id``.
        """
        if application.file_type != FileType.APPLICATION:
            raise ValueError("application must have file_type FileType.APPLICATION.")
        if response.file_type != FileType.RESPONSE:
            raise ValueError("response must have file_type FileType.RESPONSE.")
        case.application = application
        case.response = response
        self.session.add(case)
        self.session.commit()
        self.session.refresh(case)
        self.session.refresh(application)
        self.session.refresh(response)
        return case

    def add_all(self, cases: Sequence[Case]) -> list[Case]:
        self.session.add_all(cases)
        self.session.commit()
        for case in cases:
            self.session.refresh(case)
            self.session.refresh(case.application)
        return list(cases)

    def update(self, case: Case) -> Case:
        """Persist changes made to an already stored case and write a ``CaseHistory`` snapshot."""
        if case.id is None:
            raise ValueError("Cannot update a case that has not been added yet.")
        self.session.add(case)
        self.session.add(CaseHistory.snapshot(case))
        self.session.commit()
        self.session.refresh(case)
        return case

    def get_all_cases(self) -> list[Case]:
        """Return all cases ordered oldest → newest with assignee eager-loaded."""
        statement = (
            select(Case)
            .options(selectinload(Case.assignee))
            .order_by(Case.created_date, Case.id)
        )
        return list(self.session.exec(statement).all())

    def get_cases_by_assignee_id(self, assignee_id: int) -> list[Case]:
        statement = (
            select(Case)
            .where(Case.assignee_id == assignee_id)
            .order_by(Case.created_date, Case.id)
        )
        return list(self.session.exec(statement).all())

    def get_case_by_id(self, case_id: int) -> Case | None:
        return self.session.get(Case, case_id)


class DepartmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load_departments(self, path: Path = DEPARTMENTS_JSON) -> list[Department]:
        """Seed departments from ``path`` (code, name, responsibilities).

        Inserts only when the ``department`` table is empty, so it is safe to call on
        every startup. Returns the inserted rows (empty list if nothing was inserted).
        """
        if self.session.exec(select(Department.id).limit(1)).first() is not None:
            return []
        entries = json.loads(path.read_text(encoding="utf-8"))
        departments = [
            Department(
                code=entry["code"],
                name=entry["name"],
                responsibilities=entry["responsibilities"],
            )
            for entry in entries
        ]
        self.session.add_all(departments)
        self.session.commit()
        for department in departments:
            self.session.refresh(department)
        return departments

    def add(self, department: Department) -> Department:
        self.session.add(department)
        self.session.commit()
        self.session.refresh(department)
        return department

    def get_by_id(self, department_id: int) -> Department | None:
        return self.session.get(Department, department_id)

    def get_by_codes(self, codes: Sequence[str]) -> dict[str, Department]:
        """Return departments with the given codes, keyed by code (unknown codes are left out)."""
        if not codes:
            return {}
        statement = select(Department).where(Department.code.in_(list(codes)))
        return {department.code: department for department in self.session.exec(statement).all()}


class FileDataRepository:
    """``FileData`` is immutable once created, so there is no update."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, file_data: FileData) -> FileData:
        self.session.add(file_data)
        self.session.commit()
        self.session.refresh(file_data)
        return file_data

    def add_all(self, files: Sequence[FileData]) -> list[FileData]:
        self.session.add_all(files)
        self.session.commit()
        for file_data in files:
            self.session.refresh(file_data)
        return list(files)

    def get_by_id(self, file_id: int) -> FileData | None:
        return self.session.get(FileData, file_id)


class DepartmentRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, request: DepartmentRequest) -> DepartmentRequest:
        self.session.add(request)
        self.session.commit()
        self.session.refresh(request)
        return request

    def update(self, request: DepartmentRequest) -> DepartmentRequest:
        """Persist changes made to an already stored department request."""
        if request.id is None:
            raise ValueError("Cannot update a department request that has not been added yet.")
        self.session.add(request)
        self.session.commit()
        self.session.refresh(request)
        return request

    def get_by_id(self, request_id: int) -> DepartmentRequest | None:
        return self.session.get(DepartmentRequest, request_id)

    def delete(self, request: DepartmentRequest) -> None:
        self.session.delete(request)
        self.session.commit()

    def get_dep_requests_by_case_id(self, case_id: int) -> list[DepartmentRequest]:
        statement = (
            select(DepartmentRequest)
            .where(DepartmentRequest.case_id == case_id)
            .order_by(DepartmentRequest.id)
        )
        return list(self.session.exec(statement).all())


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_initials(self, initials: str) -> User | None:
        return self.session.exec(select(User).where(User.initials == initials)).first()

    def get_or_create(self, *, first_name: str, last_name: str, initials: str) -> User:
        """Return the user with ``initials``; insert it only if no such user exists."""
        user = self.get_by_initials(initials)
        if user is None:
            user = self.add(User(first_name=first_name, last_name=last_name, initials=initials))
        return user


class CaseHistoryRepository:
    """``CaseHistory`` rows are never updated, so only ``add`` exists."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, history: CaseHistory) -> CaseHistory:
        self.session.add(history)
        self.session.commit()
        self.session.refresh(history)
        return history
