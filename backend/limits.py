"""Shared upload limits, also exposed to the frontend through /api/settings."""
import os


def positive_integer(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
        if value <= 0:
            raise ValueError
        return value
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是正整数。") from exc


MAX_PDF_MB = positive_integer("STUDY_MAX_PDF_MB", 1024)
MAX_PDF_BYTES = MAX_PDF_MB * 1024 * 1024
MAX_PDF_PAGES = positive_integer("STUDY_MAX_PDF_PAGES", 2000)
UPLOAD_CHUNK_BYTES = 1024 * 1024
