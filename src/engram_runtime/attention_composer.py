from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from .capability_forge import CapabilityForge
from .experience_ledger import ExperienceLedger
from .inference_gateway import GatewayTool
from .state_core import StateCore


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class HeuristicTokenEstimator:
    """Provider-neutral estimate that intentionally errs slightly high."""

    def estimate(self, text: str) -> int:
        return max(1, math.ceil(len(text.encode("utf-8")) / 3.6))


@dataclass(frozen=True)
class FocusPacket:
    instructions: str
    tools: tuple[GatewayTool, ...]
    experience_ids: tuple[UUID, ...]
    procedure_ids: tuple[UUID, ...]
    selected_action_names: tuple[str, ...]
    estimated_tokens: int
    baseline_tokens: int
    estimated_tokens_avoided: int
    reused_procedure: bool


class AttentionComposer:
    """Build the smallest useful inference context from current runtime signals."""

    def __init__(
        self,
        core: StateCore,
        ledger: ExperienceLedger,
        forge: CapabilityForge,
        *,
        estimator: TokenEstimator | None = None,
        max_input_tokens: int = 4_000,
        procedure_relevance_floor: float = 0.78,
    ) -> None:
        self.core = core
        self.ledger = ledger
        self.forge = forge
        self.estimator = estimator or HeuristicTokenEstimator()
        self.max_input_tokens = max_input_tokens
        self.procedure_relevance_floor = procedure_relevance_floor

    def compose(
        self,
        workspace_id: UUID,
        thread_id: UUID,
        request: str,
        *,
        base_instructions: str,
        worker_id: UUID | None = None,
        action_limit: int = 8,
    ) -> FocusPacket:
        all_entries = self.core.list_recent_entries(thread_id, limit=12)
        all_signals = self.ledger.recall(
            workspace_id,
            request,
            worker_id=worker_id,
            thread_id=thread_id,
            limit=8,
            refine=False,
        )
        procedures = [
            item
            for item in self.forge.find_procedures(workspace_id, request, limit=3)
            if float(item["relevance"]) >= self.procedure_relevance_floor
        ]
        all_actions = self.forge.list_actions(workspace_id)
        ranked_actions = self.forge.select_actions(
            workspace_id,
            request,
            limit=action_limit,
        )
        selected_actions = ranked_actions
        if procedures:
            procedure_action_names: list[str] = []
            for procedure in procedures:
                for step in procedure["procedure_body"].get("steps", []):
                    name = step.get("action")
                    if name and name not in procedure_action_names:
                        procedure_action_names.append(name)
            actions_by_name = {action["name"]: action for action in all_actions}
            procedure_actions = [
                actions_by_name[name]
                for name in procedure_action_names
                if name in actions_by_name
            ]
            if procedure_actions:
                selected_actions = procedure_actions[:action_limit]
        tools = tuple(
            GatewayTool(
                name=action["name"],
                description=action["description"],
                parameters=action["input_contract"],
            )
            for action in selected_actions
        )

        if procedures:
            entries = all_entries[-2:]
            signals = all_signals[:2]
        else:
            entries = all_entries[-8:]
            signals = all_signals[:6]

        context = self._render_context(entries, signals, procedures)
        instructions = self._join_instructions(base_instructions, context)
        tool_text = json.dumps([self._tool_payload(tool) for tool in tools], sort_keys=True)
        estimated = self.estimator.estimate(instructions + request + tool_text)

        while estimated > self.max_input_tokens and (signals or len(entries) > 1):
            if signals:
                signals.pop()
            elif len(entries) > 1:
                entries.pop(0)
            context = self._render_context(entries, signals, procedures)
            instructions = self._join_instructions(base_instructions, context)
            estimated = self.estimator.estimate(instructions + request + tool_text)

        baseline_context = self._render_context(all_entries, all_signals, [])
        baseline_tools = json.dumps(
            [
                {
                    "name": action["name"],
                    "description": action["description"],
                    "parameters": action["input_contract"],
                }
                for action in all_actions
            ],
            sort_keys=True,
        )
        baseline = self.estimator.estimate(
            self._join_instructions(base_instructions, baseline_context)
            + request
            + baseline_tools
        )
        return FocusPacket(
            instructions=instructions,
            tools=tools,
            experience_ids=tuple(item.id for item in signals),
            procedure_ids=tuple(item["id"] for item in procedures),
            selected_action_names=tuple(tool.name for tool in tools),
            estimated_tokens=estimated,
            baseline_tokens=baseline,
            estimated_tokens_avoided=max(0, baseline - estimated),
            reused_procedure=bool(procedures),
        )

    @staticmethod
    def _join_instructions(base: str, context: str) -> str:
        return f"{base.strip()}\n\nFOCUS PACKET\n{context}".strip()

    @staticmethod
    def _render_context(
        entries: list[dict[str, Any]],
        signals: list[Any],
        procedures: list[dict[str, Any]],
    ) -> str:
        sections: list[str] = []
        if entries:
            transcript = "\n".join(
                f"- {entry['speaker']}: {entry['body']}" for entry in entries
            )
            sections.append(f"RECENT EXCHANGE\n{transcript}")
        if signals:
            experience = "\n".join(
                f"- [{item.experience_form}] {item.content}" for item in signals
            )
            sections.append(f"DOMAIN LENS\n{experience}")
        if procedures:
            recipes = "\n".join(
                AttentionComposer._render_procedure(item) for item in procedures
            )
            sections.append(f"PROCEDURE CUES\n{recipes}")
        return "\n\n".join(sections) if sections else "No prior runtime signals were selected."

    @staticmethod
    def _render_procedure(item: dict[str, Any]) -> str:
        status_note = "verified" if item["status"] == "verified" else "candidate; validate outcome"
        steps = json.dumps(item["procedure_body"]["steps"], ensure_ascii=False)
        return f"- {item['name']} ({status_note}): {item['description']} Steps: {steps}"

    @staticmethod
    def _tool_payload(tool: GatewayTool) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
