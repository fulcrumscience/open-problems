"""Stage 3: Open problem extraction and decomposition using Claude Sonnet."""

import asyncio
import json
import logging
import re

import anthropic

from pipeline import (
    Source, load_config, CHECKPOINTS_DIR, RESULTS_DIR,
    write_incremental_checkpoint, load_incremental_checkpoint,
    CostTracker, BudgetExceeded,
)

logger = logging.getLogger("collector.problem_extractor")

# Approximate tokens = chars / 4
MAX_INPUT_CHARS = 8000 * 4  # ~8K tokens

REVIEW_EXTRACTION_PROMPT = """\
You are extracting open scientific problems from peer review comments.

Given the following text passages (from peer reviewer comments on a scientific \
preprint), extract each distinct experimental gap, unresolved question, or \
missing evidence that the reviewers identified.

Focus on:
- Experiments the reviewers say are missing or needed
- Controls that are absent
- Alternative explanations that haven't been ruled out
- Evidence that would be needed to support the authors' claims
- Methodological limitations that need to be addressed

For each problem, provide:

1. The open problem or experimental gap as identified by the reviewer
2. The scientific domain (e.g., "protein engineering", "cell biology", \
"biochemistry", "genomics")
3. The scope: "narrow" (a single specific question), "medium" (decomposes into \
2-5 sub-questions), or "broad" (requires a research program)
4. If the scope is medium or narrow, decompose into specific sub-questions that \
could each be answered by a single study or experiment
5. For each sub-question, describe what kind of evidence or experiment would \
answer it
6. What disciplines or expertise areas are relevant

Ignore problems that are purely:
- Presentation issues ("the figures should be improved")
- Minor editorial concerns ("the writing is unclear")
- Computational/algorithmic ("better models are needed")
- Already addressed in author responses

Respond with JSON only:
{
  "problems": [
    {
      "problem_statement": "the stated open problem",
      "domain": "scientific domain",
      "subdomain": "more specific area",
      "scope": "narrow|medium|broad",
      "sub_questions": [
        {
          "question": "specific sub-question",
          "evidence_needed": "what kind of study or experiment would answer this",
          "disciplines": ["relevant", "fields"],
          "estimated_complexity": "simple|medium|complex"
        }
      ],
      "original_text": "quote from reviewer supporting this extraction",
      "related_keywords": ["key", "terms", "for", "searching"],
      "notes": "any caveats"
    }
  ],
  "meta": {
    "total_problems_found": 5,
    "decomposable_count": 3,
    "non_decomposable_reasons": ["too broad", "purely editorial"]
  }
}

If there are no extractable problems meeting the criteria, return:
{"problems": [], "meta": {"total_problems_found": 0, "decomposable_count": 0, "non_decomposable_reasons": ["reason"]}}

Reviewed preprint: {source_title}
Reviewer comments:
"""


EXTRACTION_PROMPT = """\
You are extracting open scientific problems from a document.

Given the following text passages (from a review article or workshop report), \
extract each distinct open problem, knowledge gap, or unresolved question.

For each problem, provide:

1. The open problem or question as stated
2. The scientific domain (e.g., "protein engineering", "antimicrobial resistance", \
"gene regulation", "catalysis", "genomics")
3. The scope: "narrow" (a single specific question), "medium" (decomposes into \
2-5 sub-questions), or "broad" (requires a research program)
4. If the scope is medium or narrow, decompose into specific sub-questions that \
could each be answered by a single study or experiment
5. For each sub-question, describe what kind of evidence or experiment would \
answer it
6. What disciplines or expertise areas are relevant

Ignore problems that are purely:
- Computational/algorithmic ("better models are needed")
- Policy/regulatory ("guidelines should be updated")
- Infrastructure ("more sequencing capacity is needed")
- Too broad to decompose ("the field needs a paradigm shift")

Respond with JSON only:
{
  "problems": [
    {
      "problem_statement": "the stated open problem",
      "domain": "scientific domain",
      "subdomain": "more specific area",
      "scope": "narrow|medium|broad",
      "sub_questions": [
        {
          "question": "specific sub-question",
          "evidence_needed": "what kind of study or experiment would answer this",
          "disciplines": ["relevant", "fields"],
          "estimated_complexity": "simple|medium|complex"
        }
      ],
      "original_text": "quote from source supporting this extraction",
      "related_keywords": ["key", "terms", "for", "searching"],
      "notes": "any caveats"
    }
  ],
  "meta": {
    "total_problems_found": 5,
    "decomposable_count": 3,
    "non_decomposable_reasons": ["too broad", "purely computational"]
  }
}

If there are no extractable problems meeting the criteria, return:
{"problems": [], "meta": {"total_problems_found": 0, "decomposable_count": 0, "non_decomposable_reasons": ["reason"]}}

Source document: {source_title}
Signal passages:
"""


def _build_extraction_prompt(source_title: str, passages_text: str, source_type: str = "") -> str:
    """Render extraction prompt without treating JSON braces as format tokens."""
    if source_type == "elife_review":
        template = REVIEW_EXTRACTION_PROMPT
    else:
        template = EXTRACTION_PROMPT
    return template.replace("{source_title}", source_title) + passages_text


def _parse_json_response(text: str, truncated: bool = False) -> dict | None:
    """Parse JSON from LLM response, handling markdown fences and truncation.

    When the response was truncated (stop_reason=max_tokens), attempts to
    salvage complete problem objects from the partial JSON.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting outermost JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    if not truncated:
        return None

    # Truncated response — salvage complete problem objects from partial JSON
    # Find all complete {...} blocks within the "problems" array
    problems = []
    # Look for individual problem objects (complete ones end with a closing brace
    # followed by a comma or the end of the array)
    pattern = re.compile(
        r'\{\s*"problem_statement".*?\n\s*\}',
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        try:
            obj = json.loads(m.group())
            problems.append(obj)
        except json.JSONDecodeError:
            continue

    if problems:
        logger.info("Salvaged %d complete problems from truncated response", len(problems))
        return {
            "problems": problems,
            "meta": {
                "total_problems_found": len(problems),
                "decomposable_count": len(problems),
                "non_decomposable_reasons": ["response_truncated"],
            },
        }

    return None


def _build_extraction_input(source: Source) -> str:
    """Build the text input for extraction from a source's signal passages."""
    parts = []
    for i, passage in enumerate(source.signal_passages, 1):
        section = passage.get("section", "unknown")
        category = passage.get("signal_category", "?")
        text = passage.get("context_text", "")
        parts.append(f"[Passage {i}] (section: {section}, signal: {category})\n{text}")

    combined = "\n\n".join(parts)

    # Hard cap at ~8K tokens
    if len(combined) > MAX_INPUT_CHARS:
        combined = combined[:MAX_INPUT_CHARS] + "\n[TRUNCATED]"

    return combined


async def _extract_one(
    client: anthropic.AsyncAnthropic,
    source: Source,
    model: str,
    semaphore: asyncio.Semaphore,
    cost_tracker: CostTracker | None = None,
    retry_attempts: int = 3,
) -> Source:
    """Extract open problems from a single source document."""
    async with semaphore:
        passages_text = _build_extraction_input(source)
        prompt = _build_extraction_prompt(source.title, passages_text, source.source_type)

        for attempt in range(retry_attempts):
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                )

                if cost_tracker:
                    cost_tracker.record(
                        model,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        stage="stage3",
                    )

                if not response.content:
                    logger.warning("Empty response for %s, skipping", source.source_id)
                    source.problems = []
                    return source
                text = response.content[0].text
                truncated = response.stop_reason == "max_tokens"
                if truncated:
                    logger.warning("Response truncated for %s (%d chars), attempting salvage",
                                   source.source_id, len(text))
                parsed = _parse_json_response(text, truncated=truncated)

                if parsed:
                    source.problems = parsed.get("problems", [])
                    meta = parsed.get("meta", {})
                    logger.debug(
                        "Extracted %d problems from %s (decomposable: %d)",
                        meta.get("total_problems_found", len(source.problems)),
                        source.source_id,
                        meta.get("decomposable_count", 0),
                    )
                else:
                    logger.warning("Failed to parse extraction JSON for %s", source.source_id)
                    source.problems = []

                return source

            except BudgetExceeded:
                raise
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning("Rate limit hit, waiting %ds (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                wait = 2 ** (attempt + 1)
                logger.warning("API error for %s: %s, retrying in %ds",
                               source.source_id, e, wait)
                await asyncio.sleep(wait)

        logger.error("Failed to extract from %s after %d attempts",
                      source.source_id, retry_attempts)
        source.problems = []
        return source


def _get_already_extracted_ids() -> set[str]:
    """Return source_ids that already have problems in the DB."""
    import sqlite3
    db_path = RESULTS_DIR / "collector.db"
    if not db_path.exists():
        return set()
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT DISTINCT source_ids FROM open_problems"
        ).fetchall()
        conn.close()
        # source_ids is a JSON array — extract individual IDs
        ids = set()
        for r in rows:
            try:
                for sid in json.loads(r[0]):
                    ids.add(sid)
            except (json.JSONDecodeError, TypeError):
                pass
        return ids
    except Exception:
        return set()


async def extract_problems(
    sources: list[Source],
    run_id: str,
    config: dict | None = None,
    cost_tracker: CostTracker | None = None,
) -> list[Source]:
    """Extract open problems from all sources. Returns sources with problems attached."""
    config = config or load_config()
    llm_cfg = config["llm"]
    budget_cfg = config["budget"]

    model = llm_cfg["extractor_model"]
    max_concurrent = llm_cfg["max_concurrent_requests"]
    retry_attempts = llm_cfg["retry_attempts"]
    max_calls = budget_cfg["max_sonnet_calls"]

    # Skip sources already extracted in DB or current run checkpoint
    db_done = _get_already_extracted_ids()
    cp_done = load_incremental_checkpoint(run_id, "stage3")
    already_done = db_done | cp_done
    remaining = [s for s in sources if s.source_id not in already_done]

    if already_done:
        logger.info("Resuming Stage 3: %d already done (%d from DB, %d from checkpoint), %d remaining",
                     len(already_done), len(db_done), len(cp_done), len(remaining))

    # Budget check
    if len(remaining) > max_calls:
        logger.warning("Budget guard: %d sources exceeds max_sonnet_calls (%d). Truncating.",
                        len(remaining), max_calls)
        remaining = remaining[:max_calls]

    client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(max_concurrent)

    # Process in batches for incremental checkpointing
    batch_size = 10
    all_extracted = []

    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i + batch_size]
        logger.info("Extracting batch %d-%d of %d",
                     i + 1, min(i + batch_size, len(remaining)), len(remaining))

        tasks = [
            _extract_one(client, source, model, semaphore, cost_tracker, retry_attempts)
            for source in batch
        ]
        results = await asyncio.gather(*tasks)
        all_extracted.extend(results)

        # Incremental checkpoint
        write_incremental_checkpoint(run_id, "stage3", results)

        if cost_tracker:
            cost_tracker.log_status()

    # Merge with previously checkpointed results
    if already_done:
        cp_path = CHECKPOINTS_DIR / f"{run_id}_stage3_incremental.jsonl"
        if cp_path.exists():
            done_sources = {}
            with open(cp_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        done_sources[d["source_id"]] = Source.from_dict(d)
            all_extracted = list(done_sources.values())

    sources_with_problems = [s for s in all_extracted if s.problems]
    total_problems = sum(len(s.problems) for s in sources_with_problems)
    total_sub_q = sum(
        len(p.get("sub_questions", []))
        for s in sources_with_problems
        for p in s.problems
    )

    logger.info("Problem extraction: %d/%d sources yielded %d problems (%d sub-questions)",
                 len(sources_with_problems), len(all_extracted), total_problems, total_sub_q)

    return all_extracted


def extract_problems_sync(sources: list[Source], run_id: str,
                          config: dict | None = None,
                          cost_tracker: CostTracker | None = None) -> list[Source]:
    """Synchronous wrapper for extract_problems."""
    return asyncio.run(extract_problems(sources, run_id, config, cost_tracker))
