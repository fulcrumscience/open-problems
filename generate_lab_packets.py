#!/usr/bin/env python3
"""Generate lab packet designs for GO NOW candidates using Claude.

Reads go_now candidates from feasibility_rankings.json, generates detailed
experiment designs for each, and outputs go_now_lab_packets.json.

Usage:
    python generate_lab_packets.py [--budget 2.0] [--force]
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import anthropic

from pipeline import CostTracker, BudgetExceeded, RESULTS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s | %(message)s")
logger = logging.getLogger("lab_packets")

RANKINGS_PATH = RESULTS_DIR / "feasibility_rankings.json"
OUTPUT_PATH = RESULTS_DIR / "go_now_lab_packets.json"

LAB_PACKET_PROMPT = """\
You are a senior research scientist designing a concrete, actionable experiment \
to address an open scientific problem identified from peer review or workshop reports.

Generate a detailed lab packet for the following problem and sub-question. \
The packet should be specific enough that a competent postdoc could execute it \
with minimal additional design work.

PROBLEM: {problem_statement}
DOMAIN: {domain} / {subdomain}
SCOPE: {scope}

TARGET SUB-QUESTION (the one classified as "go_now"):
{sub_question}

EVIDENCE NEEDED:
{evidence_needed}

RELEVANT DISCIPLINES: {disciplines}

Generate a JSON lab packet with this exact structure:
{{
  "title": "concise experiment title (< 15 words)",
  "objective": "one-sentence goal of the experiment",
  "readouts": [
    "Primary: the main measurable outcome",
    "Secondary: supporting measurement 1",
    "Secondary: supporting measurement 2"
  ],
  "design": {{
    "overview": "1-2 sentence experimental strategy",
    "work_packages": [
      "WP1: first phase of work",
      "WP2: second phase",
      "WP3: third phase",
      "WP4: analysis and QC"
    ],
    "controls": [
      "Positive control description",
      "Negative control description",
      "Technical control if applicable"
    ],
    "sample_size_plan": "How many replicates, samples, conditions",
    "success_criteria": [
      "Quantitative threshold for success criterion 1",
      "Quantitative threshold for success criterion 2"
    ],
    "estimated_timeline_weeks": 12
  }},
  "materials": [
    {{
      "item": "specific reagent or equipment name",
      "supplier": "vendor name",
      "catalog_or_id": "catalog number",
      "purpose": "what it's used for in this experiment"
    }}
  ],
  "estimated_direct_cost_usd": {{
    "low": 5000,
    "high": 15000,
    "scope": "What's included and excluded in the estimate"
  }},
  "protocol_references": [
    {{
      "title": "published protocol or method paper title",
      "use": "how this reference informs the experiment design"
    }}
  ],
  "handoff_package_for_lab": [
    "Deliverable 1 the lab needs before starting",
    "Deliverable 2",
    "Deliverable 3"
  ]
}}

Be specific about:
- Real vendor names and plausible catalog numbers for key reagents
- Realistic sample sizes and timelines
- Quantitative success criteria (fold changes, p-values, thresholds)
- Appropriate controls for the experimental system

Respond with JSON only. No markdown fences.
"""


def load_go_now_candidates() -> list[dict]:
    """Load GO NOW candidates from feasibility rankings."""
    with open(RANKINGS_PATH) as f:
        rankings = json.load(f)

    candidates = []
    for prob in rankings["ranked_problems"]:
        if prob.get("decision_bucket") != "go_now":
            continue

        # Find the best go_now sub-question
        best_sq = None
        for sq in prob.get("sub_question_scores", []):
            if sq.get("decision") == "go_now":
                best_sq = sq
                break

        if best_sq:
            candidates.append({
                "problem_statement": prob["problem_statement"],
                "domain": prob["domain"],
                "subdomain": prob.get("subdomain", ""),
                "scope": prob.get("scope", "medium"),
                "sources": prob.get("sources", []),
                "best_score": prob["best_score"],
                "best_confidence": prob["best_confidence"],
                "sub_question": best_sq["question"],
                "evidence_needed": best_sq.get("evidence_needed", ""),
                "disciplines": best_sq.get("disciplines", []),
            })

    return candidates


def load_existing_packets() -> dict:
    """Load existing lab packets, keyed by problem statement."""
    if not OUTPUT_PATH.exists():
        return {}
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    return {
        exp["maps_to_problem_statement"]: exp
        for exp in data.get("experiments", [])
    }


async def generate_one_packet(
    client: anthropic.AsyncAnthropic,
    candidate: dict,
    packet_id: str,
    cost_tracker: CostTracker,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict | None:
    """Generate a lab packet for one GO NOW candidate."""
    prompt = LAB_PACKET_PROMPT.format(
        problem_statement=candidate["problem_statement"],
        domain=candidate["domain"],
        subdomain=candidate["subdomain"],
        scope=candidate["scope"],
        sub_question=candidate["sub_question"],
        evidence_needed=candidate["evidence_needed"],
        disciplines=", ".join(candidate.get("disciplines", [])),
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error("API error for %s: %s", packet_id, e)
        return None

    cost_tracker.record(
        model,
        response.usage.input_tokens,
        response.usage.output_tokens,
        stage="lab_packets",
    )

    if not response.content:
        logger.warning("Empty response for %s", packet_id)
        return None

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        packet = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON for %s: %s", packet_id, e)
        logger.debug("Raw response: %s", text[:500])
        return None

    # Wrap with metadata
    return {
        "id": packet_id,
        "title": packet.get("title", ""),
        "decision_bucket": "go_now",
        "best_score": candidate["best_score"],
        "best_confidence": candidate["best_confidence"],
        "maps_to_problem_statement": candidate["problem_statement"],
        "maps_to_sub_question": candidate["sub_question"],
        "objective": packet.get("objective", ""),
        "readouts": packet.get("readouts", []),
        "design": packet.get("design", {}),
        "materials": packet.get("materials", []),
        "estimated_direct_cost_usd": packet.get("estimated_direct_cost_usd", {}),
        "protocol_references": packet.get("protocol_references", []),
        "handoff_package_for_lab": packet.get("handoff_package_for_lab", []),
    }


async def generate_all_packets(candidates: list[dict], force: bool = False,
                                budget: float = 2.0) -> list[dict]:
    """Generate lab packets for all GO NOW candidates."""
    existing = load_existing_packets()
    cost_tracker = CostTracker(limit=budget)
    client = anthropic.AsyncAnthropic()

    packets = []
    next_id = len(existing) + 1

    for candidate in candidates:
        ps = candidate["problem_statement"]

        if ps in existing and not force:
            logger.info("SKIP (already exists): %s", ps[:80])
            packets.append(existing[ps])
            continue

        packet_id = f"opc-go-{next_id:03d}"
        logger.info("Generating %s: %s", packet_id, ps[:80])

        try:
            packet = await generate_one_packet(
                client, candidate, packet_id, cost_tracker
            )
        except BudgetExceeded:
            logger.error("Budget exceeded. Stopping generation.")
            break

        if packet:
            packets.append(packet)
            next_id += 1
            cost_tracker.log_status()
        else:
            logger.warning("Failed to generate packet for: %s", ps[:80])

    return packets


def write_output(packets: list[dict]) -> Path:
    """Write lab packets JSON."""
    output = {
        "generated_at": datetime.now().isoformat(),
        "criteria_version": "feasibility_go_no_go_v2",
        "go_now_problem_count": len(packets),
        "notes": [
            "These packets are pre-POC designs for external lab discussion, not final SOPs.",
            "All experiments require institution-specific biosafety, GMO, and permit review before execution.",
            "Vendor catalogs and availability should be revalidated at ordering time.",
        ],
        "experiments": packets,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    return OUTPUT_PATH


def main():
    parser = argparse.ArgumentParser(description="Generate lab packets for GO NOW candidates")
    parser.add_argument("--budget", type=float, default=2.0,
                        help="Max LLM spend in USD (default: 2.0)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate packets even if they already exist")
    args = parser.parse_args()

    candidates = load_go_now_candidates()
    logger.info("Found %d GO NOW candidates", len(candidates))

    if not candidates:
        logger.warning("No GO NOW candidates found in %s", RANKINGS_PATH)
        sys.exit(0)

    for i, c in enumerate(candidates, 1):
        logger.info("  %d. %s", i, c["problem_statement"][:80])

    packets = asyncio.run(generate_all_packets(candidates, args.force, args.budget))

    path = write_output(packets)
    logger.info("Wrote %d lab packets to %s", len(packets), path)


if __name__ == "__main__":
    main()
