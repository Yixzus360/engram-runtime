from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class EvaluatorPricing:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float

    def cost(
        self,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
    ) -> float:
        cached = max(0, min(input_tokens, cached_input_tokens))
        uncached = max(0, input_tokens - cached)
        return (
            uncached * self.input_per_million
            + cached * self.cached_input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000


class EvaluatorBudget:
    """Persistent call reservations that keep an evaluator below a hard USD cap."""

    def __init__(
        self,
        path: Path,
        *,
        maximum_usd: float,
        pricing: EvaluatorPricing,
    ) -> None:
        if maximum_usd <= 0:
            raise ValueError("maximum_usd must be positive")
        self.path = path
        self.maximum_usd = maximum_usd
        self.pricing = pricing
        self._lock = threading.Lock()

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def spent_or_reserved_usd(self) -> float:
        latest: dict[str, dict[str, Any]] = {}
        for record in self._records():
            call_id = record.get("call_id")
            if isinstance(call_id, str):
                latest[call_id] = record
        return sum(
            float(
                record.get("actual_usd")
                if record.get("status") == "settled"
                else record.get("reserved_usd", 0.0)
            )
            for record in latest.values()
        )

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()

    def reserve(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_completion_tokens: int,
    ) -> tuple[str, float]:
        # UTF-8 bytes plus a fixed envelope is a conservative input-token upper bound.
        prompt_upper_bound = (
            len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            + 512
        )
        reserve_usd = self.pricing.cost(
            input_tokens=prompt_upper_bound,
            cached_input_tokens=0,
            output_tokens=max_completion_tokens,
        )
        call_id = uuid.uuid4().hex
        with self._lock:
            spent = self.spent_or_reserved_usd()
            if spent + reserve_usd > self.maximum_usd:
                raise RuntimeError(
                    "Evaluator budget would be exceeded: "
                    f"spent_or_reserved=${spent:.6f}, next_reserve=${reserve_usd:.6f}, "
                    f"cap=${self.maximum_usd:.2f}"
                )
            self._append(
                {
                    "call_id": call_id,
                    "status": "reserved",
                    "timestamp_utc": utc_now_iso(),
                    "requested_model": model,
                    "reserved_usd": reserve_usd,
                    "prompt_token_upper_bound": prompt_upper_bound,
                    "max_completion_tokens": max_completion_tokens,
                }
            )
        return call_id, reserve_usd

    def settle(
        self,
        call_id: str,
        *,
        model: str,
        resolved_model: str | None = None,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reserved_usd: float,
    ) -> float:
        actual_usd = self.pricing.cost(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
        with self._lock:
            self._append(
                {
                    "call_id": call_id,
                    "status": "settled",
                    "timestamp_utc": utc_now_iso(),
                    "requested_model": model,
                    "resolved_model": resolved_model or model,
                    "reserved_usd": reserved_usd,
                    "actual_usd": actual_usd,
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                }
            )
        return actual_usd

    def fail(
        self,
        call_id: str,
        *,
        model: str,
        reserved_usd: float,
        error_type: str,
    ) -> None:
        # Keep the reservation charged because a failed remote request may still be billable.
        with self._lock:
            self._append(
                {
                    "call_id": call_id,
                    "status": "failed",
                    "timestamp_utc": utc_now_iso(),
                    "requested_model": model,
                    "reserved_usd": reserved_usd,
                    "error_type": error_type,
                }
            )
