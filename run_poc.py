#!/usr/bin/env python3
"""Orchestrator for the Open Problem Collector PoC run."""

import argparse
import sys
import time

from pipeline import (
    load_config, setup_logging, generate_run_id,
    write_checkpoint, load_checkpoint, checkpoint_exists,
    CostTracker, BudgetExceeded,
)
from pipeline.ingest_workshops import ingest_workshops
from pipeline.ingest_reviews import ingest_elife_reviews_sync
from pipeline.signal_filter import SignalFilter
from pipeline.problem_extractor import extract_problems_sync
from pipeline.output import (
    init_db, upsert_source, upsert_problem, upsert_sub_question,
    record_pipeline_run, export_json_feed, build_provenance,
)


def _resolve_sources(source_arg: str) -> list[str]:
    """Map --source argument to list of source type labels."""
    if source_arg == "all":
        return ["workshops", "elife", "nas"]
    return [source_arg]


def _ingest_source_type(stype: str, config: dict) -> list:
    """Dispatch ingestion for a given source type."""
    if stype == "workshops":
        return ingest_workshops(config)
    elif stype == "elife":
        return ingest_elife_reviews_sync(config)
    elif stype == "nas":
        try:
            from pipeline.ingest_nas import ingest_nas_reports
            return ingest_nas_reports(config)
        except ImportError:
            logging.getLogger("collector").warning("NAS ingestion not yet implemented")
            return []
    else:
        logging.getLogger("collector").warning("Unknown source type: %s", stype)
        return []


def main():
    parser = argparse.ArgumentParser(description="Open Problem Collector — PoC Run")
    parser.add_argument("--resume", help="Resume a previous run by run_id")
    parser.add_argument("--source", default="workshops",
                        choices=["workshops", "elife", "nas", "all"],
                        help="Source type to ingest (default: workshops)")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM stages (for testing ingestion/filter)")
    parser.add_argument("--budget", type=float, default=None,
                        help="Max spend in USD (default: from config.yaml)")
    args = parser.parse_args()

    run_id = args.resume or generate_run_id()
    config = load_config()
    logger = setup_logging(run_id)

    budget_limit = args.budget or config["budget"]["spending_alert_threshold"]
    cost_tracker = CostTracker(limit=budget_limit)

    logger.info("=" * 60)
    logger.info("Open Problem Collector — PoC Run")
    logger.info("Run ID: %s", run_id)
    logger.info("Budget limit: $%.2f", budget_limit)
    logger.info("=" * 60)

    start_time = time.time()
    stats = {"run_id": run_id}

    # ── Stage 1: Ingestion ──────────────────────────────────────────
    source_types = _resolve_sources(args.source)
    all_sources = []

    for stype in source_types:
        cp_label = f"stage1_{stype}"
        if checkpoint_exists(run_id, cp_label):
            logger.info("Stage 1 [%s]: Loading from checkpoint", stype)
            batch = load_checkpoint(run_id, cp_label)
        else:
            logger.info("Stage 1 [%s]: Ingesting...", stype)
            batch = _ingest_source_type(stype, config)
            write_checkpoint(run_id, cp_label, batch)
        logger.info("Stage 1 [%s]: %d sources ingested", stype, len(batch))
        all_sources.extend(batch)

    sources = all_sources
    stats["sources_ingested"] = len(sources)
    stats["source_types"] = source_types
    logger.info("Stage 1 complete: %d total sources ingested", len(sources))

    if not sources:
        logger.warning("No sources ingested.")
        _print_summary(stats, start_time)
        return

    # ── Stage 2: Signal Filter ───────────────────────────────────────
    if checkpoint_exists(run_id, "stage2"):
        logger.info("Stage 2: Loading from checkpoint")
        filtered = load_checkpoint(run_id, "stage2")
    else:
        logger.info("Stage 2: Applying signal filter...")
        sig_filter = SignalFilter()
        filtered = sig_filter.filter_sources(sources)
        write_checkpoint(run_id, "stage2", filtered)

    total_passages = sum(len(s.signal_passages) for s in filtered)
    stats["signal_passages"] = total_passages
    logger.info("Stage 2 complete: %d sources with %d signal passages",
                len(filtered), total_passages)

    if args.skip_llm:
        logger.info("Skipping LLM stages (--skip-llm)")
        _print_summary(stats, start_time)
        return

    if not filtered:
        logger.warning("No signal passages found. Check signal_phrases.yaml or input documents.")
        _print_summary(stats, start_time)
        return

    # ── Stage 3: LLM Extraction ──────────────────────────────────────
    if checkpoint_exists(run_id, "stage3"):
        logger.info("Stage 3: Loading from checkpoint")
        extracted = load_checkpoint(run_id, "stage3")
    else:
        logger.info("Stage 3: Extracting open problems with LLM...")
        try:
            extracted = extract_problems_sync(filtered, run_id, config, cost_tracker)
        except BudgetExceeded:
            logger.error("Budget exceeded during Stage 3. Saving progress and aborting.")
            stats["total_cost"] = cost_tracker.total_cost
            stats["aborted"] = "budget_exceeded_stage3"
            _print_summary(stats, start_time, cost_tracker)
            sys.exit(1)
        write_checkpoint(run_id, "stage3", extracted)

    total_problems = sum(len(s.problems) for s in extracted)
    total_sub_q = sum(
        len(p.get("sub_questions", []))
        for s in extracted
        for p in s.problems
    )
    stats["problems_extracted"] = total_problems
    stats["sub_questions_extracted"] = total_sub_q
    logger.info("Stage 3 complete: %d problems, %d sub-questions", total_problems, total_sub_q)

    # ── Stage 6: Output ──────────────────────────────────────────────
    logger.info("Stage 6: Writing output...")
    conn = init_db()
    for source in extracted:
        upsert_source(conn, source)
        for problem in source.problems:
            provenance = build_provenance(source, problem)
            problem_id = upsert_problem(conn, run_id, source.source_id, problem, provenance)
            for sq in problem.get("sub_questions", []):
                upsert_sub_question(conn, problem_id, sq, source.source_id)
    conn.commit()

    stats["total_cost"] = cost_tracker.total_cost
    record_pipeline_run(conn, stats)
    conn.commit()

    feed_path = export_json_feed(conn, run_id)
    conn.close()
    logger.info("Stage 6 complete: DB and feed written to %s", feed_path)

    _print_summary(stats, start_time, cost_tracker)


def _print_summary(stats: dict, start_time: float, cost_tracker: CostTracker | None = None):
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"Run ID:               {stats.get('run_id', 'N/A')}")
    print(f"Sources ingested:     {stats.get('sources_ingested', 0)}")
    print(f"Signal passages:      {stats.get('signal_passages', 0)}")
    print(f"Problems extracted:   {stats.get('problems_extracted', 0)}")
    print(f"Sub-questions:        {stats.get('sub_questions_extracted', 0)}")
    print(f"Elapsed time:         {elapsed:.0f}s ({elapsed/60:.1f}m)")
    if cost_tracker:
        cs = cost_tracker.summary()
        print(f"Total LLM cost:       ${cs['total_cost']:.4f} / ${cs['limit']:.2f} limit")
        for stage, cost in cs["by_stage"].items():
            print(f"  {stage}: ${cost:.4f}")
    if stats.get("aborted"):
        print(f"*** ABORTED: {stats['aborted']} ***")
    print("=" * 60)


if __name__ == "__main__":
    main()
