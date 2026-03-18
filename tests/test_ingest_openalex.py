"""Tests for the OpenAlex energy/sustainability ingestion module."""

import math

import pytest

from pipeline import Source
from pipeline.ingest_openalex import (
    _reconstruct_abstract,
    _extract_openalex_id,
    _build_source_from_work,
    compute_impact_score,
)
from pipeline.output import (
    init_db, upsert_source, upsert_problem, upsert_sub_question,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_work():
    """A realistic OpenAlex work dict for a hydrogen review article."""
    return {
        "id": "https://openalex.org/W4391234567",
        "doi": "https://doi.org/10.1016/j.ijhydene.2025.01.001",
        "title": "Recent advances in green hydrogen production via water splitting",
        "display_name": "Recent advances in green hydrogen production via water splitting",
        "publication_year": 2025,
        "cited_by_count": 42,
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A1", "display_name": "Jane Smith"},
                "author_position": "first",
                "institutions": [],
            },
            {
                "author": {"id": "https://openalex.org/A2", "display_name": "John Doe"},
                "author_position": "last",
                "institutions": [],
            },
        ],
        "primary_location": {
            "source": {
                "id": "https://openalex.org/S48860480",
                "display_name": "International Journal of Hydrogen Energy",
                "issn_l": "0360-3199",
            },
            "is_oa": True,
        },
        "abstract_inverted_index": {
            "Green": [0],
            "hydrogen": [1, 14],
            "production": [2, 15],
            "via": [3],
            "water": [4],
            "splitting": [5],
            "remains": [6],
            "a": [7, 12],
            "key": [8],
            "challenge": [9],
            "for": [10],
            "the": [11],
            "clean": [13],
            "economy.": [16],
        },
    }


@pytest.fixture
def sample_journal_impact():
    return {
        "display_name": "International Journal of Hydrogen Energy",
        "2yr_mean_citedness": 5.8,
        "h_index": 280,
    }


@pytest.fixture
def sample_work_no_abstract(sample_work):
    work = sample_work.copy()
    work["abstract_inverted_index"] = None
    return work


@pytest.fixture
def sample_work_no_doi(sample_work):
    work = sample_work.copy()
    work["doi"] = None
    return work


@pytest.fixture
def sample_work_many_authors(sample_work):
    work = sample_work.copy()
    work["authorships"] = [
        {"author": {"display_name": f"Author {i}"}} for i in range(15)
    ]
    return work


# ── _reconstruct_abstract tests ──────────────────────────────────────

class TestReconstructAbstract:
    def test_simple(self):
        idx = {"Hello": [0], "world": [1]}
        assert _reconstruct_abstract(idx) == "Hello world"

    def test_repeated_words(self):
        idx = {"the": [0, 2], "cat": [1], "sat": [3]}
        assert _reconstruct_abstract(idx) == "the cat the sat"

    def test_empty_index(self):
        assert _reconstruct_abstract({}) == ""

    def test_none_index(self):
        assert _reconstruct_abstract(None) == ""

    def test_realistic_abstract(self, sample_work):
        text = _reconstruct_abstract(sample_work["abstract_inverted_index"])
        assert text.startswith("Green hydrogen production")
        assert "clean" in text
        assert "economy." in text

    def test_single_word(self):
        assert _reconstruct_abstract({"Hello": [0]}) == "Hello"

    def test_out_of_order_positions(self):
        idx = {"world": [1], "Hello": [0]}
        assert _reconstruct_abstract(idx) == "Hello world"


# ── _extract_openalex_id tests ───────────────────────────────────────

class TestExtractOpenalexId:
    def test_standard_url(self):
        assert _extract_openalex_id("https://openalex.org/W123") == "W123"

    def test_trailing_slash(self):
        assert _extract_openalex_id("https://openalex.org/W123/") == "W123"

    def test_source_id(self):
        assert _extract_openalex_id("https://openalex.org/S48860480") == "S48860480"


# ── compute_impact_score tests ───────────────────────────────────────

class TestComputeImpactScore:
    def test_high_citations_high_journal(self):
        score = compute_impact_score(100, 5.0)
        assert score > 0
        assert score == pytest.approx(math.log1p(100) * 6.0, rel=1e-3)

    def test_zero_citations(self):
        score = compute_impact_score(0, 5.0)
        assert score == 0.0

    def test_zero_journal_impact(self):
        score = compute_impact_score(50, 0.0)
        assert score == pytest.approx(math.log1p(50), rel=1e-3)

    def test_both_zero(self):
        assert compute_impact_score(0, 0.0) == 0.0

    def test_high_citations_boost(self):
        low = compute_impact_score(1, 3.0)
        high = compute_impact_score(100, 3.0)
        assert high > low

    def test_high_journal_boost(self):
        low = compute_impact_score(10, 1.0)
        high = compute_impact_score(10, 10.0)
        assert high > low


# ── _build_source_from_work tests ────────────────────────────────────

class TestBuildSourceFromWork:
    def test_source_id_format(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.source_id == "openalex-W4391234567"

    def test_source_type(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.source_type == "openalex_review"

    def test_title(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert "green hydrogen" in src.title.lower()

    def test_authors(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.authors == ["Jane Smith", "John Doe"]

    def test_organization_is_journal(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.organization == "International Journal of Hydrogen Energy"

    def test_url_prefers_doi(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.url.startswith("https://doi.org/")

    def test_url_fallback_to_openalex(self, sample_work_no_doi, sample_journal_impact):
        src = _build_source_from_work(sample_work_no_doi, "Hydrogen", sample_journal_impact)
        assert "openalex.org" in src.url

    def test_abstract_in_full_text(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert "hydrogen" in src.full_text.lower()
        assert len(src.full_text) > 20

    def test_sections_has_abstract(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert "abstract" in src.sections
        assert src.sections["abstract"] == src.full_text

    def test_no_abstract_returns_none(self, sample_work_no_abstract, sample_journal_impact):
        result = _build_source_from_work(sample_work_no_abstract, "Hydrogen", sample_journal_impact)
        assert result is None

    def test_authors_capped_at_10(self, sample_work_many_authors, sample_journal_impact):
        src = _build_source_from_work(sample_work_many_authors, "Test", sample_journal_impact)
        assert len(src.authors) == 10

    def test_metadata_has_cited_by_count(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.metadata["cited_by_count"] == 42

    def test_metadata_has_journal_impact(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        assert src.metadata["journal_2yr_citedness"] == 5.8
        assert src.metadata["journal_h_index"] == 280

    def test_metadata_has_impact_score(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        expected = compute_impact_score(42, 5.8)
        assert src.metadata["impact_score"] == round(expected, 3)

    def test_metadata_has_topic_label(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Hydrogen energy", sample_journal_impact)
        assert src.metadata["topic_label"] == "Hydrogen energy"

    def test_no_journal_impact(self, sample_work):
        src = _build_source_from_work(sample_work, "Test", None)
        assert src.metadata["journal_2yr_citedness"] == 0.0
        assert src.metadata["impact_score"] == round(
            compute_impact_score(42, 0.0), 3,
        )

    def test_date_published(self, sample_work, sample_journal_impact):
        src = _build_source_from_work(sample_work, "Test", sample_journal_impact)
        assert src.date_published == "2025"

    def test_missing_cited_by_count(self, sample_work, sample_journal_impact):
        sample_work["cited_by_count"] = None
        src = _build_source_from_work(sample_work, "Test", sample_journal_impact)
        assert src.metadata["cited_by_count"] == 0
        assert src.metadata["impact_score"] == 0.0


# ── Output integration tests ─────────────────────────────────────────

class TestOutputIntegration:
    @pytest.fixture
    def db_conn(self, tmp_path):
        conn = init_db(tmp_path / "test.db")
        yield conn
        conn.close()

    def test_openalex_source_upserts(self, db_conn, sample_work, sample_journal_impact):
        source = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        upsert_source(db_conn, source)
        db_conn.commit()

        row = db_conn.execute(
            "SELECT id, source_type, title, organization FROM sources WHERE id = ?",
            (source.source_id,),
        ).fetchone()
        assert row is not None
        assert row["source_type"] == "openalex_review"
        assert "hydrogen" in row["title"].lower()
        assert "Hydrogen Energy" in row["organization"]

    def test_openalex_problem_upserts(self, db_conn, sample_work, sample_journal_impact):
        source = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        upsert_source(db_conn, source)

        problem = {
            "problem_statement": "Green hydrogen production at scale remains unsolved",
            "domain": "energy",
            "subdomain": "hydrogen production",
            "scope": "broad",
            "sub_questions": [
                {
                    "question": "How can electrolysis efficiency be improved?",
                    "evidence_needed": "Benchmarks on novel catalyst materials",
                    "disciplines": ["electrochemistry", "materials science"],
                    "estimated_complexity": "complex",
                }
            ],
            "original_text": "Green hydrogen production via water splitting remains a key challenge",
        }
        provenance = {
            "original_text": problem["original_text"],
            "deep_link": source.url,
            "section_label": "Abstract",
        }
        problem_id = upsert_problem(db_conn, "test-run", source.source_id, problem, provenance)
        db_conn.commit()
        assert problem_id is not None

        row = db_conn.execute(
            "SELECT domain, subdomain FROM open_problems WHERE id = ?",
            (problem_id,),
        ).fetchone()
        assert row["domain"] == "energy"

    def test_sub_questions_upsert(self, db_conn, sample_work, sample_journal_impact):
        source = _build_source_from_work(sample_work, "Hydrogen", sample_journal_impact)
        upsert_source(db_conn, source)

        problem = {
            "problem_statement": "Test problem",
            "domain": "energy",
            "sub_questions": [
                {
                    "question": "Sub Q1",
                    "evidence_needed": "Evidence 1",
                    "disciplines": ["chemistry"],
                    "estimated_complexity": "medium",
                },
                {
                    "question": "Sub Q2",
                    "evidence_needed": "Evidence 2",
                    "disciplines": ["physics"],
                    "estimated_complexity": "complex",
                },
            ],
        }
        problem_id = upsert_problem(db_conn, "test-run", source.source_id, problem, None)
        for sq in problem["sub_questions"]:
            upsert_sub_question(db_conn, problem_id, sq, source.source_id)
        db_conn.commit()

        rows = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM sub_questions WHERE problem_id = ?",
            (problem_id,),
        ).fetchone()
        assert rows["cnt"] == 2
