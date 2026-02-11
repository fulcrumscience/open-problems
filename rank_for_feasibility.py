#!/usr/bin/env python3
"""Rank open problems for feasibility screening suitability (go/no-go v2).

This script applies a stricter two-stage framework:
1) Eligibility gate: identify whether a sub-question is bench-testable.
2) Feasibility scoring: score safety, technique, reagent, cost, readiness,
   and tractability, then apply an uncertainty penalty from confidence.

Output:
- data/results/feasibility_rankings.json
"""

import json
import re
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Scoring config
# ---------------------------------------------------------------------------

WEIGHTS = {
    "biosafety": 0.20,
    "technique": 0.20,
    "reagent_availability": 0.15,
    "cost": 0.15,
    "readiness": 0.20,
    "tractability": 0.10,
}
THRESHOLDS = {"high": 0.50, "medium": 0.30}
DECISION_THRESHOLDS = {"go_now": 0.50, "needs_specification": 0.35}
CONFIDENCE_THRESHOLDS = {"go_now": 0.50, "needs_specification": 0.25}
UNCERTAINTY_BASE = 0.50  # final = raw * (base + (1-base)*confidence)

BIOSAFETY = {
    "disqualifiers": {
        "score": 0.0,
        "keywords": [
            "bsl-3", "bsl-4", "select agent", "animal model", "mouse model",
            "mice", "rat model", "in vivo", "clinical trial", "human subjects",
            "patient enrollment", "primate", "mycobacterium tuberculosis",
            "sars-cov", "ebola", "influenza virus",
        ],
    },
    "bsl2_plus_viral": {
        "score": 0.2,
        "keywords": [
            "dengue", "live virus", "viral infection", "viral stock",
            "plaque assay", "viral propagation", "virus culture",
        ],
    },
    "bsl2_organisms": {
        "score": 0.5,
        "keywords": [
            "human primary cells", "primary human", "patient-derived",
            "human blood", "human tissue", "lentivirus", "adenovirus",
            "bsl-2", "salmonella", "staphylococcus", "pseudomonas",
        ],
    },
    "non_biological_materials": {
        "score": 0.9,
        "keywords": [
            "ceramic", "oxide", "electrolyte", "battery", "composite",
            "solid-state", "xrd", "eis", "gitt", "sims", "materials synthesis",
        ],
    },
    "safe_organisms": {
        "score": 1.0,
        "keywords": [
            "e. coli", "escherichia coli", "recombinant protein",
            "purified protein", "protein expression", "yeast",
            "saccharomyces", "hela", "hek293", "hek 293", "cho cells",
            "cos-7", "jurkat", "mcf-7", "a549", "nih 3t3", "3t3",
            "vero", "sf9", "insect cells", "in vitro", "cell-free",
        ],
    },
    "default_unknown_score": 0.4,
}

TECHNIQUE_ACCESSIBILITY = [
    {"keywords": ["pcr", "qpcr", "qrt-pcr", "rt-pcr", "gel electrophoresis", "agarose gel", "cloning", "restriction digest", "ligation", "transformation"], "score": 1.0},
    {"keywords": ["mic assay", "minimum inhibitory concentration", "broth microdilution", "antimicrobial susceptibility"], "score": 0.9},
    {"keywords": ["cell culture", "viability assay", "mtt assay", "cytotoxicity", "proliferation assay", "cell viability"], "score": 0.8},
    {"keywords": ["circular dichroism", "cd spectroscopy", "uv-vis"], "score": 0.7},
    {"keywords": ["elisa", "binding assay", "plate reader", "colorimetric", "fluorescence assay"], "score": 0.8},
    {"keywords": ["western blot", "protein purification", "chromatography", "his-tag", "affinity purification", "sds-page"], "score": 0.6},
    {"keywords": ["flow cytometry", "facs", "microscopy", "fluorescence microscopy", "confocal"], "score": 0.5},
    {"keywords": ["mass spectrometry", "nmr", "surface plasmon resonance", "spr", "isothermal titration", "itc", "hplc"], "score": 0.3},
    {"keywords": ["cryo-em", "x-ray crystallography", "crystallography", "synchrotron", "saxs"], "score": 0.1},
    {"keywords": ["custom equipment", "specialized instrument", "custom-built"], "score": 0.0},
]
TECHNIQUE_DEFAULT = 0.4

COST_BY_COMPLEXITY = {"simple": 1.0, "medium": 0.65, "complex": 0.35}

REAGENT_AVAILABILITY = {
    "standard_catalog": {
        "score": 1.0,
        "keywords": [
            "commercially available", "sigma", "sigma-aldrich", "thermo",
            "thermo fisher", "invitrogen", "idt", "addgene", "atcc", "neb",
            "new england biolabs", "promega", "bio-rad", "abcam", "cell signaling",
        ],
    },
    "specialty_commercial": {
        "score": 0.7,
        "keywords": [
            "specialty supplier", "custom antibody", "cayman chemical",
            "tocris", "selleckchem", "medchemexpress",
        ],
    },
    "custom_synthesis": {
        "score": 0.5,
        "keywords": [
            "custom synthesis", "synthesized", "custom peptide",
            "custom dna", "custom oligo", "gene synthesis",
        ],
    },
    "author_specific": {
        "score": 0.2,
        "keywords": [
            "available upon request", "from the authors", "provided by",
            "gift from", "kindly provided",
        ],
    },
    "restricted": {
        "score": 0.0,
        "keywords": ["restricted", "controlled substance", "unavailable", "discontinued"],
    },
    "default_unknown_score": 0.4,
}

EXPERIMENT_ACTION_KEYWORDS = [
    "assay", "experiment", "mutagenesis", "gene editing", "knockout", "knock-in",
    "transformation", "culture", "screening", "reporter", "transfection",
    "insertion", "perturbation", "isotope tracing", "validation", "qtl", "gwas",
]
MEASUREMENT_ENDPOINT_KEYWORDS = [
    "measure", "quantify", "evaluate", "compare", "efficiency", "activity",
    "expression", "growth", "binding", "stability", "viability", "flux",
    "yield", "rate", "correlat", "readout", "endpoint",
]
SYSTEM_KEYWORDS = [
    "cell", "cells", "microbe", "microbial", "bacteria", "strain", "organism",
    "plant", "crop", "protein", "enzyme", "gene", "genome", "rna", "dna",
    "metabolite", "soil", "rhizosphere", "fermentation", "sample", "library",
]
CONTROL_DESIGN_KEYWORDS = [
    "control", "baseline", "wild-type", "versus", "vs.", "comparison", "matched",
]

POLICY_ONLY_KEYWORDS = [
    "policy", "regulatory", "governance", "international law", "incentive structures",
    "funding structures", "stakeholder", "capacity building", "cross-border",
]
INFRASTRUCTURE_ONLY_KEYWORDS = [
    "monitoring sites", "observational networks", "infrastructure bottlenecks",
    "site distribution", "global network", "long-term site",
]
COMPUTATIONAL_ONLY_KEYWORDS = [
    "scenario modeling", "agent-based modeling", "survey", "gap analysis",
    "comparative policy analysis", "techno-economic analysis",
]
MULTI_YEAR_SCALE_KEYWORDS = [
    "long-term", "multi-site", "multi-year", "global", "cross-border",
    "consortium", "worldwide", "regional and global scales",
]


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def _contains_keyword(text_lower: str, keyword: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    phrase = re.escape(kw).replace(r"\ ", r"\s+")
    pattern = rf"(?<![a-z0-9]){phrase}(?![a-z0-9])"
    return re.search(pattern, text_lower) is not None


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if _contains_keyword(text_lower, kw)]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def score_biosafety(text: str) -> tuple[float, dict]:
    bio = BIOSAFETY
    disq = _matched_keywords(text, bio["disqualifiers"]["keywords"])
    if disq:
        return 0.0, {"tier": "disqualifiers", "keywords": disq}

    for tier_key in ["bsl2_plus_viral", "bsl2_organisms", "non_biological_materials", "safe_organisms"]:
        tier = bio.get(tier_key)
        if not tier:
            continue
        m = _matched_keywords(text, tier["keywords"])
        if m:
            return float(tier["score"]), {"tier": tier_key, "keywords": m}

    return float(bio["default_unknown_score"]), {"tier": "default", "keywords": []}


def score_technique(text: str) -> tuple[float, dict]:
    matched = []
    for entry in TECHNIQUE_ACCESSIBILITY:
        m = _matched_keywords(text, entry["keywords"])
        if m:
            matched.append({"score": entry["score"], "keywords": m})

    if not matched:
        return TECHNIQUE_DEFAULT, {"matched": [], "defaulted": True}

    scores = sorted([e["score"] for e in matched])
    if len(scores) == 1:
        score = scores[0]
    else:
        score = 0.4 * scores[0] + 0.6 * statistics.median(scores)

    return score, {"matched": matched, "defaulted": False}


def score_cost(complexity: str) -> tuple[float, dict]:
    c = (complexity or "medium").lower()
    return float(COST_BY_COMPLEXITY.get(c, COST_BY_COMPLEXITY["medium"])), {"complexity": c}


def score_reagent(text: str) -> tuple[float, dict]:
    for tier_key in ["restricted", "author_specific", "custom_synthesis", "specialty_commercial", "standard_catalog"]:
        tier = REAGENT_AVAILABILITY[tier_key]
        m = _matched_keywords(text, tier["keywords"])
        if m:
            return float(tier["score"]), {"tier": tier_key, "keywords": m}

    return float(REAGENT_AVAILABILITY["default_unknown_score"]), {"tier": "default", "keywords": []}


def score_readiness(text: str) -> tuple[float, dict]:
    action_hits = _matched_keywords(text, EXPERIMENT_ACTION_KEYWORDS)
    measure_hits = _matched_keywords(text, MEASUREMENT_ENDPOINT_KEYWORDS)
    system_hits = _matched_keywords(text, SYSTEM_KEYWORDS)
    control_hits = _matched_keywords(text, CONTROL_DESIGN_KEYWORDS)

    score = 0.0
    if action_hits:
        score += 0.4
    if measure_hits:
        score += 0.4
    if system_hits:
        score += 0.2
    if control_hits:
        score += 0.1
    if action_hits and measure_hits and system_hits:
        score += 0.1

    score = _clamp(score)
    return score, {
        "action_hits": action_hits,
        "measurement_hits": measure_hits,
        "system_hits": system_hits,
        "control_hits": control_hits,
        "signal_count": sum(bool(x) for x in [action_hits, measure_hits, system_hits]),
    }


def score_tractability(complexity: str, text: str) -> tuple[float, dict]:
    c = (complexity or "medium").lower()
    score = float(COST_BY_COMPLEXITY.get(c, COST_BY_COMPLEXITY["medium"]))

    penalties = []
    long_scale_hits = _matched_keywords(text, MULTI_YEAR_SCALE_KEYWORDS)
    infra_hits = _matched_keywords(text, INFRASTRUCTURE_ONLY_KEYWORDS)
    computational_only_hits = _matched_keywords(text, COMPUTATIONAL_ONLY_KEYWORDS)

    if long_scale_hits:
        score -= 0.20
        penalties.append("multi_year_or_scale")
    if infra_hits:
        score -= 0.15
        penalties.append("infrastructure")
    if computational_only_hits:
        score -= 0.10
        penalties.append("non_bench_emphasis")

    return _clamp(score), {
        "complexity": c,
        "penalties": penalties,
        "long_scale_hits": long_scale_hits,
        "infrastructure_hits": infra_hits,
        "computational_only_hits": computational_only_hits,
    }


# ---------------------------------------------------------------------------
# Eligibility + decisions
# ---------------------------------------------------------------------------

def evaluate_eligibility(text: str) -> dict:
    action_hits = _matched_keywords(text, EXPERIMENT_ACTION_KEYWORDS)
    measurement_hits = _matched_keywords(text, MEASUREMENT_ENDPOINT_KEYWORDS)
    system_hits = _matched_keywords(text, SYSTEM_KEYWORDS)
    policy_hits = _matched_keywords(text, POLICY_ONLY_KEYWORDS)
    infra_hits = _matched_keywords(text, INFRASTRUCTURE_ONLY_KEYWORDS)
    computational_hits = _matched_keywords(text, COMPUTATIONAL_ONLY_KEYWORDS)

    reasons = []
    eligible = True

    if not action_hits:
        eligible = False
        reasons.append("missing_experimental_action")
    if not measurement_hits:
        eligible = False
        reasons.append("missing_measurable_endpoint")
    if not system_hits:
        eligible = False
        reasons.append("missing_manipulable_system")

    blocker_hits = sorted(set(policy_hits + infra_hits + computational_hits))
    if blocker_hits and not action_hits:
        eligible = False
        reasons.append("policy_or_infrastructure_or_modeling_without_bench_plan")

    return {
        "eligible": eligible,
        "reasons": reasons,
        "blocker_hits": blocker_hits,
        "signals": {
            "action_hits": action_hits,
            "measurement_hits": measurement_hits,
            "system_hits": system_hits,
        },
    }


def _tier_from_score(score: float) -> str:
    if score >= THRESHOLDS["high"]:
        return "high"
    if score >= THRESHOLDS["medium"]:
        return "medium"
    return "low"


def _decision_from_scores(
    final_score: float,
    confidence: float,
    eligibility: dict,
    readiness_score: float,
) -> str:
    if not eligibility["eligible"]:
        return "needs_repositioning"
    if eligibility["blocker_hits"] and readiness_score < 0.5:
        return "needs_repositioning"
    if (
        final_score >= DECISION_THRESHOLDS["go_now"]
        and confidence >= CONFIDENCE_THRESHOLDS["go_now"]
    ):
        return "go_now"
    if (
        final_score >= DECISION_THRESHOLDS["needs_specification"]
        and confidence >= CONFIDENCE_THRESHOLDS["needs_specification"]
    ):
        return "needs_specification"
    return "needs_repositioning"


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def score_sub_question(sq: dict) -> dict:
    text = " ".join([
        sq.get("question", ""),
        sq.get("evidence_needed", ""),
        " ".join(sq.get("disciplines", [])),
    ])
    complexity = sq.get("estimated_complexity", "medium")

    eligibility = evaluate_eligibility(text)
    bio_score, bio_detail = score_biosafety(text)
    tech_score, tech_detail = score_technique(text)
    reagent_score, reagent_detail = score_reagent(text)
    cost_score, cost_detail = score_cost(complexity)
    readiness_score, readiness_detail = score_readiness(text)
    tractability_score, tractability_detail = score_tractability(complexity, text)

    raw_score = (
        WEIGHTS["biosafety"] * bio_score
        + WEIGHTS["technique"] * tech_score
        + WEIGHTS["reagent_availability"] * reagent_score
        + WEIGHTS["cost"] * cost_score
        + WEIGHTS["readiness"] * readiness_score
        + WEIGHTS["tractability"] * tractability_score
    )

    if bio_score == 0.0:
        raw_score = min(raw_score, 0.1)

    known_signals = [
        bio_detail.get("tier") != "default",
        not tech_detail.get("defaulted", False),
        reagent_detail.get("tier") != "default",
        readiness_detail.get("signal_count", 0) >= 2,
    ]
    confidence = sum(1 for s in known_signals if s) / len(known_signals)
    uncertainty_penalty = UNCERTAINTY_BASE + (1.0 - UNCERTAINTY_BASE) * confidence
    final_score = raw_score * uncertainty_penalty

    tier = _tier_from_score(final_score)
    decision = _decision_from_scores(final_score, confidence, eligibility, readiness_score)

    return {
        "composite": round(final_score, 3),
        "raw_score": round(raw_score, 3),
        "confidence": round(confidence, 3),
        "uncertainty_penalty": round(uncertainty_penalty, 3),
        "tier": tier,
        "decision": decision,
        "breakdown": {
            "biosafety": round(bio_score, 2),
            "technique": round(tech_score, 2),
            "cost": round(cost_score, 2),
            "reagent": round(reagent_score, 2),
            "readiness": round(readiness_score, 2),
            "tractability": round(tractability_score, 2),
        },
        "details": {
            "eligibility": eligibility,
            "biosafety": bio_detail,
            "technique": tech_detail,
            "cost": cost_detail,
            "reagent": reagent_detail,
            "readiness": readiness_detail,
            "tractability": tractability_detail,
        },
    }


def score_problem(problem: dict) -> dict:
    sq_scores = []
    for sq in problem.get("sub_questions", []):
        result = score_sub_question(sq)
        sq_scores.append({
            "question": sq["question"],
            "evidence_needed": sq.get("evidence_needed", ""),
            "complexity": sq.get("estimated_complexity", "medium"),
            **result,
        })

    decision_rank = {"go_now": 0, "needs_specification": 1, "needs_repositioning": 2}
    sq_scores.sort(key=lambda x: (decision_rank[x["decision"]], -x["composite"]))
    best = sq_scores[0] if sq_scores else None
    avg = statistics.mean([s["composite"] for s in sq_scores]) if sq_scores else 0.0
    avg_conf = statistics.mean([s["confidence"] for s in sq_scores]) if sq_scores else 0.0

    best_decision = best["decision"] if best else "needs_repositioning"

    return {
        "problem_statement": problem["problem_statement"],
        "domain": problem.get("domain", ""),
        "subdomain": problem.get("subdomain", ""),
        "scope": problem.get("scope", ""),
        "sources": [s["id"] for s in problem.get("sources", [])],
        "best_score": best["composite"] if best else 0.0,
        "best_tier": best["tier"] if best else "low",
        "best_confidence": best["confidence"] if best else 0.0,
        "decision_bucket": best_decision,
        "avg_score": round(avg, 3),
        "avg_confidence": round(avg_conf, 3),
        "num_sub_questions": len(sq_scores),
        "go_now_count": sum(1 for s in sq_scores if s["decision"] == "go_now"),
        "needs_specification_count": sum(1 for s in sq_scores if s["decision"] == "needs_specification"),
        "needs_repositioning_count": sum(1 for s in sq_scores if s["decision"] == "needs_repositioning"),
        "high_tier_count": sum(1 for s in sq_scores if s["tier"] == "high"),
        "medium_tier_count": sum(1 for s in sq_scores if s["tier"] == "medium"),
        "low_tier_count": sum(1 for s in sq_scores if s["tier"] == "low"),
        "sub_question_scores": sq_scores,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    feed_path = Path(__file__).parent / "data" / "results" / "problems_feed.json"
    if not feed_path.exists():
        print(f"ERROR: {feed_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(feed_path) as f:
        data = json.load(f)

    problems = data["problems"]
    scored = [score_problem(p) for p in problems]
    decision_rank = {"go_now": 0, "needs_specification": 1, "needs_repositioning": 2}
    scored.sort(key=lambda x: (decision_rank[x["decision_bucket"]], -x["best_score"]))

    go_now = [p for p in scored if p["decision_bucket"] == "go_now"]
    needs_spec = [p for p in scored if p["decision_bucket"] == "needs_specification"]
    not_fit = [p for p in scored if p["decision_bucket"] == "needs_repositioning"]

    out = {
        "criteria_version": "feasibility_go_no_go_v2",
        "summary": {
            "total_problems": len(scored),
            "go_now": len(go_now),
            "needs_specification": len(needs_spec),
            "needs_repositioning": len(not_fit),
        },
        "ranked_problems": scored,
    }

    out_path = feed_path.parent / "feasibility_rankings.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print("\n" + "=" * 72)
    print(f"FEASIBILITY GO/NO-GO RANKING (v2) — {len(scored)} open problems")
    print("=" * 72)
    print(f"\n  GO NOW:              {len(go_now)}")
    print(f"  NEEDS SPECIFICATION: {len(needs_spec)}")
    print(f"  NEEDS REPOSITIONING:      {len(not_fit)}")

    print("\n" + "-" * 72)
    print("TOP GO-NOW CANDIDATES")
    print("-" * 72 + "\n")
    for i, p in enumerate(go_now[:20], 1):
        stmt = p["problem_statement"]
        if len(stmt) > 90:
            stmt = stmt[:87] + "..."
        print(f"  [+] {i:2d}. ({p['best_score']:.2f}, conf {p['best_confidence']:.2f}) {stmt}")
        print(f"       domain: {p['domain']}")
        print(
            f"       go/needs/not-fit sub-questions: "
            f"{p['go_now_count']}/{p['needs_specification_count']}/{p['needs_repositioning_count']}"
        )
        best_sq = p["sub_question_scores"][0] if p["sub_question_scores"] else None
        if best_sq:
            q = best_sq["question"]
            if len(q) > 80:
                q = q[:77] + "..."
            bd = best_sq["breakdown"]
            print(f"       best sub-Q: {q}")
            print(
                "       breakdown: "
                f"bio={bd['biosafety']:.1f} tech={bd['technique']:.1f} "
                f"reag={bd['reagent']:.1f} cost={bd['cost']:.1f} "
                f"ready={bd['readiness']:.1f} tract={bd['tractability']:.1f}"
            )
        print()

    print(f"Full rankings written to: {out_path}")


if __name__ == "__main__":
    main()
