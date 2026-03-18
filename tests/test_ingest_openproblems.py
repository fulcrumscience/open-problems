"""Tests for the openproblems.bio benchmark task ingest module."""

import pytest

from pipeline import Source
from pipeline.ingest_openproblems import (
    _build_source,
    _build_problems,
    _build_sub_questions_from_metrics,
    _analyze_benchmark_gaps,
    _extract_keywords,
)
from pipeline.output import (
    init_db, upsert_source, upsert_problem, upsert_sub_question,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_task_info():
    return {
        "task_id": "task_batch_integration",
        "task_name": "Batch Integration",
        "task_summary": "Remove unwanted batch effects from scRNA-seq data",
        "task_description": (
            "Large-scale single-cell consortia combine datasets from "
            "multiple labs using different sequencing technologies, "
            "creating complex batch effects. Over 200 tools exist for "
            "batch correction. This task benchmarks their performance."
        ),
        "repo": "https://github.com/openproblems-bio/task_batch_integration",
        "license": "MIT",
        "authors": [
            {"name": "Alice Smith", "roles": "maintainer", "info": {"github": "asmith"}},
            {"name": "Bob Jones", "roles": "author", "info": {"github": "bjones"}},
        ],
    }


@pytest.fixture
def sample_metrics():
    return [
        {
            "metric_id": "asw_batch",
            "metric_name": "ASW Batch",
            "metric_summary": "batch mixing quality within cell identity clusters",
            "maximize": True,
        },
        {
            "metric_id": "nmi",
            "metric_name": "NMI",
            "metric_summary": "clustering-to-label agreement",
            "maximize": True,
        },
        {
            "metric_id": "graph_connectivity",
            "metric_name": "Graph Connectivity",
            "metric_summary": "kNN graph connectedness within cell-type groups",
            "maximize": True,
        },
    ]


@pytest.fixture
def sample_methods():
    return [
        {"method_id": "no_integration", "method_name": "No Integration", "is_baseline": True},
        {"method_id": "scanorama", "method_name": "Scanorama", "is_baseline": False},
        {"method_id": "harmony", "method_name": "Harmony", "is_baseline": False},
        {"method_id": "combat", "method_name": "ComBat", "is_baseline": False},
    ]


@pytest.fixture
def sample_results():
    return [
        {
            "dataset_id": "dataset_1",
            "method_id": "no_integration",
            "scaled_scores": {"asw_batch": 0.1, "nmi": 0.3, "graph_connectivity": 0.5},
            "mean_score": 0.3,
        },
        {
            "dataset_id": "dataset_1",
            "method_id": "scanorama",
            "scaled_scores": {"asw_batch": 0.85, "nmi": 0.72, "graph_connectivity": 0.95},
            "mean_score": 0.84,
        },
        {
            "dataset_id": "dataset_1",
            "method_id": "harmony",
            "scaled_scores": {"asw_batch": 0.78, "nmi": 0.65, "graph_connectivity": 0.88},
            "mean_score": 0.77,
        },
        {
            "dataset_id": "dataset_2",
            "method_id": "scanorama",
            "scaled_scores": {"asw_batch": 0.70, "nmi": 0.60, "graph_connectivity": 0.90},
            "mean_score": 0.73,
        },
        {
            "dataset_id": "dataset_2",
            "method_id": "harmony",
            "scaled_scores": {"asw_batch": 0.90, "nmi": 0.80, "graph_connectivity": 0.92},
            "mean_score": 0.87,
        },
        {
            "dataset_id": "dataset_2",
            "method_id": "combat",
            "scaled_scores": {"asw_batch": 0.40, "nmi": 0.35, "graph_connectivity": "NA"},
            "mean_score": 0.38,
        },
    ]


@pytest.fixture
def sample_datasets():
    return [
        {"dataset_id": "dataset_1", "dataset_name": "Mouse Pancreas Atlas"},
        {"dataset_id": "dataset_2", "dataset_name": "Immune Cell Atlas"},
    ]


@pytest.fixture
def sample_task_data(sample_task_info, sample_metrics, sample_methods, sample_results, sample_datasets):
    return {
        "task_info": sample_task_info,
        "metric_info": sample_metrics,
        "method_info": sample_methods,
        "results": sample_results,
        "dataset_info": sample_datasets,
    }


# ── _build_source tests ──────────────────────────────────────────────

class TestBuildSource:
    def test_source_id_format(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.source_id == "openproblems-batch_integration"

    def test_source_type(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.source_type == "openproblems_benchmark"

    def test_title_from_task_info(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.title == "Batch Integration"

    def test_authors_extracted(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.authors == ["Alice Smith", "Bob Jones"]

    def test_organization(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.organization == "Open Problems in Single-Cell Analysis"

    def test_url(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert source.url == "https://openproblems.bio/results/batch_integration"

    def test_full_text_contains_description(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert "batch effects" in source.full_text

    def test_problems_populated(self, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        assert len(source.problems) == 1

    def test_missing_authors(self, sample_task_data):
        sample_task_data["task_info"]["authors"] = []
        source = _build_source("batch_integration", sample_task_data)
        assert source.authors == []


# ── _build_problems tests ────────────────────────────────────────────

class TestBuildProblems:
    def test_one_problem_per_task(self, sample_task_data):
        problems = _build_problems("batch_integration", sample_task_data)
        assert len(problems) == 1

    def test_problem_statement(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert problem["problem_statement"] == "Remove unwanted batch effects from scRNA-seq data"

    def test_domain(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert problem["domain"] == "computational biology"

    def test_subdomain(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert problem["subdomain"] == "batch effect correction"

    def test_scope_broad(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert problem["scope"] == "broad"

    def test_original_text(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert "200 tools" in problem["original_text"]

    def test_sub_questions_from_metrics(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert len(problem["sub_questions"]) == 3  # One per metric

    def test_notes_has_benchmark_info(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert "methods evaluated" in problem["notes"]

    def test_notes_has_datasets(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert "Mouse Pancreas Atlas" in problem["notes"]

    def test_related_keywords(self, sample_task_data):
        problem = _build_problems("batch_integration", sample_task_data)[0]
        assert "single-cell" in problem["related_keywords"]
        assert "benchmarking" in problem["related_keywords"]


# ── _build_sub_questions_from_metrics tests ──────────────────────────

class TestBuildSubQuestions:
    def test_one_per_metric(self, sample_metrics, sample_results, sample_methods):
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        assert len(sqs) == 3

    def test_high_score_simple(self, sample_metrics, sample_results, sample_methods):
        """asw_batch best is 0.90 (harmony on dataset_2) -> simple"""
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        asw_sq = next(sq for sq in sqs if "asw" in sq["evidence_needed"].lower())
        assert asw_sq["estimated_complexity"] == "simple"

    def test_medium_score_medium(self, sample_metrics, sample_results, sample_methods):
        """nmi best is 0.80 (harmony on dataset_2) -> simple (>= 0.8)"""
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        nmi_sq = next(sq for sq in sqs if "'NMI'" in sq["evidence_needed"])
        assert nmi_sq["estimated_complexity"] == "simple"

    def test_baseline_excluded(self, sample_metrics, sample_results, sample_methods):
        """no_integration is baseline and shouldn't affect best scores."""
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        # graph_connectivity: best non-baseline is 0.95 (scanorama on dataset_1) -> simple
        gc_sq = next(sq for sq in sqs if "Graph Connectivity" in sq["evidence_needed"])
        assert gc_sq["estimated_complexity"] == "simple"
        assert "0.95" in gc_sq["evidence_needed"]

    def test_na_scores_handled(self, sample_metrics, sample_methods):
        """Results with 'NA' scores should be skipped."""
        results = [
            {
                "dataset_id": "d1",
                "method_id": "combat",
                "scaled_scores": {"asw_batch": "NA", "nmi": "NA", "graph_connectivity": "NA"},
                "mean_score": "NA",
            },
        ]
        sqs = _build_sub_questions_from_metrics(sample_metrics, results, sample_methods)
        # All scores are NA for the only non-baseline method -> complex
        for sq in sqs:
            assert sq["estimated_complexity"] == "complex"

    def test_empty_results(self, sample_metrics, sample_methods):
        sqs = _build_sub_questions_from_metrics(sample_metrics, [], sample_methods)
        for sq in sqs:
            assert sq["estimated_complexity"] == "complex"
            assert "No non-baseline" in sq["evidence_needed"]

    def test_question_uses_metric_summary(self, sample_metrics, sample_results, sample_methods):
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        asw_sq = next(sq for sq in sqs if "batch mixing" in sq["question"])
        assert asw_sq["question"].startswith("How can methods better achieve")

    def test_disciplines(self, sample_metrics, sample_results, sample_methods):
        sqs = _build_sub_questions_from_metrics(sample_metrics, sample_results, sample_methods)
        for sq in sqs:
            assert "computational biology" in sq["disciplines"]

    def test_low_score_complex(self):
        """Metric with best score < 0.5 should be complex."""
        metrics = [{"metric_id": "hard_metric", "metric_name": "Hard Metric", "metric_summary": ""}]
        methods = [{"method_id": "m1", "method_name": "M1", "is_baseline": False}]
        results = [
            {"dataset_id": "d1", "method_id": "m1",
             "scaled_scores": {"hard_metric": 0.3}, "mean_score": 0.3},
        ]
        sqs = _build_sub_questions_from_metrics(metrics, results, methods)
        assert sqs[0]["estimated_complexity"] == "complex"
        assert "far from solved" in sqs[0]["evidence_needed"]

    def test_mid_score_medium(self):
        """Metric with best score 0.5-0.8 should be medium."""
        metrics = [{"metric_id": "mid_metric", "metric_name": "Mid Metric", "metric_summary": "something"}]
        methods = [{"method_id": "m1", "method_name": "M1", "is_baseline": False}]
        results = [
            {"dataset_id": "d1", "method_id": "m1",
             "scaled_scores": {"mid_metric": 0.65}, "mean_score": 0.65},
        ]
        sqs = _build_sub_questions_from_metrics(metrics, results, methods)
        assert sqs[0]["estimated_complexity"] == "medium"
        assert "partially addressed" in sqs[0]["evidence_needed"]


# ── _analyze_benchmark_gaps tests ────────────────────────────────────

class TestAnalyzeBenchmarkGaps:
    def test_summary_has_method_count(self, sample_results, sample_methods, sample_metrics):
        notes = _analyze_benchmark_gaps(sample_results, sample_methods, sample_metrics)
        assert "3 methods evaluated" in notes

    def test_summary_has_dataset_count(self, sample_results, sample_methods, sample_metrics):
        notes = _analyze_benchmark_gaps(sample_results, sample_methods, sample_metrics)
        assert "2 datasets" in notes

    def test_summary_has_best_method(self, sample_results, sample_methods, sample_metrics):
        notes = _analyze_benchmark_gaps(sample_results, sample_methods, sample_metrics)
        # Harmony avg = (0.77 + 0.87) / 2 = 0.82
        # Scanorama avg = (0.84 + 0.73) / 2 = 0.785
        assert "Harmony" in notes

    def test_empty_results(self, sample_methods, sample_metrics):
        notes = _analyze_benchmark_gaps([], sample_methods, sample_metrics)
        assert "No benchmark results" in notes

    def test_all_baseline_only(self, sample_metrics):
        methods = [{"method_id": "base", "method_name": "Base", "is_baseline": True}]
        results = [
            {"dataset_id": "d1", "method_id": "base",
             "scaled_scores": {"asw_batch": 0.5}, "mean_score": 0.5},
        ]
        notes = _analyze_benchmark_gaps(results, methods, sample_metrics)
        assert "No benchmark results" in notes


# ── _extract_keywords tests ──────────────────────────────────────────

class TestExtractKeywords:
    def test_base_keywords(self, sample_metrics):
        kw = _extract_keywords("batch_integration", {}, sample_metrics)
        assert "single-cell" in kw
        assert "benchmarking" in kw

    def test_task_dir_words(self, sample_metrics):
        kw = _extract_keywords("batch_integration", {}, sample_metrics)
        assert "batch" in kw
        assert "integration" in kw

    def test_metric_names_included(self, sample_metrics):
        kw = _extract_keywords("batch_integration", {}, sample_metrics)
        assert "nmi" in kw

    def test_no_duplicates(self):
        kw = _extract_keywords("batch_integration", {}, [])
        assert len(kw) == len(set(kw))


# ── Output integration tests ─────────────────────────────────────────

class TestOutputIntegration:
    @pytest.fixture
    def db_conn(self, tmp_path):
        conn = init_db(tmp_path / "test.db")
        yield conn
        conn.close()

    def test_openproblems_source_upserts(self, db_conn, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        upsert_source(db_conn, source)
        db_conn.commit()

        row = db_conn.execute(
            "SELECT id, source_type, title, organization FROM sources WHERE id = ?",
            (source.source_id,),
        ).fetchone()
        assert row is not None
        assert row["source_type"] == "openproblems_benchmark"
        assert row["title"] == "Batch Integration"

    def test_openproblems_problem_upserts(self, db_conn, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        upsert_source(db_conn, source)
        problem = source.problems[0]
        provenance = {
            "original_text": problem.get("original_text", ""),
            "deep_link": source.url,
            "section_label": "Benchmark Task Description",
        }
        problem_id = upsert_problem(
            db_conn, "test-run", source.source_id, problem, provenance,
        )
        db_conn.commit()
        assert problem_id is not None

        row = db_conn.execute(
            "SELECT domain, subdomain, scope FROM open_problems WHERE id = ?",
            (problem_id,),
        ).fetchone()
        assert row["domain"] == "computational biology"
        assert row["subdomain"] == "batch effect correction"

    def test_sub_questions_upsert(self, db_conn, sample_task_data):
        source = _build_source("batch_integration", sample_task_data)
        upsert_source(db_conn, source)
        problem = source.problems[0]
        problem_id = upsert_problem(
            db_conn, "test-run", source.source_id, problem, None,
        )

        for sq in problem["sub_questions"]:
            upsert_sub_question(db_conn, problem_id, sq, source.source_id)
        db_conn.commit()

        rows = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM sub_questions WHERE problem_id = ?",
            (problem_id,),
        ).fetchone()
        assert rows["cnt"] == 3  # One per metric
