"""Stage 1e: OpenAlex academic paper ingestion for energy/sustainability topics.

Fetches review articles and editorials from the OpenAlex API based on
configurable topic searches.  Each paper's abstract is extracted and fed
through the standard signal filter -> LLM extraction pipeline.

Citation count and journal impact (2yr_mean_citedness) are fetched and
combined into a composite impact_score for ranking/filtering.

OpenAlex API: https://docs.openalex.org/
No API key required. Uses polite pool with email in User-Agent.
"""

import asyncio
import logging
import math
from pathlib import Path

import httpx
import yaml

from pipeline import Source, CONFIG_DIR, load_config

logger = logging.getLogger("collector.ingest_openalex")

OPENALEX_API = "https://api.openalex.org"


# ── Config helpers ─────────────────────────────────────────────────────

def _load_topics(config: dict) -> tuple[list[dict], dict]:
    """Load topic definitions from energy_topics.yaml."""
    openalex_cfg = config.get("sources", {}).get("openalex", {})
    topics_file = openalex_cfg.get("topics_file", "config/energy_topics.yaml")
    topics_path = CONFIG_DIR.parent / topics_file

    with open(topics_path) as f:
        data = yaml.safe_load(f)

    return data.get("topics", []), data.get("defaults", {})


# ── Abstract reconstruction ────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct plain text from OpenAlex inverted-index abstract.

    OpenAlex stores abstracts as {"word": [pos0, pos5, ...]}. We invert
    this into a flat (position, word) list, sort by position, and join.
    """
    if not inverted_index:
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            pairs.append((pos, word))
    pairs.sort(key=lambda x: x[0])
    return " ".join(word for _, word in pairs)


def _extract_openalex_id(openalex_url: str) -> str:
    """Extract short ID from an OpenAlex URL.

    e.g. 'https://openalex.org/W2123456789' -> 'W2123456789'
    """
    return openalex_url.rstrip("/").split("/")[-1]


# ── Journal impact cache ──────────────────────────────────────────────

async def _fetch_journal_impact(
    client: httpx.AsyncClient,
    source_id: str,
    cache: dict[str, dict],
    rate_limit_delay: float = 0.5,
) -> dict:
    """Fetch journal impact metrics from /sources/{id}.

    Returns dict with 'display_name', '2yr_mean_citedness', 'h_index'.
    Results are cached so each journal is fetched only once.
    """
    if source_id in cache:
        return cache[source_id]

    try:
        resp = await client.get(
            f"{OPENALEX_API}/sources/{source_id}",
            params={"select": "id,display_name,summary_stats"},
        )
        resp.raise_for_status()
        data = resp.json()
        stats = data.get("summary_stats", {})
        result = {
            "display_name": data.get("display_name", ""),
            "2yr_mean_citedness": stats.get("2yr_mean_citedness", 0.0),
            "h_index": stats.get("h_index", 0),
        }
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.debug("Could not fetch journal impact for %s: %s", source_id, e)
        result = {"display_name": "", "2yr_mean_citedness": 0.0, "h_index": 0}

    cache[source_id] = result
    await asyncio.sleep(rate_limit_delay)
    return result


# ── Impact scoring ────────────────────────────────────────────────────

def compute_impact_score(cited_by_count: int, journal_2yr_citedness: float) -> float:
    """Composite impact score: log1p(citations) * (1 + journal_impact).

    This boosts papers that are both highly cited and in high-impact journals.
    Returns 0.0 for uncitable or unknown papers.
    """
    return math.log1p(cited_by_count) * (1.0 + journal_2yr_citedness)


# ── OpenAlex API search ──────────────────────────────────────────────

async def search_openalex_works(
    client: httpx.AsyncClient,
    query: str,
    doc_types: list[str],
    source_ids: list[str] | None = None,
    from_year: int = 2025,
    max_results: int = 50,
    rate_limit_delay: float = 0.5,
) -> list[dict]:
    """Search OpenAlex for works matching query and filters.

    Uses cursor-based pagination. Returns list of raw work dicts.
    Results are sorted by cited_by_count descending.
    """
    filter_parts = [
        f"default.search:{query}",
        f"type:{'|'.join(doc_types)}",
        "has_abstract:true",
        f"from_publication_date:{from_year}-01-01",
    ]
    if source_ids:
        filter_parts.append(
            f"primary_location.source.id:{'|'.join(source_ids)}"
        )

    filter_str = ",".join(filter_parts)

    works: list[dict] = []
    cursor = "*"
    per_page = min(50, max_results)

    while len(works) < max_results and cursor:
        params = {
            "filter": filter_str,
            "per_page": per_page,
            "cursor": cursor,
            "sort": "cited_by_count:desc",
            "select": (
                "id,doi,title,display_name,publication_year,"
                "authorships,primary_location,abstract_inverted_index,"
                "cited_by_count"
            ),
        }

        resp = await client.get(f"{OPENALEX_API}/works", params=params)
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("results", [])
        if not batch:
            break

        works.extend(batch)
        cursor = data.get("meta", {}).get("next_cursor")

        await asyncio.sleep(rate_limit_delay)

    return works[:max_results]


# ── Source building ───────────────────────────────────────────────────

def _build_source_from_work(
    work: dict,
    topic_label: str,
    journal_impact: dict | None = None,
) -> Source | None:
    """Convert an OpenAlex work dict to a Source object.

    Returns None if the work has no reconstructable abstract.
    """
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    if not abstract:
        return None

    openalex_id = _extract_openalex_id(work.get("id", ""))

    # Authors (cap at 10)
    authors: list[str] = []
    for authorship in work.get("authorships", [])[:10]:
        name = authorship.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    # Journal
    primary_loc = work.get("primary_location") or {}
    source_info = primary_loc.get("source") or {}
    journal = source_info.get("display_name", "")

    # URL: prefer DOI, fall back to OpenAlex URL
    url = work.get("doi") or work.get("id", "")

    # Citation & impact metrics
    cited_by_count = work.get("cited_by_count", 0) or 0
    journal_2yr = (journal_impact or {}).get("2yr_mean_citedness", 0.0)
    impact_score = compute_impact_score(cited_by_count, journal_2yr)

    return Source(
        source_id=f"openalex-{openalex_id}",
        source_type="openalex_review",
        title=work.get("title") or work.get("display_name", ""),
        authors=authors,
        organization=journal,
        date_published=str(work.get("publication_year", "")),
        url=url,
        full_text=abstract,
        sections={"abstract": abstract},
        metadata={
            "cited_by_count": cited_by_count,
            "journal_2yr_citedness": journal_2yr,
            "journal_h_index": (journal_impact or {}).get("h_index", 0),
            "impact_score": round(impact_score, 3),
            "topic_label": topic_label,
            "openalex_id": openalex_id,
        },
    )


# ── Main ingestion ───────────────────────────────────────────────────

async def ingest_openalex(config: dict | None = None) -> list[Source]:
    """Fetch review articles from OpenAlex for all configured energy topics.

    Sources are deduplicated across topics and sorted by impact_score.
    """
    config = config or load_config()
    openalex_cfg = config.get("sources", {}).get("openalex", {})

    topics, defaults = _load_topics(config)

    from_year = openalex_cfg.get("from_year", defaults.get("from_year", 2025))
    default_max = openalex_cfg.get("max_per_topic", 25)
    default_doc_types = openalex_cfg.get(
        "doc_types", defaults.get("doc_types", ["review", "editorial"])
    )
    min_impact = openalex_cfg.get("min_impact_score", 0)
    email = openalex_cfg.get("email", defaults.get("email", ""))
    rate_limit_delay = openalex_cfg.get(
        "rate_limit_delay", defaults.get("rate_limit_delay", 0.5)
    )

    headers = {}
    if email:
        headers["User-Agent"] = f"open-problem-collector/1.0 (mailto:{email})"

    seen_ids: set[str] = set()
    sources: list[Source] = []
    journal_cache: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for topic in topics:
            label = topic["label"]
            query = topic["search"]
            doc_types = topic.get("doc_types", default_doc_types)
            source_ids = topic.get("source_ids")
            max_results = topic.get("max_results", default_max)

            logger.info("Searching OpenAlex: %s", label)

            try:
                works = await search_openalex_works(
                    client, query, doc_types, source_ids,
                    from_year, max_results, rate_limit_delay,
                )
            except httpx.HTTPError as e:
                logger.warning("Failed to search topic '%s': %s", label, e)
                continue

            topic_count = 0
            for work in works:
                oa_id = _extract_openalex_id(work.get("id", ""))
                if oa_id in seen_ids:
                    continue
                seen_ids.add(oa_id)

                # Fetch journal impact (cached per journal)
                ji = None
                primary_loc = work.get("primary_location") or {}
                src_info = primary_loc.get("source") or {}
                src_oa_id = src_info.get("id", "")
                if src_oa_id:
                    ji = await _fetch_journal_impact(
                        client, _extract_openalex_id(src_oa_id),
                        journal_cache, rate_limit_delay,
                    )

                source = _build_source_from_work(work, label, ji)
                if source:
                    sources.append(source)
                    topic_count += 1

            logger.info(
                "  '%s': %d works fetched, %d new sources",
                label, len(works), topic_count,
            )

    # Filter by minimum impact score
    if min_impact > 0:
        before = len(sources)
        sources = [
            s for s in sources
            if s.metadata.get("impact_score", 0) >= min_impact
        ]
        logger.info("Impact filter: %d -> %d sources (min_impact_score=%.1f)",
                     before, len(sources), min_impact)

    # Sort by impact score descending
    sources.sort(key=lambda s: s.metadata.get("impact_score", 0), reverse=True)

    logger.info(
        "OpenAlex ingestion complete: %d unique sources from %d topics "
        "(journals cached: %d)",
        len(sources), len(topics), len(journal_cache),
    )
    return sources


def ingest_openalex_sync(config: dict | None = None) -> list[Source]:
    """Synchronous wrapper for ingest_openalex."""
    return asyncio.run(ingest_openalex(config))
