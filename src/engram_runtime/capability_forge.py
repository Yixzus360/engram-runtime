from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator

from .signal_index import SignalEncoder
from .state_core import StateCore


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ActionContext:
    workspace_id: UUID
    run_id: UUID | None = None
    root_path: Path | None = None


ActionHandler = Callable[[dict[str, Any], ActionContext], Any]


@dataclass(frozen=True)
class ActionUnit:
    name: str
    description: str
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    handler: ActionHandler
    risk_level: RiskLevel = RiskLevel.READ

    @property
    def handler_reference(self) -> str:
        return f"{self.handler.__module__}:{self.handler.__qualname__}"


@dataclass(frozen=True)
class ActionReceipt:
    action: str
    output: Any
    risk_level: RiskLevel


class CapabilityForge:
    """Registers typed actions and crystallizes evidence-backed procedures."""

    def __init__(
        self,
        core: StateCore,
        encoder: SignalEncoder,
        *,
        verification_threshold: int = 2,
    ) -> None:
        if verification_threshold < 1:
            raise ValueError("verification_threshold must be positive")
        self.core = core
        self.encoder = encoder
        self.verification_threshold = verification_threshold
        self._actions: dict[tuple[UUID, str], ActionUnit] = {}

    def register(self, workspace_id: UUID, action: ActionUnit) -> dict[str, Any]:
        self._validate_contract(action.input_contract)
        self._validate_contract(action.output_contract)
        embedding = self.encoder.encode([f"{action.name}\n{action.description}"])[0]
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_action_unit (
                    workspace_id, name, description, input_contract,
                    output_contract, handler, risk_level, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, name)
                DO UPDATE SET
                    description = EXCLUDED.description,
                    input_contract = EXCLUDED.input_contract,
                    output_contract = EXCLUDED.output_contract,
                    handler = EXCLUDED.handler,
                    risk_level = EXCLUDED.risk_level,
                    embedding = EXCLUDED.embedding,
                    enabled = true,
                    updated_at = now()
                RETURNING *
                """,
                (
                    workspace_id,
                    action.name,
                    action.description,
                    json.dumps(action.input_contract),
                    json.dumps(action.output_contract),
                    action.handler_reference,
                    action.risk_level.value,
                    embedding,
                ),
            )
            row = cursor.fetchone()
            connection.commit()
        self._actions[(workspace_id, action.name)] = action
        return row

    def invoke(
        self,
        workspace_id: UUID,
        action_name: str,
        arguments: dict[str, Any],
        *,
        context: ActionContext | None = None,
    ) -> ActionReceipt:
        action = self._actions.get((workspace_id, action_name))
        if action is None:
            raise LookupError(f"Action Unit '{action_name}' is not loaded in this process.")
        Draft202012Validator(action.input_contract).validate(arguments)
        output = action.handler(
            arguments,
            context or ActionContext(workspace_id=workspace_id),
        )
        Draft202012Validator(action.output_contract).validate(output)
        return ActionReceipt(action=action_name, output=output, risk_level=action.risk_level)

    def loaded_action(self, workspace_id: UUID, action_name: str) -> ActionUnit:
        action = self._actions.get((workspace_id, action_name))
        if action is None:
            raise LookupError(f"Action Unit '{action_name}' is not loaded in this process.")
        return action

    def select_actions(
        self,
        workspace_id: UUID,
        request: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_vector = self.encoder.encode([request])[0]
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, description, input_contract, output_contract,
                       handler, risk_level,
                       1 - (embedding <=> %s::vector) AS relevance
                  FROM engram_action_unit
                 WHERE workspace_id = %s AND enabled = true AND embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector, name
                 LIMIT %s
                """,
                (query_vector, workspace_id, query_vector, limit),
            )
            return list(cursor.fetchall())

    def distill_candidate(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        name: str,
        description: str,
        trigger_text: str,
    ) -> dict[str, Any]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run.status, thread.workspace_id
                  FROM engram_run AS run
                  JOIN engram_thread AS thread ON thread.id = run.thread_id
                 WHERE run.id = %s
                """,
                (run_id,),
            )
            run = cursor.fetchone()
            if not run or run["workspace_id"] != workspace_id:
                raise ValueError("the source run does not belong to this workspace")
            if run["status"] != "complete":
                raise ValueError("only successful completed runs can produce a procedure candidate")
            cursor.execute(
                """
                SELECT payload
                  FROM engram_run_record
                 WHERE run_id = %s AND record_kind = 'action_dispatch'
                 ORDER BY id
                """,
                (run_id,),
            )
            steps = [record["payload"] for record in cursor.fetchall()]
            if not steps:
                raise ValueError("the source run has no successful action sequence")

            body = {"steps": steps}
            evidence = {"successful_run_ids": [str(run_id)], "failed_run_ids": []}
            fingerprint = self._procedure_fingerprint(trigger_text, body)
            embedding = self.encoder.encode([f"{trigger_text}\n{description}"])[0]
            cursor.execute(
                """
                INSERT INTO engram_procedure_pack (
                    workspace_id, name, description, trigger_text, procedure_body,
                    verification_evidence, fingerprint, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, fingerprint)
                DO UPDATE SET
                    description = EXCLUDED.description,
                    trigger_text = EXCLUDED.trigger_text,
                    procedure_body = EXCLUDED.procedure_body,
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
                RETURNING *
                """,
                (
                    workspace_id,
                    name,
                    description,
                    trigger_text,
                    json.dumps(body),
                    json.dumps(evidence),
                    fingerprint,
                    embedding,
                ),
            )
            procedure = cursor.fetchone()
            connection.commit()
            return procedure

    def add_verification(
        self,
        procedure_id: UUID,
        run_id: UUID,
        *,
        successful: bool,
    ) -> dict[str, Any]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT procedure.*, run.status AS run_status
                  FROM engram_procedure_pack AS procedure
                  JOIN engram_thread AS thread ON thread.workspace_id = procedure.workspace_id
                  JOIN engram_run AS run ON run.thread_id = thread.id AND run.id = %s
                 WHERE procedure.id = %s
                """,
                (run_id, procedure_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("procedure and run must belong to the same workspace")
            if successful and row["run_status"] != "complete":
                raise ValueError("a successful verification requires a completed run")

            evidence = dict(row["verification_evidence"])
            key = "successful_run_ids" if successful else "failed_run_ids"
            run_ids = list(evidence.get(key, []))
            if str(run_id) not in run_ids:
                run_ids.append(str(run_id))
            evidence[key] = run_ids
            success_count = len(set(evidence.get("successful_run_ids", [])))
            status = "verified" if success_count >= self.verification_threshold else "candidate"
            cursor.execute(
                """
                UPDATE engram_procedure_pack
                   SET verification_evidence = %s, status = %s, updated_at = now()
                 WHERE id = %s
                RETURNING *
                """,
                (json.dumps(evidence), status, procedure_id),
            )
            updated = cursor.fetchone()
            connection.commit()
            return updated

    def find_verified_procedures(
        self,
        workspace_id: UUID,
        request: str,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        query_vector = self.encoder.encode([request])[0]
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, version, description, trigger_text,
                       procedure_body, verification_evidence,
                       1 - (embedding <=> %s::vector) AS relevance
                  FROM engram_procedure_pack
                 WHERE workspace_id = %s
                   AND status = 'verified'
                   AND embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector, updated_at DESC
                 LIMIT %s
                """,
                (query_vector, workspace_id, query_vector, limit),
            )
            return list(cursor.fetchall())

    @staticmethod
    def _validate_contract(contract: dict[str, Any]) -> None:
        Draft202012Validator.check_schema(contract)

    @staticmethod
    def _procedure_fingerprint(trigger_text: str, body: dict[str, Any]) -> str:
        encoded_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
        source = trigger_text.casefold().strip() + encoded_body
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


def action_contract(
    *,
    name: str,
    description: str,
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.READ,
) -> Callable[[ActionHandler], ActionUnit]:
    """Turn a plain callable into a typed Action Unit."""

    def wrap(handler: ActionHandler) -> ActionUnit:
        return ActionUnit(
            name=name,
            description=description,
            input_contract=input_contract,
            output_contract=output_contract,
            handler=handler,
            risk_level=risk_level,
        )

    return wrap


def action_schemas(actions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored Action Units to provider-neutral inference schemas."""
    return [
        {
            "name": action["name"],
            "description": action["description"],
            "parameters": action["input_contract"],
        }
        for action in actions
    ]
