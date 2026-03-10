"""Infrastructure utility -- document parsing for PDF, DOCX, and TXT files.

Supports:
  - PDF via pypdf
  - DOCX via python-docx
  - TXT via direct read
  - Auto-detection based on content type or filename extension
"""

import io

import structlog

logger = structlog.get_logger(__name__)


def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        logger.error("document_parser.pdf.import_error", msg="pypdf not installed")
        raise ValueError("PDF parsing requires 'pypdf' package. Install with: pip install pypdf")
    except Exception as exc:
        logger.error("document_parser.pdf.error", error=str(exc))
        raise ValueError(f"Failed to parse PDF: {exc}")


def parse_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)
    except ImportError:
        logger.error("document_parser.docx.import_error", msg="python-docx not installed")
        raise ValueError("DOCX parsing requires 'python-docx' package. Install with: pip install python-docx")
    except Exception as exc:
        logger.error("document_parser.docx.error", error=str(exc))
        raise ValueError(f"Failed to parse DOCX: {exc}")


def parse_text(file_bytes: bytes) -> str:
    """Extract text from plain text bytes."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("latin-1")
        except Exception as exc:
            raise ValueError(f"Failed to decode text file: {exc}")


# Map of content types / extensions to parser functions
_PARSERS = {
    "application/pdf": parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    "text/plain": parse_text,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".txt": parse_text,
    ".text": parse_text,
    ".md": parse_text,
    ".csv": parse_text,
}


def parse_document(
    file_bytes: bytes,
    filename: str = "",
    content_type: str = "",
) -> str:
    """Auto-detect and parse a document.

    Tries content_type first, then falls back to filename extension.
    Returns the extracted plain text.
    """
    # Try content type first
    if content_type and content_type in _PARSERS:
        return _PARSERS[content_type](file_bytes)

    # Fall back to extension
    if filename:
        ext = ""
        dot_idx = filename.rfind(".")
        if dot_idx >= 0:
            ext = filename[dot_idx:].lower()
        if ext in _PARSERS:
            return _PARSERS[ext](file_bytes)

    raise ValueError(
        f"Unsupported file type: content_type='{content_type}', filename='{filename}'. "
        f"Supported: PDF, DOCX, TXT"
    )
