import time
from pathlib import Path


def cleanup_old_files(directory: Path, hours: int = 1):
    """Remove files older than the configured number of hours."""
    if not directory.exists():
        return

    current_time = time.time()
    for file_path in directory.glob("*"):
        if file_path.is_file():
            file_age = current_time - file_path.stat().st_mtime
            if file_age > hours * 3600:
                try:
                    file_path.unlink()
                except OSError:
                    pass


def ensure_directories(storage_dir: Path):
    """Ensure required local storage directories exist."""
    for dir_path in [
        storage_dir / "uploads",
        storage_dir / "reports",
        storage_dir / "vector",
    ]:
        dir_path.mkdir(parents=True, exist_ok=True)
