"""Shared PDF text extraction and section detection utilities."""

import logging
import re
from pathlib import Path

logger = logging.getLogger("collector.pdf_utils")

# Section header patterns for report detection
SECTION_PATTERNS = [
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?executive\s+summary\s*\n", "executive_summary"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?introduction\s*\n", "introduction"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?background\s*\n", "background"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?recommendations?\s*\n", "recommendations"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?research\s+priorities\s*\n", "research_priorities"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?(?:open\s+)?questions?\s*\n", "open_questions"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?future\s+directions?\s*\n", "future_directions"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?challenges?\s*(?:\s+and\s+opportunities)?\s*\n", "challenges"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?opportunities\s*\n", "opportunities"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?(?:key\s+)?findings?\s*\n", "findings"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?conclusions?\s*\n", "conclusion"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?(?:acknowledgements?|funding)\s*\n", "acknowledgements"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?(?:references?|bibliography)\s*\n", "references"),
    (r"(?:^|\n)\s*(?:\d+\.?\s*)?appendi(?:x|ces)\s*\n", "appendix"),
]


def extract_text_from_pdf(pdf_path: Path) -> str | None:
    """Extract text from a PDF using pymupdf."""
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text if text.strip() else None
    except Exception as e:
        logger.warning("PDF text extraction failed for %s: %s", pdf_path, e)
        return None


def detect_sections(text: str) -> dict:
    """Detect report sections via regex heuristics."""
    sections = {}
    boundaries = []
    text_lower = text.lower()

    for pattern, name in SECTION_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            boundaries.append((match.start(), match.end(), name))

    boundaries.sort(key=lambda x: x[0])

    for i, (start, end, name) in enumerate(boundaries):
        # Skip appendix, acknowledgements, and references content
        if name in ("appendix", "acknowledgements", "references"):
            continue
        if i + 1 < len(boundaries):
            next_start = boundaries[i + 1][0]
            sections[name] = text[end:next_start].strip()
        else:
            sections[name] = text[end:].strip()

    return sections
