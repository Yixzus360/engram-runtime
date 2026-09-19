from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .config import RuntimeSettings, get_settings
from .experience_ledger import ExperienceForm, ExperienceLedger
from .signal_index import OllamaSignalEncoder, SignalEncoder, SignalIndex
from .state_core import StateCore

SignalKind = Literal["fact", "decision", "constraint", "outcome", "failure", "correction"]

_MAX_QUERY_CHARS = 2_000
_MAX_CONTENT_CHARS = 4_000
_MAX_EVIDENCE_CHARS = 1_200
_MAX_SIGNAL_CHARS = 560
_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:api[_-]?key|password|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)


def _bounded(value: str, maximum: int, field: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} cannot exceed {maximum} characters")
    return normalized


def _reject_secrets(*values: str) -> None:
    combined = "\n".join(values)
    if any(pattern.search(combined) for pattern in _SENSITIVE_PATTERNS):
        raise ValueError("Engram rejected content that resembles a credential or private key")


def _clip(value: str, maximum: int = _MAX_SIGNAL_CHARS) -> str:
    return value if len(value) <= maximum else f"{value[: maximum - 1]}…"


class EngramMemoryService:
    """A narrow MCP boundary over Engram's existing local experience ledger."""

    def __init__(
        self,
        core: StateCore,
        encoder: SignalEncoder,
        *,
        workspace_slug: str,
        owns_core: bool = False,
    ) -> None:
        self.core = core
        self.encoder = encoder
        self.workspace_slug = workspace_slug
        self.owns_core = owns_core
        self.index = SignalIndex(core, encoder)
        self.ledger = ExperienceLedger(self.index)
        self.workspace = core.ensure_workspace(workspace_slug, "Codex MCP evaluation")
        self.worker = core.ensure_worker(
            self.workspace["id"],
            "codex-mcp",
            "Codex through Engram MCP",
            {"protocol": "mcp", "transport": "stdio"},
        )

    @classmethod
    def open(cls, settings: RuntimeSettings) -> EngramMemoryService:
        core = StateCore(settings.database_url)
        core.open()
        try:
            core.migrate()
            encoder = OllamaSignalEncoder(settings.ollama_url, settings.embedding_model)
            return cls(
                core,
                encoder,
                workspace_slug=settings.workspace_slug,
                owns_core=True,
            )
        except Exception:
            core.close()
            raise

    def close(self) -> None:
        if self.owns_core:
            self.core.close()

    def status(self) -> dict[str, Any]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM engram_experience
                      WHERE workspace_id = %s AND superseded_by IS NULL
                        AND (expires_at IS NULL OR expires_at > now())) AS signals,
                    (SELECT count(*) FROM engram_procedure_pack
                      WHERE workspace_id = %s AND status = 'candidate') AS candidates,
                    (SELECT count(*) FROM engram_procedure_pack
                      WHERE workspace_id = %s AND status = 'verified') AS verified
                """,
                (self.workspace["id"], self.workspace["id"], self.workspace["id"]),
            )
            counts = cursor.fetchone()
        return {
            "ready": self.core.ping(),
            "workspace": self.workspace_slug,
            "transport": "stdio",
            "storage": "postgresql+pgvector",
            "active_signals": int(counts["signals"]),
            "candidate_procedures": int(counts["candidates"]),
            "verified_procedures": int(counts["verified"]),
        }

    def recall(self, task: str, *, limit: int = 3) -> dict[str, Any]:
        query = _bounded(task, _MAX_QUERY_CHARS, "task")
        effective_limit = min(max(limit, 1), 3)
        hits = self.ledger.recall(
            self.workspace["id"],
            query,
            worker_id=self.worker["id"],
            limit=effective_limit,
            refine=False,
        )
        signals = [
            {
                "form": hit.experience_form,
                "kind": hit.attributes.get("kind", "signal"),
                "content": _clip(hit.content),
                "confidence": round(hit.confidence, 3),
            }
            for hit in hits
        ]
        context_characters = sum(len(item["content"]) for item in signals)
        return {
            "workspace": self.workspace_slug,
            "task": query,
            "limit_used": effective_limit,
            "signals": signals,
            "signal_count": len(signals),
            "estimated_context_tokens": math.ceil(context_characters / 4),
            "usage_note": (
                "Use only relevant signals and verify them against current project state."
            ),
        }

    def preserve(
        self,
        *,
        kind: SignalKind,
        content: str,
        task: str,
        evidence: str,
        success: bool,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        normalized_content = _bounded(content, _MAX_CONTENT_CHARS, "content")
        normalized_task = _bounded(task, _MAX_QUERY_CHARS, "task")
        normalized_evidence = _bounded(evidence, _MAX_EVIDENCE_CHARS, "evidence")
        _reject_secrets(normalized_content, normalized_task, normalized_evidence)
        if kind in {"outcome", "correction"} and not success:
            raise ValueError(f"{kind} requires success=true; use failure for unsuccessful work")
        if kind == "failure" and success:
            raise ValueError("failure requires success=false")
        form = (
            ExperienceForm.KNOWLEDGE_MAP
            if kind in {"fact", "decision", "constraint"}
            else ExperienceForm.RUN_JOURNAL
        )
        item = self.ledger.preserve(
            self.workspace["id"],
            form=form,
            content=normalized_content,
            source="codex-mcp",
            worker_id=self.worker["id"],
            confidence=confidence,
            attributes={
                "kind": kind,
                "task": normalized_task,
                "evidence": normalized_evidence,
                "success": success,
                "origin": "mcp",
            },
        )
        return {
            "stored": True,
            "id": str(item["id"]),
            "workspace": self.workspace_slug,
            "form": form.value,
            "kind": kind,
            "fingerprint": item["fingerprint"],
        }

    @staticmethod
    def render_recall(packet: Mapping[str, Any]) -> str:
        lines = [
            f"workspace={packet['workspace']} signals={packet['signal_count']} "
            f"estimated_tokens={packet['estimated_context_tokens']}"
        ]
        for position, signal in enumerate(packet["signals"], start=1):
            lines.append(
                f"[{position}] {signal['kind']}/{signal['form']} "
                f"confidence={signal['confidence']}: {signal['content']}"
            )
        lines.append("Verify relevant claims against current project state.")
        return "\n".join(lines)


def build_server(service: EngramMemoryService) -> MCPServer:
    server = MCPServer(
        "Engram Runtime",
        description="Compact local execution memory for coding agents.",
        instructions=(
            "Before work that may depend on earlier results, call recall_signals with the precise "
            "task. Treat recalled content as evidence to verify against current files. After a "
            "validated result, correction, or failure, call preserve_signal with concise evidence. "
            "Never store secrets, guesses, raw transcripts, or unverified procedures."
        ),
        version="0.1.0",
    )

    @server.tool(
        name="runtime_status",
        description="Check the isolated Engram workspace and local memory counts.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def runtime_status() -> dict[str, Any]:
        return service.status()

    @server.tool(
        name="recall_signals",
        description=(
            "Retrieve a small ranked packet of prior facts, decisions, constraints, outcomes, "
            "failures, and corrections relevant to the current task."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=False,
    )
    def recall_signals(task: str, limit: int = 3) -> str:
        return service.render_recall(service.recall(task, limit=limit))

    @server.tool(
        name="preserve_signal",
        description=(
            "Store one concise, evidence-backed result in the isolated local workspace. "
            "Use failure with success=false for failed approaches."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def preserve_signal(
        kind: SignalKind,
        content: str,
        task: str,
        evidence: str,
        success: bool,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        return service.preserve(
            kind=kind,
            content=content,
            task=task,
            evidence=evidence,
            success=success,
            confidence=confidence,
        )

    return server


def main() -> None:
    settings = get_settings()
    service = EngramMemoryService.open(settings)
    try:
        build_server(service).run(transport="stdio")
    finally:
        service.close()


if __name__ == "__main__":
    main()
