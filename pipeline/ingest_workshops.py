"""Stage 1b: Workshop report ingestion from local PDFs."""

import logging
from pathlib import Path

import yaml

from pipeline import Source, WORKSHOPS_DIR, load_config
from pipeline.pdf_utils import extract_text_from_pdf, detect_sections

logger = logging.getLogger("collector.ingest_workshops")


def ingest_workshops(config: dict | None = None) -> list[Source]:
    """Scan data/workshops/ for PDFs and extract text from each.

    Looks for optional YAML sidecar files (same name as PDF but .yaml extension)
    for metadata (title, authors, organization, date, url).
    """
    config = config or load_config()
    workshops_dir = WORKSHOPS_DIR

    if not workshops_dir.exists():
        logger.warning("Workshops directory does not exist: %s", workshops_dir)
        return []

    pdf_files = sorted(workshops_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", workshops_dir)
        return []

    logger.info("Found %d PDF files in %s", len(pdf_files), workshops_dir)

    sources = []
    for pdf_path in pdf_files:
        source = _ingest_one(pdf_path)
        if source and source.full_text:
            sources.append(source)
        else:
            logger.warning("No text extracted from %s", pdf_path.name)

    logger.info("Ingested %d/%d workshop reports", len(sources), len(pdf_files))
    return sources


def _ingest_one(pdf_path: Path) -> Source | None:
    """Ingest a single workshop report PDF."""
    logger.info("Ingesting: %s", pdf_path.name)

    # Load optional metadata sidecar
    metadata = _load_metadata(pdf_path)

    # Generate source_id from filename
    source_id = metadata.get("source_id", pdf_path.stem)

    source = Source(
        source_id=source_id,
        source_type="workshop_report",
        title=metadata.get("title", pdf_path.stem.replace("-", " ").replace("_", " ")),
        authors=metadata.get("authors", []),
        organization=metadata.get("organization", ""),
        date_published=metadata.get("date_published", ""),
        url=metadata.get("url", ""),
        pdf_path=str(pdf_path),
    )

    # Extract text
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
    """Load metadata from a YAML sidecar file if it exists.

    Looks for a file with the same stem as the PDF but .yaml extension.
    Example: data/workshops/nih-amr-2025.pdf → data/workshops/nih-amr-2025.yaml
    """
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


