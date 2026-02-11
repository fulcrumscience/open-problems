"""Tests for the open problem signal filter."""

import json
from pathlib import Path

import pytest

from pipeline import Source
from pipeline.signal_filter import SignalFilter, _split_paragraphs

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def signal_filter():
    return SignalFilter()


@pytest.fixture
def sample_texts():
    with open(FIXTURES_DIR / "sample_workshop_text.json") as f:
        return json.load(f)


def _make_source(text: str, source_id: str = "test") -> Source:
    return Source(
        source_id=source_id,
        source_type="workshop_report",
        full_text=text,
    )


class TestSignalFilter:
    def test_category_a_remains_unknown(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_a_remains_unknown")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        p = source.signal_passages[0]
        assert p["signal_category"] == "A"
        assert "it remains unknown" in p["matched_phrases"]

    def test_category_a_critical_gap(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_a_critical_gap")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "A"

    def test_category_b_promising_direction(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_b_promising_direction")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "B"

    def test_category_b_underexplored(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_b_underexplored")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "B"

    def test_category_c_research_priority(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_c_research_priority")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "C"

    def test_category_c_bottleneck(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "cat_c_bottleneck")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "C"

    def test_negative_filter_rejects(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "negative_funding")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 0

    def test_no_signal_background(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "no_signal_background")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 0

    def test_short_paragraph_skipped(self, signal_filter, sample_texts):
        case = next(c for c in sample_texts if c["id"] == "short_paragraph_skip")
        source = _make_source(case["text"])
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 0

    def test_category_a_takes_priority_over_b(self, signal_filter):
        """A paragraph matching both A and B should be classified as A."""
        text = "It remains unknown whether this approach would benefit from additional validation. The mechanism is largely unexplored and future work should address this gap."
        source = _make_source(text)
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["signal_category"] == "A"

    def test_section_tracking(self, signal_filter):
        """Passages should track which section they came from."""
        source = Source(
            source_id="test-sections",
            source_type="workshop_report",
            sections={
                "recommendations": "Future research should focus on developing new tools for genome engineering. This is a critical gap in the field.",
                "background": "CRISPR was discovered in the early 2000s as a bacterial immune system.",
            },
        )
        signal_filter.filter_source(source)

        assert len(source.signal_passages) == 1
        assert source.signal_passages[0]["section"] == "recommendations"

    def test_filter_sources_returns_only_with_signals(self, signal_filter):
        sources = [
            _make_source("It remains unknown how horizontal gene transfer is regulated in polymicrobial biofilm communities under stress conditions.", source_id="has-signal"),
            _make_source("CRISPR-Cas9 was first characterized as a programmable genome editing tool in 2012 by Doudna and Charpentier.", source_id="no-signal"),
        ]
        result = signal_filter.filter_sources(sources)

        assert len(result) == 1
        assert result[0].source_id == "has-signal"


class TestSplitParagraphs:
    def test_double_newline(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_whitespace_between(self):
        text = "First paragraph.\n  \n  \nSecond paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_empty_text(self):
        assert _split_paragraphs("") == []

    def test_single_paragraph(self):
        text = "Just one paragraph with no blank lines."
        result = _split_paragraphs(text)
        assert len(result) == 1
