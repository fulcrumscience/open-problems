"""Stage 2: Open problem signal filter for source text passages."""

import logging
import re

from pipeline import Source, load_signal_phrases

logger = logging.getLogger("collector.signal_filter")


class SignalFilter:
    """Regex-based passage filter with configurable phrase categories.

    Unlike the hypothesis scanner's filter (which does pass/fail on whole abstracts),
    this filter operates on individual paragraphs within a document and collects
    all matching passages with their context.
    """

    def __init__(self, phrases: dict | None = None):
        phrases = phrases or load_signal_phrases()

        # Pre-compile patterns (case-insensitive)
        self.cat_a_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in phrases.get("category_a", [])
        ]
        self.cat_b_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in phrases.get("category_b", [])
        ]
        self.cat_c_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in phrases.get("category_c", [])
        ]
        self.cat_d_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in phrases.get("category_d", [])
        ]
        self.negative_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in phrases.get("negative_filters", [])
        ]

    def _match_category(self, text: str, patterns: list) -> list[str]:
        """Return list of matched phrase strings."""
        matched = []
        for pat in patterns:
            if pat.search(text):
                matched.append(re.sub(r"\\(.)", r"\1", pat.pattern))
        return matched

    def _has_negative(self, text: str) -> bool:
        """Check if text matches any negative filter."""
        return any(pat.search(text) for pat in self.negative_patterns)

    def _classify_paragraph(self, paragraph: str) -> tuple[str | None, list[str]]:
        """Classify a paragraph and return (category, matched_phrases) or (None, []).

        Priority: A > C > B. A single match in any category is sufficient.
        """
        if self._has_negative(paragraph):
            return None, []

        a_matches = self._match_category(paragraph, self.cat_a_patterns)
        if a_matches:
            return "A", a_matches

        d_matches = self._match_category(paragraph, self.cat_d_patterns)
        if d_matches:
            return "D", d_matches

        c_matches = self._match_category(paragraph, self.cat_c_patterns)
        if c_matches:
            return "C", c_matches

        b_matches = self._match_category(paragraph, self.cat_b_patterns)
        if b_matches:
            return "B", b_matches

        return None, []

    def filter_source(self, source: Source) -> Source:
        """Find signal passages in a source document.

        Scans each paragraph in every section (or full text if no sections).
        Populates source.signal_passages with matching passages.
        """
        source.signal_passages = []

        if source.sections:
            for section_name, section_text in source.sections.items():
                self._scan_text(source, section_text, section_name)
        elif source.full_text:
            self._scan_text(source, source.full_text, "full_text")

        logger.debug("Source %s: %d signal passages (A=%d, B=%d, C=%d, D=%d)",
                      source.source_id, len(source.signal_passages),
                      sum(1 for p in source.signal_passages if p["signal_category"] == "A"),
                      sum(1 for p in source.signal_passages if p["signal_category"] == "B"),
                      sum(1 for p in source.signal_passages if p["signal_category"] == "C"),
                      sum(1 for p in source.signal_passages if p["signal_category"] == "D"))

        return source

    def _scan_text(self, source: Source, text: str, section_name: str) -> None:
        """Scan text for signal passages and append to source.signal_passages."""
        paragraphs = _split_paragraphs(text)

        for paragraph in paragraphs:
            if len(paragraph.strip()) < 50:  # Skip very short paragraphs
                continue

            category, matched_phrases = self._classify_paragraph(paragraph)
            if category:
                source.signal_passages.append({
                    "signal_category": category,
                    "matched_phrases": matched_phrases,
                    "context_text": paragraph.strip(),
                    "section": section_name,
                })

    def filter_sources(self, sources: list[Source]) -> list[Source]:
        """Filter all sources, returning those with at least one signal passage."""
        for source in sources:
            self.filter_source(source)

        with_signals = [s for s in sources if s.signal_passages]
        total_passages = sum(len(s.signal_passages) for s in with_signals)

        logger.info(
            "Signal filter: %d/%d sources have signals (%d total passages)",
            len(with_signals), len(sources), total_passages,
        )

        # Category breakdown
        a_count = sum(1 for s in with_signals for p in s.signal_passages if p["signal_category"] == "A")
        b_count = sum(1 for s in with_signals for p in s.signal_passages if p["signal_category"] == "B")
        c_count = sum(1 for s in with_signals for p in s.signal_passages if p["signal_category"] == "C")
        d_count = sum(1 for s in with_signals for p in s.signal_passages if p["signal_category"] == "D")
        logger.info("  Category A: %d, B: %d, C: %d, D: %d", a_count, b_count, c_count, d_count)

        return with_signals


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs on blank lines or double newlines."""
    # Split on two or more newlines (possibly with whitespace between)
    paragraphs = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paragraphs if p.strip()]
