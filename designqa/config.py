"""Configuration loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Model choice is a product decision: Sonnet is the default because the task is
# high-volume (every PR / every screen) and cost per screen matters. Opus is the
# "high accuracy" option. Compare both with evals/run_evals.py before deciding.
MODEL = os.getenv("DESIGNQA_MODEL", "claude-sonnet-5-5")

# USD per million tokens (input, output). Update if pricing changes.
PRICES = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5-1": (10.0, 50.0),
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if len(ANTHROPIC_API_KEY) < 30 or ANTHROPIC_API_KEY.endswith("..."):
    ANTHROPIC_API_KEY = ""  # the placeholder from .env.example is not a key: run in free mode
FIGMA_TOKEN = os.getenv("FIGMA_TOKEN", "")

CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN", "")
CLICKUP_LIST_ID = os.getenv("CLICKUP_LIST_ID", "")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID", "")

# Guardrail thresholds
MIN_CONFIDENCE = float(os.getenv("DESIGNQA_MIN_CONFIDENCE", "0.5"))
AUTO_APPROVE_CONFIDENCE = float(os.getenv("DESIGNQA_AUTO_APPROVE", "0.85"))


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout
