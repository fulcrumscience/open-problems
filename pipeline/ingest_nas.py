"""Stage 1c: National Academies (NAS) report ingestion from local PDFs.

NAS Consensus Studies PDFs must be downloaded manually from
nationalacademies.org (login required). Place them in data/nas_reports/
with optional YAML sidecar files for metadata.

This module follows the same pattern as ingest_workshops.py.
"""

import logging
from pathlib import Path

import yaml

from pipeline import Source, DATA_DIR, load_config
from pipeline.pdf_utils import extract_text_from_pdf, detect_sections

logger = logging.getLogger("collector.ingest_nas")

NAS_DIR = DATA_DIR / "nas_reports"


def ingest_nas_reports(config: dict | None = None) -> list[Source]:
    """Scan data/nas_reports/ for PDFs and extract text from each.

    Looks for optional YAML sidecar files (same name as PDF but .yaml extension)
    for metadata (title, authors, organization, date, url).
    """
    config = config or load_config()
    nas_dir = Path(config.get("sources", {}).get("nas_reports", {}).get("data_dir", str(NAS_DIR)))

    if not nas_dir.is_absolute():
        nas_dir = DATA_DIR / nas_dir

    if not nas_dir.exists():
        nas_dir.mkdir(parents=True, exist_ok=True)
        logger.warning("NAS reports directory created (empty): %s", nas_dir)
        logger.warning("Download NAS PDFs from nationalacademies.org and place them here.")
        return []

    pdf_files = sorted(nas_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", nas_dir)
        return []

    logger.info("Found %d PDF files in %s", len(pdf_files), nas_dir)

    sources = []
    for pdf_path in pdf_files:
        source = _ingest_one(pdf_path)
        if source and source.full_text:
            sources.append(source)
        else:
            logger.warning("No text extracted from %s", pdf_path.name)

    logger.info("Ingested %d/%d NAS reports", len(sources), len(pdf_files))
    return sources


def _ingest_one(pdf_path: Path) -> Source | None:
    """Ingest a single NAS report PDF."""
    logger.info("Ingesting: %s", pdf_path.name)

    metadata = _load_metadata(pdf_path)
    source_id = metadata.get("source_id", f"nas-{pdf_path.stem}")

    source = Source(
        source_id=source_id,
        source_type="nas_report",
        title=metadata.get("title", pdf_path.stem.replace("-", " ").replace("_", " ")),
        authors=metadata.get("authors", []),
        organization=metadata.get("organization", "National Academies"),
        date_published=metadata.get("date_published", ""),
        url=metadata.get("url", ""),
        pdf_path=str(pdf_path),
    )

    text = extract_text_from_pdf(pdf_path)
    if not text:
        return None

    source.full_text = text
    source.sections = detect_sections(text)

    if source.sections:
        logger.info("  Detected %d sections: %s",
                     len(source.sections), ", ".join(source.sections.keys()))
    else:
        logger.info("  No sections detected, will use full text")

    return source


def _load_metadata(pdf_path: Path) -> dict:
    """Load metadata from a YAML sidecar file if it exists."""
    yaml_path = pdf_path.with_suffix(".yaml")
    if not yaml_path.exists():
        return {}

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to load metadata from %s: %s", yaml_path, e)
        return {}
