"""Stage 1d: openproblems.bio benchmark task ingestion via GitHub raw JSON.

Fetches structured benchmark task data from the openproblems-bio/website
GitHub repository. Each task is a formally defined computational open problem
in single-cell biology with metrics, methods, and benchmark results.

Unlike other ingest modules, this produces Source objects with problems already
populated (direct mapping), so signal filter and LLM extraction are skipped.
"""

import asyncio
import logging

import httpx

from pipeline import Source, load_config

logger = logging.getLogger("collector.ingest_openproblems")

BASE_URL = "https://raw.githubusercontent.com/openproblems-bio/website/main/results"

TASK_DIRS = [
    "batch_integration",
    "cell_cell_communication_ligand_target",
    "cell_cell_communication_source_target",
    "denoising",
    "dimensionality_reduction",
    "foundation_models",
    "label_projection",
    "matching_modalities",
    "perturbation_prediction",
    "predict_modality",
    "spatial_decomposition",
    "spatially_variable_genes",
]

DATA_FILES = [
    "task_info.json",
    "metric_info.json",
    "method_info.json",
    "results.json",
    "dataset_info.json",
]

SUBDOMAIN_MAP = {
    "batch_integration": "batch effect correction",
    "cell_cell_communication_ligand_target": "cell-cell communication (ligand-target)",
    "cell_cell_communication_source_target": "cell-cell communication (source-target)",
    "denoising": "expression denoising",
    "dimensionality_reduction": "dimensionality reduction",
    "foundation_models": "foundation models for single-cell",
    "label_projection": "cell type annotation",
    "matching_modalities": "multi-modal integration",
    "perturbation_prediction": "perturbation response prediction",
    "predict_modality": "cross-modality prediction",
    "spatial_decomposition": "spatial transcriptomics deconvolution",
    "spatially_variable_genes": "spatially variable gene detection",
}


async def fetch_task_data(
    client: httpx.AsyncClient,
    task_dir: str,
) -> dict | None:
    """Fetch all JSON data files for a single benchmark task.

    Returns dict with keys matching DATA_FILES (sans .json), or None if
    task_info.json cannot be fetched.
    """
    data = {}
    for filename in DATA_FILES:
        key = filename.replace(".json", "")
        url = f"{BASE_URL}/{task_dir}/data/{filename}"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data[key] = resp.json()
            else:
                logger.warning("HTTP %d for %s/%s", resp.status_code, task_dir, filename)
        except httpx.HTTPError as e:
            logger.warning("HTTP error fetching %s/%s: %s", task_dir, filename, e)
        except ValueError as e:
            logger.warning("JSON decode error for %s/%s: %s", task_dir, filename, e)

    if "task_info" not in data:
        logger.warning("No task_info for %s, skipping", task_dir)
        return None
    return data


def _build_source(task_dir: str, task_data: dict) -> Source:
    """Map raw task JSON data to a Source object with problems attached."""
    task_info = task_data["task_info"]

    authors = []
    for a in task_info.get("authors", []):
        if isinstance(a, dict):
            authors.append(a.get("name", str(a)))
        else:
            authors.append(str(a))

    full_text = (
        f"{task_info.get('task_name', '')}\n\n"
        f"{task_info.get('task_description', '')}"
    )

    source = Source(
        source_id=f"openproblems-{task_dir}",
        source_type="openproblems_benchmark",
        title=task_info.get("task_name", task_dir.replace("_", " ").title()),
        authors=authors,
        organization="Open Problems in Single-Cell Analysis",
        date_published="",
        url=f"https://openproblems.bio/results/{task_dir}",
        full_text=full_text,
        problems=_build_problems(task_dir, task_data),
    )
    return source


def _build_problems(task_dir: str, task_data: dict) -> list[dict]:
    """Construct Problem dicts directly from structured benchmark data.

    Each benchmark task maps to exactly one Problem.
    """
    task_info = task_data["task_info"]
    metrics = task_data.get("metric_info", [])
    methods = task_data.get("method_info", [])
    results = task_data.get("results", [])
    datasets = task_data.get("dataset_info", [])

    sub_questions = _build_sub_questions_from_metrics(metrics, results, methods)
    notes = _analyze_benchmark_gaps(results, methods, metrics)

    if datasets:
        dataset_names = [
            d.get("dataset_name", d.get("dataset_id", ""))
            for d in datasets
        ]
        notes += f"\n\nBenchmark datasets ({len(datasets)}): {', '.join(dataset_names)}"

    problem = {
        "problem_statement": task_info.get("task_summary", ""),
        "domain": "computational biology",
        "subdomain": SUBDOMAIN_MAP.get(task_dir, task_dir.replace("_", " ")),
        "scope": "broad",
        "sub_questions": sub_questions,
        "original_text": task_info.get("task_description", ""),
        "related_keywords": _extract_keywords(task_dir, task_info, metrics),
        "notes": notes,
    }

    return [problem]


def _build_sub_questions_from_metrics(
    metrics: list[dict],
    results: list[dict],
    methods: list[dict],
) -> list[dict]:
    """Derive sub-questions from metric definitions and benchmark gaps.

    Each metric becomes a sub-question. Complexity is determined by the best
    achieved scaled_score across non-baseline methods.
    """
    baseline_ids = {m["method_id"] for m in methods if m.get("is_baseline", False)}

    # Compute best scaled score per metric (excluding baselines)
    best_per_metric: dict[str, float] = {}
    for row in results:
        if row.get("method_id") in baseline_ids:
            continue
        for metric_id, score in row.get("scaled_scores", {}).items():
            if not isinstance(score, (int, float)):
                continue
            if metric_id not in best_per_metric or score > best_per_metric[metric_id]:
                best_per_metric[metric_id] = score

    sub_questions = []
    for metric in metrics:
        metric_id = metric.get("metric_id", metric.get("component_name", ""))
        metric_name = metric.get("metric_name", metric_id)
        metric_summary = metric.get("metric_summary", "")
        best_score = best_per_metric.get(metric_id)

        if best_score is None:
            complexity = "complex"
            gap_note = "No non-baseline methods have reported scores"
        elif best_score < 0.5:
            complexity = "complex"
            gap_note = f"Best non-baseline score: {best_score:.3f} (far from solved)"
        elif best_score < 0.8:
            complexity = "medium"
            gap_note = f"Best non-baseline score: {best_score:.3f} (partially addressed)"
        else:
            complexity = "simple"
            gap_note = f"Best non-baseline score: {best_score:.3f} (largely addressed)"

        if metric_summary:
            question = f"How can methods better achieve {metric_summary.lower().rstrip('.')}?"
        else:
            question = f"How can {metric_name.lower()} be improved for this task?"

        sub_questions.append({
            "question": question,
            "evidence_needed": (
                f"New or improved methods evaluated on the benchmark "
                f"with metric '{metric_name}'. {gap_note}"
            ),
            "disciplines": [
                "computational biology",
                "machine learning",
                "single-cell genomics",
            ],
            "estimated_complexity": complexity,
        })

    return sub_questions


def _analyze_benchmark_gaps(
    results: list[dict],
    methods: list[dict],
    metrics: list[dict],
) -> str:
    """Summarize benchmark state: method count, best/worst scores, gaps."""
    baseline_ids = {m["method_id"] for m in methods if m.get("is_baseline", False)}
    non_baseline_methods = [m for m in methods if not m.get("is_baseline", False)]

    # Average mean_score per method across datasets
    method_scores: dict[str, list[float]] = {}
    for row in results:
        mid = row.get("method_id", "")
        if mid in baseline_ids:
            continue
        score = row.get("mean_score")
        if isinstance(score, (int, float)):
            method_scores.setdefault(mid, []).append(score)

    avg_by_method = {
        mid: sum(scores) / len(scores)
        for mid, scores in method_scores.items()
        if scores
    }

    if not avg_by_method:
        return "No benchmark results available for non-baseline methods."

    best_method_id = max(avg_by_method, key=avg_by_method.get)
    best_avg = avg_by_method[best_method_id]
    worst_avg = min(avg_by_method.values())

    best_name = best_method_id
    for m in methods:
        if m.get("method_id") == best_method_id:
            best_name = m.get("method_name", best_method_id)
            break

    dataset_ids = {r.get("dataset_id") for r in results if r.get("dataset_id")}

    parts = [
        f"Benchmark status: {len(non_baseline_methods)} methods evaluated, "
        f"{len(dataset_ids)} datasets.",
        f"Best average score: {best_avg:.3f} ({best_name}).",
        f"Score range across methods: {worst_avg:.3f} - {best_avg:.3f}.",
    ]

    return " ".join(parts)


def _extract_keywords(
    task_dir: str,
    task_info: dict,
    metrics: list[dict],
) -> list[str]:
    """Extract relevant keywords from task and metric data."""
    keywords = ["single-cell", "benchmarking", "open problems"]
    keywords.extend(task_dir.replace("_", " ").split())
    for m in metrics:
        name = m.get("metric_name", "")
        if name:
            keywords.append(name.lower())
    # Deduplicate preserving order
    return list(dict.fromkeys(keywords))


async def ingest_openproblems(config: dict | None = None) -> list[Source]:
    """Fetch all openproblems.bio benchmark tasks and return Source objects.

    Sources have problems already populated (direct mapping).
    """
    config = config or load_config()
    op_cfg = config.get("sources", {}).get("openproblems", {})

    base_url_override = op_cfg.get("base_url")
    if base_url_override:
        global BASE_URL
        BASE_URL = base_url_override

    task_dirs = op_cfg.get("tasks", TASK_DIRS)

    logger.info("Fetching %d openproblems.bio benchmark tasks...", len(task_dirs))

    sources = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for task_dir in task_dirs:
            task_data = await fetch_task_data(client, task_dir)
            if task_data is None:
                continue

            source = _build_source(task_dir, task_data)
            sources.append(source)
            logger.info(
                "  %s: %d problems, %d sub-questions",
                task_dir,
                len(source.problems),
                sum(len(p.get("sub_questions", [])) for p in source.problems),
            )

            await asyncio.sleep(0.1)  # Polite delay

    logger.info(
        "openproblems.bio ingestion complete: %d/%d tasks ingested",
        len(sources), len(task_dirs),
    )
    return sources


def ingest_openproblems_sync(config: dict | None = None) -> list[Source]:
    """Synchronous wrapper for ingest_openproblems."""
    return asyncio.run(ingest_openproblems(config))
