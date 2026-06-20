from __future__ import annotations

import asyncio
import hashlib
import tempfile
import urllib.request
from pathlib import Path

import structlog

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
PDF_DIR = _DATA_DIR / "pdf"


def _ensure_pdf_dir() -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    return PDF_DIR


def _url_to_filename(url: str) -> str:
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"{h}.pdf"


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text())
        return "\n".join(parts).strip()
    finally:
        doc.close()


async def download_pdf(url: str) -> Path | None:
    dest = _ensure_pdf_dir() / _url_to_filename(url)
    if dest.exists():
        return dest
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlretrieve(url, str(dest))
        )
        logger.info("pdf.downloaded", path=str(dest), url=url[:80])
        return dest
    except Exception:
        logger.exception("pdf.download_failed", url=url[:80])
        dest.unlink(missing_ok=True)
        return None


async def download_and_extract_pdf(url: str) -> tuple[str | None, str | None]:
    """Download PDF and extract text. Returns (pdf_filename, text)."""
    pdf_path = await download_pdf(url)
    if not pdf_path:
        return None, None
    try:
        text = extract_text_from_pdf(pdf_path)
        filename = pdf_path.name
        if text:
            logger.info("pdf.extracted", chars=len(text), url=url[:80])
            return filename, text
        logger.warning("pdf.empty", url=url[:80])
        return filename, None
    except Exception:
        logger.exception("pdf.extract_failed", url=url[:80])
        return pdf_path.name, None
