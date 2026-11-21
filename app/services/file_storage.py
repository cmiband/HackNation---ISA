"""Persist uploaded files to the host-mounted storage archive."""

from pathlib import Path, PureWindowsPath

from app.config import settings


def sanitize_filename(filename: str) -> str:
    """Return a safe base filename stripped of any directory components."""
    # Handle both POSIX and Windows separators regardless of host/container OS.
    name = PureWindowsPath(filename).name
    name = Path(name).name.strip()
    if not name or name in {".", ".."}:
        return "uploaded_file"
    return name


def unique_target_path(target_dir: Path, filename: str) -> Path:
    """Resolve a non-colliding path inside `target_dir` (e.g. `doc.pdf`, `doc_1.pdf`)."""
    safe_name = sanitize_filename(filename)
    candidate = target_dir / safe_name
    if not candidate.exists():
        return candidate

    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def save_uploaded_file(
    filename: str,
    data: bytes,
    is_application: bool,
    *,
    applications_dir: Path | None = None,
    responses_dir: Path | None = None,
) -> Path:
    """Save file bytes under applications/ (`True`) or responses/ (`False`/0) and return the path."""
    target_dir = (
        (applications_dir or settings.applications_dir)
        if is_application
        else (responses_dir or settings.responses_dir)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = unique_target_path(target_dir, filename)
    target_path.write_bytes(data)
    return target_path
