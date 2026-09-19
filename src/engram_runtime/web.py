from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .action_cycle import ActionCycle, CycleLimits
from .attention_composer import AttentionComposer
from .builtin_actions import register_builtin_actions
from .capability_forge import CapabilityForge, RiskLevel
from .config import RuntimeSettings, get_settings
from .experience_ledger import ExperienceLedger
from .inference_gateway import (
    InferenceProfile,
    InferenceProvider,
    OllamaProvider,
    OpenAIResponsesProvider,
    standard_router,
)
from .pattern_learner import PatternLearner
from .signal_index import FastEmbedResultRefiner, OllamaSignalEncoder, SignalIndex
from .state_core import StateCore

STATIC_DIR = Path(__file__).with_name("static")


class ThreadRequest(BaseModel):
    title: str = Field(default="New runtime task", min_length=1, max_length=120)


class RunRequest(BaseModel):
    thread_id: UUID
    request: str = Field(min_length=1, max_length=20_000)
    profile: str = "local"
    allow_side_effects: bool = False


class RuntimeService:
    def __init__(
        self,
        settings: RuntimeSettings,
        core: StateCore,
        *,
        provider_factory: Callable[[InferenceProfile], InferenceProvider] | None = None,
    ) -> None:
        self.settings = settings
        self.core = core
        self.encoder = OllamaSignalEncoder(settings.ollama_url, settings.embedding_model)
        self.signal_index = SignalIndex(
            core,
            self.encoder,
            refiner=FastEmbedResultRefiner(settings.reranker_model),
        )
        self.ledger = ExperienceLedger(self.signal_index)
        self.forge = CapabilityForge(core, self.encoder)
        self.learner = PatternLearner(self.forge)
        self.composer = AttentionComposer(core, self.ledger, self.forge)
        self.router = standard_router(
            local_model=settings.model,
            economy_model=settings.openai_economy_model,
            balanced_model=settings.openai_balanced_model,
            frontier_model=settings.openai_frontier_model,
        )
        self._provider_factory = provider_factory
        self.workspace = core.ensure_workspace(settings.workspace_slug, "Local workspace")
        self.worker = core.ensure_worker(
            self.workspace["id"],
            "primary",
            "Primary worker",
            {"role": "local operator"},
        )
        register_builtin_actions(self.forge, self.workspace["id"])

    def create_thread(self, title: str) -> dict[str, Any]:
        return self.core.create_thread(self.workspace["id"], self.worker["id"], title)

    def dashboard(self) -> dict[str, Any]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread.*,
                       latest.status AS last_run_status,
                       latest.started_at AS last_run_at
                  FROM engram_thread AS thread
                  LEFT JOIN LATERAL (
                    SELECT status, started_at
                      FROM engram_run
                     WHERE thread_id = thread.id
                     ORDER BY started_at DESC
                     LIMIT 1
                  ) AS latest ON true
                 WHERE thread.workspace_id = %s
                 ORDER BY thread.updated_at DESC
                 LIMIT 50
                """,
                (self.workspace["id"],),
            )
            threads = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT
                  (SELECT count(*) FROM engram_run AS run
                    JOIN engram_thread AS thread ON thread.id = run.thread_id
                   WHERE thread.workspace_id = %s) AS runs,
                  (SELECT count(*) FROM engram_experience
                   WHERE workspace_id = %s AND superseded_by IS NULL
                     AND (expires_at IS NULL OR expires_at > now())) AS experiences,
                  (SELECT count(*) FROM engram_procedure_pack
                   WHERE workspace_id = %s AND status = 'verified') AS verified_procedures,
                  (SELECT count(*) FROM engram_stored_output
                   WHERE workspace_id = %s) AS stored_outputs
                """,
                (self.workspace["id"],) * 4,
            )
            stats = cursor.fetchone()
        return {
            "workspace": self.workspace,
            "worker": self.worker,
            "threads": threads,
            "stats": stats,
            "profiles": [profile.__dict__ for profile in self.router.list_profiles()],
            "health": self.health(),
        }

    def health(self) -> dict[str, Any]:
        ollama_ready = False
        try:
            response = httpx.get(f"{self.settings.ollama_url}/api/tags", timeout=2)
            ollama_ready = response.is_success
        except httpx.HTTPError:
            pass
        return {
            "state_core": self.core.ping(),
            "ollama": ollama_ready,
            "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        }

    def thread_detail(self, thread_id: UUID) -> dict[str, Any]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM engram_thread WHERE id = %s AND workspace_id = %s",
                (thread_id, self.workspace["id"]),
            )
            thread = cursor.fetchone()
            if not thread:
                raise LookupError("thread does not exist")
            cursor.execute(
                "SELECT * FROM engram_entry WHERE thread_id = %s ORDER BY sequence_no",
                (thread_id,),
            )
            entries = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT * FROM engram_run
                 WHERE thread_id = %s
                 ORDER BY started_at DESC
                 LIMIT 20
                """,
                (thread_id,),
            )
            runs = list(cursor.fetchall())
            records: list[dict[str, Any]] = []
            if runs:
                records = self.core.list_records(runs[0]["id"])
        return {"thread": thread, "entries": entries, "runs": runs, "records": records}

    def run(self, payload: RunRequest) -> dict[str, Any]:
        self.thread_detail(payload.thread_id)
        profile = self.router.resolve(payload.profile)
        packet = self.composer.compose(
            self.workspace["id"],
            payload.thread_id,
            payload.request,
            base_instructions=(
                "You are an Engram Runtime worker. Use the selected Action Units when they "
                "improve accuracy. Treat candidate Procedure Cues as hypotheses and validate "
                "their outcomes. Give a concise final answer after the work is complete."
            ),
            worker_id=self.worker["id"],
            action_limit=self.settings.action_limit,
        )
        provider = self._build_provider(profile)

        def gate(risk: RiskLevel, _name: str, _arguments: dict[str, Any]) -> bool:
            return payload.allow_side_effects and risk in {RiskLevel.WRITE, RiskLevel.EXTERNAL}

        cycle = ActionCycle(
            self.core,
            self.forge,
            limits=CycleLimits(
                max_dispatches=self.settings.action_limit,
                max_duration_seconds=self.settings.duration_limit_seconds,
            ),
            operator_gate=gate,
            learner=self.learner,
            output_inline_bytes=self.settings.output_inline_bytes,
        )
        result = cycle.run(
            self.workspace["id"],
            payload.thread_id,
            payload.request,
            provider=provider,
            instructions=packet.instructions,
            root_path=Path.cwd(),
            tools=packet.tools,
        )
        focus_metrics = {
            "estimated_tokens": packet.estimated_tokens,
            "baseline_tokens": packet.baseline_tokens,
            "estimated_tokens_avoided": packet.estimated_tokens_avoided,
            "reused_procedure": packet.reused_procedure,
            "procedures": [str(item) for item in packet.procedure_ids],
            "experiences": [str(item) for item in packet.experience_ids],
            "actions": list(packet.selected_action_names),
        }
        self.core.emit_record(result.run_id, "focus_packet", focus_metrics)
        return {
            "result": result.__dict__,
            "focus_packet": focus_metrics,
            "thread": self.thread_detail(payload.thread_id),
        }

    def procedures(self) -> list[dict[str, Any]]:
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, version, status, description, trigger_text,
                       verification_evidence, created_at, updated_at
                  FROM engram_procedure_pack
                 WHERE workspace_id = %s
                 ORDER BY updated_at DESC
                 LIMIT 100
                """,
                (self.workspace["id"],),
            )
            return list(cursor.fetchall())

    def experiences(self) -> list[dict[str, Any]]:
        return self.ledger.list_current(self.workspace["id"], limit=100)

    def _build_provider(self, profile: InferenceProfile) -> InferenceProvider:
        if self._provider_factory:
            return self._provider_factory(profile)
        if profile.provider == "ollama":
            return OllamaProvider(
                profile.model,
                base_url=self.settings.ollama_url,
                timeout_seconds=self.settings.duration_limit_seconds,
            )
        return OpenAIResponsesProvider(
            profile.model,
            reasoning_effort=profile.reasoning_effort,
            max_output_tokens=profile.max_output_tokens,
            timeout_seconds=self.settings.duration_limit_seconds,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    core = StateCore(settings.database_url)
    core.open()
    core.migrate()
    app.state.runtime = RuntimeService(settings, core)
    try:
        yield
    finally:
        core.close()


app = FastAPI(title="Engram Runtime", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def runtime() -> RuntimeService:
    return app.state.runtime


@app.get("/", response_class=HTMLResponse)
def console() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return runtime().dashboard()


@app.post("/api/threads")
def create_thread(payload: ThreadRequest) -> dict[str, Any]:
    return runtime().create_thread(payload.title)


@app.get("/api/threads/{thread_id}")
def thread_detail(thread_id: UUID) -> dict[str, Any]:
    try:
        return runtime().thread_detail(thread_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/run")
def execute(payload: RunRequest) -> dict[str, Any]:
    try:
        return runtime().run(payload)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/procedures")
def procedures() -> list[dict[str, Any]]:
    return runtime().procedures()


@app.get("/api/experiences")
def experiences() -> list[dict[str, Any]]:
    return runtime().experiences()


@app.get("/api/outputs/{output_id}")
def stored_output(
    output_id: UUID,
    download: bool = Query(default=False),
) -> Response:
    content = runtime().core.fetch_output(runtime().workspace["id"], output_id)
    if content is None:
        raise HTTPException(status_code=404, detail="stored output does not exist")
    disposition = "attachment" if download else "inline"
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": f'{disposition}; filename="{output_id}.json"'},
    )
