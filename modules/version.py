"""Read the release version shipped with the application."""
from pathlib import Path


def get_version() -> str:
    version_path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8").strip() or "0.0.0-dev"
    except FileNotFoundError:
        return "0.0.0-dev"
