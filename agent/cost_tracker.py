"""
AI Engineering — Cost Tracker

Registra cada llamada LLM con modelo, tokens y costo estimado.
Datos persistidos en /opt/ai_engineering/data/costs.json.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_COSTS_FILE = Path("/opt/ai_engineering/data/costs.json")

# Precios aproximados por 1M tokens (input/output) en USD
# Actualizados a 2026-03
_PRICING: dict[str, dict] = {
    "claude-sonnet-4-6":  {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":   {"input": 0.80,  "output": 4.00},
    "gpt-4o":             {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":        {"input": 0.15,  "output": 0.60},
    "gemini-2.5-pro":     {"input": 1.25,  "output": 10.00},
    "gemini-2.0-flash":   {"input": 0.075, "output": 0.30},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calcula el costo estimado en USD."""
    pricing = _PRICING.get(model, {"input": 1.0, "output": 3.0})
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 6)


def record_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    project: str,
    task: str,
) -> float:
    """Registra una llamada LLM y retorna el costo estimado."""
    cost = estimate_cost(model, input_tokens, output_tokens)

    entry = {
        "ts": int(time.time()),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "project": project,
        "task": task,
    }

    try:
        _COSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = []
        if _COSTS_FILE.exists():
            try:
                data = json.loads(_COSTS_FILE.read_text())
            except Exception:
                data = []
        data.append(entry)
        _COSTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning(f"CostTracker: error guardando entrada: {e}")

    return cost


def get_summary() -> dict:
    """Retorna resumen de costos por modelo y por proyecto."""
    if not _COSTS_FILE.exists():
        return {"by_model": {}, "by_project": {}, "total_usd": 0.0}

    try:
        data = json.loads(_COSTS_FILE.read_text())
    except Exception:
        return {"by_model": {}, "by_project": {}, "total_usd": 0.0}

    by_model: dict[str, float] = {}
    by_project: dict[str, float] = {}
    total = 0.0

    for entry in data:
        model   = entry.get("model", "unknown")
        project = entry.get("project", "unknown")
        cost    = entry.get("cost_usd", 0.0)

        by_model[model]     = round(by_model.get(model, 0.0) + cost, 6)
        by_project[project] = round(by_project.get(project, 0.0) + cost, 6)
        total = round(total + cost, 6)

    return {"by_model": by_model, "by_project": by_project, "total_usd": total}
