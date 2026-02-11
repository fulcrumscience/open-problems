"""Open Problem Collector pipeline."""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

# ── Path constants ──────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
WORKSHOPS_DIR = DATA_DIR / "workshops"
RESULTS_DIR = DATA_DIR / "results"
LOGS_DIR = DATA_DIR / "logs"
CHECKPOINTS_DIR = DATA_DIR / "checkpoints"
CONFIG_DIR = ROOT_DIR / "config"

for d in [WORKSHOPS_DIR, RESULTS_DIR, LOGS_DIR, CHECKPOINTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── Logging ─────────────────────────────────────────────────────────────────

def setup_logging(run_id: str | None = None) -> logging.Logger:
    """Configure pipeline logging to console and file."""
    logger = logging.getLogger("collector")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s",
                            datefmt="%H:%M:%S")

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if run_id:
        fh = logging.FileHandler(LOGS_DIR / f"{run_id}.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ── Config loader ───────────────────────────────────────────────────────────

def load_config(path: Path | None = None) -> dict:
    """Load config.yaml from project root."""
    path = path or ROOT_DIR / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_signal_phrases(path: Path | None = None) -> dict:
    path = path or CONFIG_DIR / "signal_phrases.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


# ── Source dataclass ────────────────────────────────────────────────────────

@dataclass
class Source:
    """Core data object carried through all pipeline stages."""
    # Identity
    source_id: str          # e.g. "nih-workshop-amr-2025"
    source_type: str        # "workshop_report", "review_article", etc.

    # Metadata (Stage 1)
    title: str = ""
    authors: list[str] = field(default_factory=list)
    organization: str = ""  # "NIH/NIAID", "NSF", etc.
    date_published: str = ""
    url: str = ""
    pdf_path: Optional[str] = None

    # Text extraction (Stage 1b)
    full_text: Optional[str] = None
    sections: Optional[dict] = None  # {section_name: text}

    # Signal filter (Stage 2)
    signal_passages: list[dict] = field(default_factory=list)
    # Each: {signal_category, matched_phrases, context_text, section}

    # LLM extraction (Stage 3)
    problems: list[dict] = field(default_factory=list)
    # Each: {problem_statement, domain, subdomain, scope, sub_questions, ...}

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Checkpoint helpers ──────────────────────────────────────────────────────

def write_checkpoint(run_id: str, stage: str, sources: list[Source]) -> Path:
    """Write a list of Sources to a checkpoint JSONL file."""
    path = CHECKPOINTS_DIR / f"{run_id}_{stage}.jsonl"
    with open(path, "w") as f:
        for s in sources:
            f.write(s.to_json() + "\n")
    return path


def load_checkpoint(run_id: str, stage: str) -> list[Source] | None:
    """Load sources from a checkpoint file, or None if it doesn't exist."""
    path = CHECKPOINTS_DIR / f"{run_id}_{stage}.jsonl"
    if not path.exists():
        return None
    sources = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                sources.append(Source.from_dict(json.loads(line)))
    return sources


def checkpoint_exists(run_id: str, stage: str) -> bool:
    path = CHECKPOINTS_DIR / f"{run_id}_{stage}.jsonl"
    return path.exists()


def write_incremental_checkpoint(run_id: str, stage: str, sources: list[Source]) -> Path:
    """Append sources to an incremental checkpoint (for LLM stages)."""
    path = CHECKPOINTS_DIR / f"{run_id}_{stage}_incremental.jsonl"
    with open(path, "a") as f:
        for s in sources:
            f.write(s.to_json() + "\n")
    return path


def load_incremental_checkpoint(run_id: str, stage: str) -> set[str]:
    """Return set of source_ids already processed in incremental checkpoint."""
    path = CHECKPOINTS_DIR / f"{run_id}_{stage}_incremental.jsonl"
    if not path.exists():
        return set()
    ids = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                ids.add(d["source_id"])
    return ids


def generate_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ── Cost tracking ──────────────────────────────────────────────────────────

# Per-million-token pricing (as of early 2026)
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
}


class BudgetExceeded(Exception):
    """Raised when cumulative LLM spend exceeds the configured threshold."""


class CostTracker:
    """Track cumulative LLM spend across pipeline stages."""

    def __init__(self, limit: float = 10.0):
        self.limit = limit
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self._by_stage: dict[str, float] = {}
        self._logger = logging.getLogger("collector.cost")

    def record(self, model: str, input_tokens: int, output_tokens: int,
               stage: str = "") -> float:
        """Record token usage from one API call. Returns the call cost.

        Raises BudgetExceeded if cumulative spend exceeds the limit.
        """
        pricing = MODEL_PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        if stage:
            self._by_stage[stage] = self._by_stage.get(stage, 0.0) + cost

        if self.total_cost >= self.limit:
            self._logger.error(
                "BUDGET EXCEEDED: $%.4f spent (limit $%.2f). Aborting.",
                self.total_cost, self.limit,
            )
            raise BudgetExceeded(
                f"Cumulative spend ${self.total_cost:.4f} exceeds limit ${self.limit:.2f}"
            )

        return cost

    def summary(self) -> dict:
        return {
            "total_cost": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "by_stage": {k: round(v, 4) for k, v in self._by_stage.items()},
            "limit": self.limit,
        }

    def log_status(self) -> None:
        self._logger.info(
            "Cost so far: $%.4f / $%.2f (%.0f%% of budget)",
            self.total_cost, self.limit,
            100 * self.total_cost / self.limit if self.limit else 0,
        )
