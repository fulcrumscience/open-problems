#!/usr/bin/env python3
"""Generate review queue CSVs from collector.db for human adjudication."""

import argparse
import csv
import json
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT_DIR / "data" / "results"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export ranked problem-review queue and adjudication template."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=RESULTS_DIR / "collector.db",
        help="Path to collector SQLite DB (default: data/results/collector.db).",
    )
    parser.add_argument(
        "--run-id",
        help="Pipeline run_id to review (default: latest run in pipeline_runs).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Output directory for CSV files (default: data/results).",
    )
    return parser.parse_args()


def _resolve_run_id(conn: sqlite3.Connection, run_id: str | None) -> str:
    if run_id:
        exists = conn.execute(
            "SELECT 1 FROM pipeline_runs WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Run ID not found in pipeline_runs: {run_id}")
        return run_id

    row = conn.execute(
        "SELECT run_id FROM pipeline_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row or not row["run_id"]:
        raise ValueError("No pipeline runs found; run the pipeline first.")
    return row["run_id"]


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def _load_review_rows(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          op.id AS problem_id,
          op.scope,
          op.domain,
          op.subdomain,
          op.mention_count,
          op.source_ids,
          op.related_keywords,
          op.canonical_statement AS problem_statement,
          COUNT(sq.id) AS subq_count
        FROM run_problems rp
        JOIN open_problems op ON op.id = rp.problem_id
        LEFT JOIN sub_questions sq ON sq.problem_id = op.id
        WHERE rp.run_id = ?
        GROUP BY op.id
        ORDER BY
          CASE op.scope
            WHEN 'medium' THEN 0
            WHEN 'narrow' THEN 1
            WHEN 'broad' THEN 2
            ELSE 3
          END,
          COUNT(sq.id) DESC,
          op.mention_count DESC,
          op.id ASC
        """,
        (run_id,),
    ).fetchall()

    source_ids_all = set()
    for row in rows:
        source_ids_all.update(_safe_json_list(row["source_ids"]))

    source_map: dict[str, dict] = {}
    if source_ids_all:
        placeholders = ",".join("?" for _ in source_ids_all)
        source_rows = conn.execute(
            f"SELECT id, source_type, title FROM sources WHERE id IN ({placeholders})",
            tuple(source_ids_all),
        ).fetchall()
        source_map = {
            r["id"]: {"source_type": r["source_type"], "title": r["title"]}
            for r in source_rows
        }

    output = []
    for row in rows:
        source_ids = _safe_json_list(row["source_ids"])
        keywords = _safe_json_list(row["related_keywords"])
        source_titles = []
        source_types = set()
        for sid in source_ids:
            src = source_map.get(sid)
            if not src:
                continue
            source_titles.append(src["title"] or sid)
            if src["source_type"]:
                source_types.add(src["source_type"])

        statement = (row["problem_statement"] or "").strip()
        lower_statement = statement.lower()
        lower_domain = (row["domain"] or "").lower()

        flag_policy_or_regulatory = any(
            t in lower_statement for t in ("policy", "regulatory", "guideline", "governance")
        )
        flag_computational_like = (
            "machine learning" in lower_statement
            or "ai/ml" in lower_statement
            or "algorithm" in lower_statement
            or "machine learning" in lower_domain
            or "computational" in lower_domain
        )
        flag_missing_subqs_for_decomposable = (
            row["scope"] in {"narrow", "medium"} and int(row["subq_count"] or 0) == 0
        )

        output.append(
            {
                "run_id": run_id,
                "problem_id": row["problem_id"],
                "scope": row["scope"] or "",
                "domain": row["domain"] or "",
                "subdomain": row["subdomain"] or "",
                "mention_count": row["mention_count"] or 0,
                "source_count": len(source_ids),
                "subq_count": row["subq_count"] or 0,
                "flag_policy_or_regulatory": int(flag_policy_or_regulatory),
                "flag_computational_like": int(flag_computational_like),
                "flag_missing_subqs_for_decomposable": int(flag_missing_subqs_for_decomposable),
                "problem_statement": statement,
                "related_keywords": " | ".join(keywords),
                "source_ids": " | ".join(source_ids),
                "source_types": " | ".join(sorted(source_types)),
                "source_titles": " | ".join(source_titles),
            }
        )
    return output


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def main() -> None:
    args = _parse_args()
    if not args.db.exists():
        raise FileNotFoundError(f"DB not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    try:
        run_id = _resolve_run_id(conn, args.run_id)
        rows = _load_review_rows(conn, run_id)
    finally:
        conn.close()

    queue_fields = [
        "run_id",
        "problem_id",
        "scope",
        "domain",
        "subdomain",
        "mention_count",
        "source_count",
        "subq_count",
        "flag_policy_or_regulatory",
        "flag_computational_like",
        "flag_missing_subqs_for_decomposable",
        "problem_statement",
        "related_keywords",
        "source_ids",
        "source_types",
        "source_titles",
    ]
    adjudication_fields = queue_fields + [
        "decision",
        "priority",
        "merge_into_problem_id",
        "in_scope",
        "decomposition_quality",
        "reviewer_notes",
    ]

    queue_path = args.out_dir / f"review_queue_{run_id}.csv"
    adjudication_path = args.out_dir / f"review_adjudication_{run_id}.csv"
    _write_csv(queue_path, rows, queue_fields)
    _write_csv(adjudication_path, rows, adjudication_fields)

    print(f"Run ID: {run_id}")
    print(f"Problems queued: {len(rows)}")
    print(f"Wrote: {queue_path}")
    print(f"Wrote: {adjudication_path}")


if __name__ == "__main__":
    main()
