"""Tests for the SQLite output module."""

import json
from pathlib import Path

import pytest

from pipeline import Source
from pipeline.output import (
    init_db, upsert_source, upsert_problem, upsert_sub_question,
    record_pipeline_run, export_json_feed,
)


@pytest.fixture
def db_conn(tmp_path):
    conn = init_db(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def sample_source():
    return Source(
        source_id="nih-workshop-amr-2025",
        source_type="workshop_report",
        title="AMR Workshop Report 2025",
        authors=["Smith, J.", "Jones, A."],
        organization="NIH/NIAID",
        date_published="2025-06-15",
        url="https://example.com/report.pdf",
        signal_passages=[
            {"signal_category": "A", "matched_phrases": ["it remains unknown"],
             "context_text": "It remains unknown...", "section": "recommendations"},
            {"signal_category": "C", "matched_phrases": ["research priority"],
             "context_text": "This is a research priority...", "section": "executive_summary"},
        ],
    )


@pytest.fixture
def sample_problem():
    return {
        "problem_statement": "The substrate specificity of serine integrases remains poorly characterized",
        "domain": "protein engineering",
        "subdomain": "site-specific recombination",
        "scope": "medium",
        "sub_questions": [
            {
                "question": "Which residues determine att site preference?",
                "evidence_needed": "Mutagenesis study with integration assays",
                "disciplines": ["protein biochemistry", "molecular biology"],
                "estimated_complexity": "medium",
            },
            {
                "question": "Do different orthologs show distinct promiscuity profiles?",
                "evidence_needed": "Comparative in vitro integration assay",
                "disciplines": ["comparative biochemistry"],
                "estimated_complexity": "medium",
            },
        ],
        "original_text": "The substrate specificity...",
        "related_keywords": ["serine integrase", "Bxb1", "att site"],
        "notes": "",
    }


class TestInitDb:
    def test_creates_tables(self, db_conn):
        tables = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {t["name"] for t in tables}
        assert "sources" in names
        assert "open_problems" in names
        assert "sub_questions" in names
        assert "pipeline_runs" in names
        assert "run_problems" in names

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()


class TestUpsertSource:
    def test_insert_source(self, db_conn, sample_source):
        upsert_source(db_conn, sample_source)
        db_conn.commit()

        row = db_conn.execute("SELECT * FROM sources WHERE id = ?",
                              (sample_source.source_id,)).fetchone()
        assert row is not None
        assert row["title"] == "AMR Workshop Report 2025"
        assert row["organization"] == "NIH/NIAID"
        assert row["signal_hits"] == 2
        assert json.loads(row["authors"]) == ["Smith, J.", "Jones, A."]

    def test_upsert_replaces(self, db_conn, sample_source):
        upsert_source(db_conn, sample_source)
        sample_source.title = "Updated Title"
        upsert_source(db_conn, sample_source)
        db_conn.commit()

        row = db_conn.execute("SELECT * FROM sources WHERE id = ?",
                              (sample_source.source_id,)).fetchone()
        assert row["title"] == "Updated Title"


class TestUpsertProblem:
    def test_insert_problem(self, db_conn, sample_source, sample_problem):
        upsert_source(db_conn, sample_source)
        problem_id = upsert_problem(db_conn, "run1", sample_source.source_id, sample_problem)
        db_conn.commit()

        assert problem_id > 0
        row = db_conn.execute("SELECT * FROM open_problems WHERE id = ?", (problem_id,)).fetchone()
        assert row["domain"] == "protein engineering"
        assert row["scope"] == "medium"
        assert row["mention_count"] == 1

    def test_dedup_merges_sources(self, db_conn, sample_source, sample_problem):
        upsert_source(db_conn, sample_source)
        pid1 = upsert_problem(db_conn, "run1", "source-a", sample_problem)
        pid2 = upsert_problem(db_conn, "run1", "source-b", sample_problem)
        db_conn.commit()

        assert pid1 == pid2
        row = db_conn.execute("SELECT * FROM open_problems WHERE id = ?", (pid1,)).fetchone()
        assert row["mention_count"] == 2
        source_ids = json.loads(row["source_ids"])
        assert "source-a" in source_ids
        assert "source-b" in source_ids

    def test_run_linkage(self, db_conn, sample_source, sample_problem):
        upsert_source(db_conn, sample_source)
        problem_id = upsert_problem(db_conn, "run1", sample_source.source_id, sample_problem)
        db_conn.commit()

        row = db_conn.execute(
            "SELECT * FROM run_problems WHERE run_id = ? AND problem_id = ?",
            ("run1", problem_id),
        ).fetchone()
        assert row is not None


class TestUpsertSubQuestion:
    def test_insert_sub_question(self, db_conn, sample_source, sample_problem):
        upsert_source(db_conn, sample_source)
        problem_id = upsert_problem(db_conn, "run1", sample_source.source_id, sample_problem)

        sq = sample_problem["sub_questions"][0]
        upsert_sub_question(db_conn, problem_id, sq, sample_source.source_id)
        db_conn.commit()

        row = db_conn.execute(
            "SELECT * FROM sub_questions WHERE problem_id = ?", (problem_id,)
        ).fetchone()
        assert row is not None
        assert row["question"] == "Which residues determine att site preference?"
        assert json.loads(row["disciplines"]) == ["protein biochemistry", "molecular biology"]

    def test_dedup_sub_question(self, db_conn, sample_source, sample_problem):
        upsert_source(db_conn, sample_source)
        problem_id = upsert_problem(db_conn, "run1", sample_source.source_id, sample_problem)

        sq = sample_problem["sub_questions"][0]
        upsert_sub_question(db_conn, problem_id, sq, sample_source.source_id)
        upsert_sub_question(db_conn, problem_id, sq, sample_source.source_id)
        db_conn.commit()

        count = db_conn.execute(
            "SELECT COUNT(*) FROM sub_questions WHERE problem_id = ?", (problem_id,)
        ).fetchone()[0]
        assert count == 1


class TestRecordPipelineRun:
    def test_record_run(self, db_conn):
        row_id = record_pipeline_run(db_conn, {
            "run_id": "run1",
            "source_types": ["workshop_report"],
            "sources_ingested": 20,
            "signal_passages": 400,
            "problems_extracted": 150,
            "sub_questions_extracted": 300,
            "total_cost": 0.72,
        })
        db_conn.commit()

        assert row_id > 0
        row = db_conn.execute("SELECT * FROM pipeline_runs WHERE run_id = 'run1'").fetchone()
        assert row["sources_ingested"] == 20
        assert row["problems_extracted"] == 150


class TestExportJsonFeed:
    def test_export(self, db_conn, sample_source, sample_problem, tmp_path):
        upsert_source(db_conn, sample_source)
        problem_id = upsert_problem(db_conn, "run1", sample_source.source_id, sample_problem)
        for sq in sample_problem["sub_questions"]:
            upsert_sub_question(db_conn, problem_id, sq, sample_source.source_id)
        record_pipeline_run(db_conn, {
            "run_id": "run1",
            "sources_ingested": 1,
            "signal_passages": 2,
            "problems_extracted": 1,
            "sub_questions_extracted": 2,
        })
        db_conn.commit()

        output_path = tmp_path / "feed.json"
        result = export_json_feed(db_conn, "run1", output_path)

        assert result == output_path
        assert output_path.exists()

        with open(output_path) as f:
            feed = json.load(f)

        assert feed["pipeline_run_id"] == "run1"
        assert feed["summary"]["problems_extracted"] == 1
        assert len(feed["problems"]) == 1

        prob = feed["problems"][0]
        assert prob["domain"] == "protein engineering"
        assert len(prob["sub_questions"]) == 2
        assert prob["sub_questions"][0]["question"] == "Which residues determine att site preference?"
