"""Per-call and cumulative USD cost tracking for OpenRouter-backed merge runs.

Pricing is read from OpenRouter's public `/models` catalog (price per input/
output token for the selected model) and multiplied by the token usage each
merge call reports. A no-op (always $0) when no --model was passed, since the
default Ollama/vLLM backends are self-hosted and have no per-token cost.
"""

import httpx

from .logger import get_logger

log = get_logger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class CostTracker:
    def __init__(self, model: str | None) -> None:
        self.model = model
        self.total_cost = 0.0
        self.call_count = 0
        self.per_call_costs: list[dict] = []
        self._prompt_price = 0.0
        self._completion_price = 0.0
        if model is not None:
            self._prompt_price, self._completion_price = self._fetch_pricing(model)

    @staticmethod
    def _fetch_pricing(model: str) -> tuple[float, float]:
        """Return (usd_per_input_token, usd_per_output_token) for `model`."""
        try:
            resp = httpx.get(_OPENROUTER_MODELS_URL, timeout=10.0)
            resp.raise_for_status()
            for entry in resp.json().get("data", []):
                if entry.get("id") == model:
                    pricing = entry.get("pricing", {})
                    return float(pricing.get("prompt", 0.0)), float(pricing.get("completion", 0.0))
            log.warning(
                "cost tracking: model '%s' not found in OpenRouter pricing catalog "
                "— costs will report as $0",
                model,
            )
        except Exception as exc:
            log.warning(
                "cost tracking: failed to fetch OpenRouter pricing (%s: %s) "
                "— costs will report as $0",
                exc.__class__.__name__, exc,
            )
        return 0.0, 0.0

    def record(self, idx: int, usage_details) -> float:
        """Record one LLM call's cost from its usage_details; returns that cost in USD."""
        if self.model is None or usage_details is None:
            return 0.0
        input_tokens = usage_details.get("input_token_count") or 0
        output_tokens = usage_details.get("output_token_count") or 0
        cost = input_tokens * self._prompt_price + output_tokens * self._completion_price
        self.total_cost += cost
        self.call_count += 1
        self.per_call_costs.append({
            "env": idx,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
        })
        log.info(
            "env %d cost | input_tokens=%d output_tokens=%d cost=$%.6f | running_total=$%.6f",
            idx, input_tokens, output_tokens, cost, self.total_cost,
        )
        return cost

    def summary(self) -> str:
        if self.model is None:
            return "Cost tracking: n/a (local Ollama/vLLM backend has no OpenRouter cost)"
        return (
            f"Total LLM cost (model={self.model}): ${self.total_cost:.6f} "
            f"across {self.call_count} call(s)"
        )

    def to_json_dict(self) -> dict:
        return {
            "model": self.model,
            "total_cost_usd": self.total_cost,
            "call_count": self.call_count,
            "per_call": self.per_call_costs,
        }
