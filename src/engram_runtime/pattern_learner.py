from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from .capability_forge import CapabilityForge


@dataclass(frozen=True)
class LearningReceipt:
    procedure_id: UUID
    status: str
    created: bool
    relevance: float | None


class PatternLearner:
    """Turn successful action sequences into reusable, evidence-backed procedures."""

    def __init__(self, forge: CapabilityForge, *, similarity_floor: float = 0.82) -> None:
        self.forge = forge
        self.similarity_floor = similarity_floor

    def observe_success(
        self,
        workspace_id: UUID,
        run_id: UUID,
        request: str,
    ) -> LearningReceipt:
        candidates = self.forge.find_procedures(
            workspace_id,
            request,
            statuses=("candidate",),
            limit=1,
        )
        if candidates and float(candidates[0]["relevance"]) >= self.similarity_floor:
            candidate = candidates[0]
            updated = self.forge.add_verification(
                candidate["id"],
                run_id,
                successful=True,
            )
            return LearningReceipt(
                procedure_id=updated["id"],
                status=updated["status"],
                created=False,
                relevance=float(candidate["relevance"]),
            )

        digest = hashlib.sha256(request.casefold().strip().encode()).hexdigest()[:8]
        slug = re.sub(r"[^a-z0-9]+", "-", request.casefold()).strip("-")[:36]
        procedure = self.forge.distill_candidate(
            workspace_id,
            run_id,
            name=f"learned-{slug or 'procedure'}-{digest}",
            description="Action sequence distilled from a successful Engram run.",
            trigger_text=request,
        )
        return LearningReceipt(
            procedure_id=procedure["id"],
            status=procedure["status"],
            created=True,
            relevance=None,
        )
