"""Tests for Stage 3 prompt rendering."""

from pipeline.problem_extractor import _build_extraction_prompt


def test_build_extraction_prompt_renders_source_title_without_format_errors():
    passages_text = "[Passage 1] (section: intro, signal: A)\nIt remains unknown why X."
    prompt = _build_extraction_prompt("AMR Review 2025", passages_text)

    # The prompt includes literal JSON braces and must render without KeyError.
    assert "Source document: AMR Review 2025" in prompt
    assert '"problems": [' in prompt
    assert '"meta": {' in prompt
    assert "{source_title}" not in prompt
    assert prompt.endswith(passages_text)
