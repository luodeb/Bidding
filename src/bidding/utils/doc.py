from __future__ import annotations

import hashlib
import io
import tempfile
import zipfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DOC_DIR = _DATA_DIR / "doc"


def _ensure_doc_dir() -> Path:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    return DOC_DIR


def extract_text_from_docx(data: bytes) -> str | None:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(parts).strip()
    return text if text else None


def extract_text_from_doc(data: bytes) -> str | None:
    """Extract text from legacy .doc (OLE2) format via antiword or textract."""
    tmp = tempfile.NamedTemporaryFile(suffix=".doc", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        import subprocess

        result = subprocess.run(
            ["antiword", tmp.name], capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        logger.debug("doc.antiword_not_installed")
    except Exception:
        logger.debug("doc.antiword_failed")
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return None


def _find_docs_in_zip(zip_data: bytes, depth: int = 0) -> list[tuple[str, bytes]]:
    if depth > 3:
        return []

    results: list[tuple[str, bytes]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_data))
    except zipfile.BadZipFile:
        return []

    for info in zf.infolist():
        if info.is_dir():
            continue

        try:
            raw = info.filename
            name = raw.encode("cp437").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            name = info.filename

        try:
            data = zf.read(info.filename)
        except (KeyError, zipfile.BadZipFile):
            try:
                for alt in zf.infolist():
                    if not alt.is_dir():
                        d = zf.read(alt)
                        h = d[:4]
                        if name.lower().endswith((".docx", ".doc")) or h == b"PK\x03\x04":
                            data = d
                            break
                else:
                    continue
            except Exception:
                continue

        lower = name.lower()
        if lower.endswith(".docx") or lower.endswith(".doc"):
            results.append((name, data))
        elif lower.endswith(".zip"):
            results.extend(_find_docs_in_zip(data, depth + 1))

    return results


def extract_text_from_zip(zip_data: bytes) -> tuple[str | None, str | None]:
    """Extract text from a ZIP that may contain DOCX/DOC files (possibly nested).

    Returns (saved_filename, extracted_text).
    The original ZIP is saved to data/doc/ for archival.
    """
    docs = _find_docs_in_zip(zip_data)
    if not docs:
        return None, None

    doc_name, doc_data = docs[0]
    for name, data in docs:
        if "公告" in name:
            doc_name, doc_data = name, data
            break

    h = hashlib.md5(zip_data).hexdigest()[:12]
    doc_dir = _ensure_doc_dir()

    if doc_name.lower().endswith(".docx"):
        saved_name = f"{h}.docx"
    else:
        saved_name = f"{h}.doc"

    saved_path = doc_dir / saved_name
    if not saved_path.exists():
        saved_path.write_bytes(doc_data)

    text = None
    if doc_name.lower().endswith(".docx"):
        try:
            text = extract_text_from_docx(doc_data)
        except Exception:
            logger.warning("doc.docx_extract_failed", name=doc_name)
    elif doc_name.lower().endswith(".doc"):
        text = extract_text_from_doc(doc_data)

    if text:
        logger.info("doc.extracted", name=doc_name, chars=len(text))
    else:
        logger.warning("doc.no_text", name=doc_name)

    return saved_name, text
