"""Stage 1a: eLife peer review ingestion via API + HTML scraping."""

import asyncio
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from pipeline import Source, load_config

logger = logging.getLogger("collector.ingest_reviews")

ELIFE_API = "https://api.elifesciences.org"
ELIFE_WEB = "https://elifesciences.org"


async def fetch_reviewed_preprint_ids(
    client: httpx.AsyncClient,
    subjects: list[str],
    max_per_subject: int = 50,
) -> list[dict]:
    """Fetch reviewed preprint metadata from eLife search API.

    Returns list of dicts: {id, version, title, authorLine, published, subjects, doi}.
    Deduplicates across subjects.
    """
    seen = set()
    items = []

    for subject in subjects:
        page = 1
        collected = 0
        while collected < max_per_subject:
            per_page = min(20, max_per_subject - collected)
            params = {
                "subject[]": subject,
                "type[]": "reviewed-preprint",
                "per-page": per_page,
                "page": page,
                "order": "desc",
            }
            resp = await client.get(f"{ELIFE_API}/search", params=params)
            resp.raise_for_status()
            data = resp.json()

            batch = data.get("items", [])
            if not batch:
                break

            for item in batch:
                msid = item["id"]
                if msid not in seen:
                    seen.add(msid)
                    items.append({
                        "id": msid,
                        "version": item.get("version", 1),
                        "title": item.get("title", ""),
                        "authorLine": item.get("authorLine", ""),
                        "published": item.get("published", ""),
                        "subjects": [s["id"] for s in item.get("subjects", [])],
                        "doi": item.get("doi", ""),
                    })
                    collected += 1

            page += 1
            total = data.get("total", 0)
            if page * per_page >= total:
                break

        logger.info("Subject %s: fetched %d preprints", subject, collected)

    logger.info("Total unique reviewed preprints: %d", len(items))
    return items


async def fetch_review_text(
    client: httpx.AsyncClient,
    msid: int | str,
    version: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, str] | None:
    """Fetch and parse peer review text from an eLife reviewed preprint.

    Returns dict of {section_id: text} keyed by peer-review-N, or None on failure.
    """
    async with semaphore:
        url = f"{ELIFE_WEB}/reviewed-preprints/{msid}v{version}/reviews"
        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning("HTTP %d for %s", resp.status_code, url)
                return None
        except httpx.HTTPError as e:
            logger.warning("HTTP error fetching %s: %s", url, e)
            return None

        return _parse_review_html(resp.text, msid)


def _parse_review_html(html: str, msid: int | str) -> dict[str, str] | None:
    """Extract reviewer comment text from eLife review page HTML.

    Looks for sections with id='peer-review-N' and extracts paragraph text
    from the review-content_body div inside each.
    Returns dict keyed by section id (e.g. 'peer-review-0').
    """
    soup = BeautifulSoup(html, "html.parser")

    sections = {}

    # Find all peer review sections (peer-review-0, peer-review-1, ...)
    review_sections = soup.find_all(
        id=re.compile(r"^peer-review-\d+$")
    )

    for section in review_sections:
        section_id = section.get("id", "unknown")
        body = section.find(class_="review-content_body")
        if not body:
            continue

        paragraphs = body.find_all("p")
        if not paragraphs:
            continue

        section_text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        if section_text:
            sections[section_id] = section_text

    if not sections:
        logger.debug("No review sections found for %s", msid)
        return None

    return sections


async def ingest_elife_reviews(config: dict | None = None) -> list[Source]:
    """Ingest eLife peer reviews as Source objects.

    Fetches reviewed preprint metadata from the API, then scrapes review
    HTML for each. Applies rate limiting to be polite to eLife servers.
    """
    config = config or load_config()
    elife_cfg = config.get("sources", {}).get("elife_reviews", {})

    subjects = elife_cfg.get("subjects", ["biochemistry-chemical-biology"])
    max_per_subject = elife_cfg.get("max_per_subject", 50)
    rate_limit_delay = elife_cfg.get("rate_limit_delay", 1.0)

    # Concurrent HTML fetches (polite: max 2 at a time)
    semaphore = asyncio.Semaphore(2)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Stage 1: Fetch preprint metadata
        logger.info("Fetching eLife reviewed preprint listings...")
        preprints = await fetch_reviewed_preprint_ids(client, subjects, max_per_subject)

        if not preprints:
            logger.warning("No eLife preprints found")
            return []

        # Stage 2: Fetch review text for each preprint
        logger.info("Fetching review text for %d preprints...", len(preprints))
        sources = []

        for i, pp in enumerate(preprints):
            msid = pp["id"]
            version = pp["version"]
            source_id = f"elife-{msid}v{version}"

            review_sections = await fetch_review_text(client, msid, version, semaphore)

            if not review_sections:
                logger.debug("No review text for %s, skipping", source_id)
                continue

            # Parse authors from authorLine (e.g., "Smith, Jones et al.")
            authors = [a.strip() for a in pp.get("authorLine", "").split(",")] if pp.get("authorLine") else []

            published = pp.get("published", "")
            if published:
                try:
                    published = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass

            source = Source(
                source_id=source_id,
                source_type="elife_review",
                title=pp.get("title", ""),
                authors=authors,
                organization="eLife",
                date_published=published,
                url=f"{ELIFE_WEB}/reviewed-preprints/{msid}v{version}",
                full_text="\n\n".join(review_sections.values()),
                sections=review_sections,
            )
            sources.append(source)

            if (i + 1) % 10 == 0:
                logger.info("  Fetched reviews: %d/%d (%d with text)",
                            i + 1, len(preprints), len(sources))

            # Rate limit
            await asyncio.sleep(rate_limit_delay)

    logger.info("eLife ingestion complete: %d/%d preprints yielded review text",
                len(sources), len(preprints))
    return sources


def ingest_elife_reviews_sync(config: dict | None = None) -> list[Source]:
    """Synchronous wrapper for ingest_elife_reviews."""
    return asyncio.run(ingest_elife_reviews(config))
