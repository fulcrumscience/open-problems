"""Stage 6: SQLite output + JSON feed export."""

import json
import sqlite3
import urllib.parse
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from pipeline import RESULTS_DIR, Source

DB_PATH = RESULTS_DIR / "collector.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    source_type TEXT,
    title TEXT,
    authors TEXT,
    organization TEXT,
    date_published TEXT,
    url TEXT,
    signal_hits INTEGER,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS open_problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_statement TEXT,
    domain TEXT,
    subdomain TEXT,
    scope TEXT,
    mention_count INTEGER DEFAULT 1,
    source_ids TEXT,
    related_keywords TEXT,
    original_text TEXT,
    notes TEXT,
    provenance TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS sub_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER REFERENCES open_problems(id),
    question TEXT,
    evidence_needed TEXT,
    disciplines TEXT,
    estimated_complexity TEXT,
    source_id TEXT REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS run_problems (
    run_id TEXT,
    problem_id INTEGER REFERENCES open_problems(id),
    PRIMARY KEY (run_id, problem_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    run_date TEXT,
    source_types TEXT,
    sources_ingested INTEGER,
    signal_passages INTEGER,
    problems_extracted INTEGER,
    sub_questions_extracted INTEGER,
    total_cost REAL,
    config TEXT
);
"""


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the database and return a connection."""
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_problems_run_id ON run_problems(run_id)"
    )
    return conn


def upsert_source(conn: sqlite3.Connection, source: Source) -> None:
    """Insert or replace a source record."""
    conn.execute(
        """INSERT OR REPLACE INTO sources
           (id, source_type, title, authors, organization,
            date_published, url, signal_hits, processed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source.source_id,
            source.source_type,
            source.title,
            json.dumps(source.authors),
            source.organization,
            source.date_published,
            source.url,
            len(source.signal_passages),
            datetime.now().isoformat(),
        ),
    )


def _canonical_json(value, default):
    """Serialize list/dict fields deterministically for stable de-duplication."""
    return json.dumps(value if value is not None else default, sort_keys=True)


def build_provenance(source: Source, problem: dict) -> dict | None:
    """Match a problem's original_text to the best signal passage and build provenance.

    Returns a dict with section, signal_category, matched_phrases, original_text,
    and a deep_link (text-fragment URL for eLife, section ref for workshops).
    """
    original_text = problem.get("original_text", "")
    if not original_text or not source.signal_passages:
        return None

    # Find the best-matching signal passage by text similarity
    best_passage = None
    best_ratio = 0.0
    for passage in source.signal_passages:
        context = passage.get("context_text", "")
        if not context:
            continue
        # Check if original_text is a substring
        if original_text[:80].lower() in context.lower():
            best_passage = passage
            best_ratio = 1.0
            break
        # Fall back to fuzzy match
        ratio = SequenceMatcher(None, original_text[:200].lower(), context[:200].lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_passage = passage

    if not best_passage or best_ratio < 0.3:
        return {"original_text": original_text}

    provenance = {
        "section": best_passage.get("section", ""),
        "signal_category": best_passage.get("signal_category", ""),
        "matched_phrases": best_passage.get("matched_phrases", []),
        "original_text": original_text,
    }

    # Build deep link
    if source.source_type == "elife_review" and source.url:
        # eLife is a React SPA — text fragments don't work (content loaded dynamically).
        # Use section anchor instead: /reviews#peer-review-N
        section = best_passage.get("section", "")
        review_url = source.url.rstrip("/") + "/reviews"
        if section and section.startswith("peer-review-"):
            provenance["deep_link"] = f"{review_url}#{section}"
            # Friendly label: "peer-review-0" → "Reviewer #1"
            try:
                idx = int(section.split("-")[-1])
                provenance["section_label"] = f"Reviewer #{idx + 1}"
            except ValueError:
                provenance["section_label"] = section
        else:
            provenance["deep_link"] = review_url
    elif source.source_type == "workshop_report":
        section = best_passage.get("section", "")
        if section and source.url:
            provenance["deep_link"] = source.url
            provenance["section_label"] = section.replace("_", " ").title()

    return provenance


def upsert_problem(
    conn: sqlite3.Connection, run_id: str, source_id: str, problem: dict,
    provenance: dict | None = None,
) -> int:
    """Insert/update a problem record and attach it to a run. Returns problem_id."""
    canonical_statement = problem.get("problem_statement", "")
    domain = problem.get("domain", "")
    subdomain = problem.get("subdomain", "")
    scope = problem.get("scope", "")
    source_ids = _canonical_json([source_id], [])
    related_keywords = _canonical_json(problem.get("related_keywords"), [])
    original_text = problem.get("original_text", "")
    notes = problem.get("notes", "")
    provenance_json = json.dumps(provenance) if provenance else None

    # Check for existing problem with same statement from same source
    existing = conn.execute(
        """SELECT id, source_ids, mention_count FROM open_problems
           WHERE canonical_statement = ?
           ORDER BY id ASC
           LIMIT 1""",
        (canonical_statement,),
    ).fetchone()

    if existing:
        problem_id = existing["id"]
        # Merge source_ids
        existing_ids = json.loads(existing["source_ids"]) if existing["source_ids"] else []
        if source_id not in existing_ids:
            existing_ids.append(source_id)
            conn.execute(
                """UPDATE open_problems
                   SET source_ids = ?, mention_count = ?
                   WHERE id = ?""",
                (json.dumps(existing_ids, sort_keys=True), len(existing_ids), problem_id),
            )
        # Update provenance if not set yet
        if provenance_json:
            conn.execute(
                "UPDATE open_problems SET provenance = ? WHERE id = ? AND provenance IS NULL",
                (provenance_json, problem_id),
            )
    else:
        cursor = conn.execute(
            """INSERT INTO open_problems
               (canonical_statement, domain, subdomain, scope, mention_count,
                source_ids, related_keywords, original_text, notes, provenance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                canonical_statement,
                domain,
                subdomain,
                scope,
                1,
                source_ids,
                related_keywords,
                original_text,
                notes,
                provenance_json,
                datetime.now().isoformat(),
            ),
        )
        problem_id = cursor.lastrowid

    # Ensure run linkage
    conn.execute(
        """INSERT OR IGNORE INTO run_problems (run_id, problem_id)
           VALUES (?, ?)""",
        (run_id, problem_id),
    )

    return problem_id


def upsert_sub_question(
    conn: sqlite3.Connection, problem_id: int, sq: dict, source_id: str
) -> None:
    """Insert a sub-question for a problem."""
    question = sq.get("question", "")
    evidence_needed = sq.get("evidence_needed", "")
    disciplines = _canonical_json(sq.get("disciplines"), [])
    estimated_complexity = sq.get("estimated_complexity", "")

    # Check for existing identical sub-question
    existing = conn.execute(
        """SELECT id FROM sub_questions
           WHERE problem_id = ? AND question = ?
           LIMIT 1""",
        (problem_id, question),
    ).fetchone()

    if not existing:
        conn.execute(
            """INSERT INTO sub_questions
               (problem_id, question, evidence_needed, disciplines,
                estimated_complexity, source_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                problem_id,
                question,
                evidence_needed,
                disciplines,
                estimated_complexity,
                source_id,
            ),
        )


def record_pipeline_run(conn: sqlite3.Connection, run_info: dict) -> int:
    """Record a pipeline run and return the row id."""
    cursor = conn.execute(
        """INSERT INTO pipeline_runs
           (run_id, run_date, source_types, sources_ingested, signal_passages,
            problems_extracted, sub_questions_extracted, total_cost, config)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_info.get("run_id", ""),
            datetime.now().isoformat(),
            json.dumps(run_info.get("source_types", ["workshop_report"])),
            run_info.get("sources_ingested", 0),
            run_info.get("signal_passages", 0),
            run_info.get("problems_extracted", 0),
            run_info.get("sub_questions_extracted", 0),
            run_info.get("total_cost", 0.0),
            json.dumps(run_info.get("config", {})),
        ),
    )
    return cursor.lastrowid


def export_json_feed(
    conn: sqlite3.Connection,
    run_id: str,
    output_path: Path | None = None,
) -> Path:
    """Export problems as a JSON feed file."""
    output_path = output_path or RESULTS_DIR / "problems_feed.json"

    # Get run stats
    run_row = conn.execute(
        """SELECT * FROM pipeline_runs WHERE run_id = ? ORDER BY id DESC LIMIT 1""",
        (run_id,),
    ).fetchone()

    # Get problems for this run
    problem_rows = conn.execute(
        """SELECT op.* FROM run_problems rp
           JOIN open_problems op ON op.id = rp.problem_id
           WHERE rp.run_id = ?
           ORDER BY op.mention_count DESC, op.id ASC""",
        (run_id,),
    ).fetchall()

    feed = {
        "generated_at": datetime.now().isoformat(),
        "pipeline_run_id": run_id,
        "summary": {
            "sources_scanned": run_row["sources_ingested"] if run_row else 0,
            "signal_passages": run_row["signal_passages"] if run_row else 0,
            "problems_extracted": run_row["problems_extracted"] if run_row else 0,
            "sub_questions": run_row["sub_questions_extracted"] if run_row else 0,
        },
        "problems": [],
    }

    for prob in problem_rows:
        # Get sub-questions for this problem
        sq_rows = conn.execute(
            """SELECT * FROM sub_questions WHERE problem_id = ? ORDER BY id""",
            (prob["id"],),
        ).fetchall()

        # Get source details
        source_ids = json.loads(prob["source_ids"]) if prob["source_ids"] else []
        sources_detail = []
        for sid in source_ids:
            src = conn.execute(
                "SELECT id, source_type, title, url FROM sources WHERE id = ?", (sid,)
            ).fetchone()
            if src:
                detail = {
                    "id": src["id"],
                    "type": src["source_type"],
                    "title": src["title"],
                }
                if src["url"]:
                    detail["url"] = src["url"]
                sources_detail.append(detail)

        entry = {
            "problem_statement": prob["canonical_statement"],
            "domain": prob["domain"],
            "subdomain": prob["subdomain"],
            "scope": prob["scope"],
            "mention_count": prob["mention_count"],
            "sources": sources_detail,
            "sub_questions": [
                {
                    "question": sq["question"],
                    "evidence_needed": sq["evidence_needed"],
                    "disciplines": json.loads(sq["disciplines"]) if sq["disciplines"] else [],
                    "estimated_complexity": sq["estimated_complexity"],
                }
                for sq in sq_rows
            ],
            "related_keywords": json.loads(prob["related_keywords"]) if prob["related_keywords"] else [],
        }
        if prob["provenance"]:
            entry["provenance"] = json.loads(prob["provenance"])
        feed["problems"].append(entry)

    with open(output_path, "w") as f:
        json.dump(feed, f, indent=2)

    return output_path


def export_all_json_feed(
    conn: sqlite3.Connection,
    output_path: Path | None = None,
) -> Path:
    """Export ALL problems from the database as a JSON feed file."""
    output_path = output_path or RESULTS_DIR / "problems_feed.json"

    # Aggregate stats across all runs
    stats = conn.execute(
        """SELECT
            SUM(sources_ingested) as sources,
            SUM(signal_passages) as signals,
            SUM(problems_extracted) as problems,
            SUM(sub_questions_extracted) as sub_q
           FROM pipeline_runs"""
    ).fetchone()

    # Get all problems
    problem_rows = conn.execute(
        """SELECT * FROM open_problems
           ORDER BY mention_count DESC, id ASC"""
    ).fetchall()

    feed = {
        "generated_at": datetime.now().isoformat(),
        "pipeline_run_id": "all",
        "summary": {
            "sources_scanned": stats["sources"] if stats else 0,
            "signal_passages": stats["signals"] if stats else 0,
            "problems_extracted": len(problem_rows),
            "sub_questions": stats["sub_q"] if stats else 0,
        },
        "problems": [],
    }

    for prob in problem_rows:
        sq_rows = conn.execute(
            """SELECT * FROM sub_questions WHERE problem_id = ? ORDER BY id""",
            (prob["id"],),
        ).fetchall()

        source_ids = json.loads(prob["source_ids"]) if prob["source_ids"] else []
        sources_detail = []
        for sid in source_ids:
            src = conn.execute(
                "SELECT id, source_type, title, url FROM sources WHERE id = ?", (sid,)
            ).fetchone()
            if src:
                detail = {
                    "id": src["id"],
                    "type": src["source_type"],
                    "title": src["title"],
                }
                if src["url"]:
                    detail["url"] = src["url"]
                sources_detail.append(detail)

        entry = {
            "problem_statement": prob["canonical_statement"],
            "domain": prob["domain"],
            "subdomain": prob["subdomain"],
            "scope": prob["scope"],
            "mention_count": prob["mention_count"],
            "sources": sources_detail,
            "sub_questions": [
                {
                    "question": sq["question"],
                    "evidence_needed": sq["evidence_needed"],
                    "disciplines": json.loads(sq["disciplines"]) if sq["disciplines"] else [],
                    "estimated_complexity": sq["estimated_complexity"],
                }
                for sq in sq_rows
            ],
            "related_keywords": json.loads(prob["related_keywords"]) if prob["related_keywords"] else [],
        }
        if prob["provenance"]:
            entry["provenance"] = json.loads(prob["provenance"])
        feed["problems"].append(entry)

    with open(output_path, "w") as f:
        json.dump(feed, f, indent=2)

    return output_path
