from __future__ import annotations

import importlib.util
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .inference_gateway import InferenceProfile
from .state_core import StateCore

Tier = Literal["local", "economy", "balanced", "frontier"]


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    provider: Literal["ollama", "openai", "litellm"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^\S+$")
    tier: Tier = "balanced"
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
    max_output_tokens: int = Field(default=1200, ge=64, le=16000)
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,79}$")
    base_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def reserved_name(cls, value: str) -> str:
        if value == "auto":
            raise ValueError("auto is reserved for the routing policy")
        return value

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) endpoint without credentials or query parameters")
        return value.rstrip("/")

    def profile(self) -> InferenceProfile:
        if self.tier == "local" and self.provider != "ollama":
            raise ValueError("The local tier requires Ollama")
        if self.provider == "litellm" and not self.credential_env:
            raise ValueError("Specify the local environment variable containing the provider key")
        return InferenceProfile(**self.model_dump())


def profile_availability(profile: InferenceProfile) -> tuple[bool, str]:
    if not profile.enabled:
        return False, "Disabled"
    if profile.provider == "litellm" and importlib.util.find_spec("litellm") is None:
        return False, "Install the universal extra"
    key_name = profile.credential_env or (
        "OPENAI_API_KEY" if profile.provider == "openai" else None
    )
    if key_name and not os.getenv(key_name):
        return False, f"Missing {key_name} in the local environment"
    return True, "Configured; model access is verified when used"


class ProfileStore:
    def __init__(self, core: StateCore, workspace_id: UUID) -> None:
        self.core = core
        self.workspace_id = workspace_id

    def list(self, defaults: Sequence[InferenceProfile]) -> list[InferenceProfile]:
        profiles = {item.name: item for item in defaults}
        with self.core.pool.connection() as connection:
            rows = connection.execute(
                "SELECT configuration FROM engram_inference_profile WHERE workspace_id = %s",
                (self.workspace_id,),
            ).fetchall()
        for row in rows:
            item = ProfileRequest(**row["configuration"]).profile()
            profiles[item.name] = item
        return list(profiles.values())

    def save(self, payload: ProfileRequest) -> InferenceProfile:
        profile = payload.profile()
        with self.core.pool.connection() as connection:
            connection.execute(
                """INSERT INTO engram_inference_profile (workspace_id, name, configuration)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (workspace_id, name) DO UPDATE
                   SET configuration = EXCLUDED.configuration, updated_at = now()""",
                (self.workspace_id, profile.name, Jsonb(asdict(profile))),
            )
            connection.commit()
        return profile


@dataclass(frozen=True)
class RoutingDecision:
    profile: InferenceProfile
    reason: str
    policy: str = "deterministic-v1"


def choose_profile(
    profiles: Sequence[InferenceProfile],
    request: str,
    *,
    local_only: bool = False,
    reused_procedure: bool = False,
    available: Callable[[InferenceProfile], tuple[bool, str]] = profile_availability,
) -> RoutingDecision:
    ready = [item for item in profiles if available(item)[0]]
    if local_only:
        ready = [item for item in ready if item.provider == "ollama"]
        preferred, reason = "local", "Local-only boundary requested"
    elif re.search(
        r"\b(audit|audita|security|seguridad|arquitectura|architecture)\b", request, re.I
    ):
        preferred = "frontier"
        reason = "Architecture or security review requires the strongest tier"
    elif len(request) > 1200 or re.search(
        r"\b(debug|depura|implementa|implement|compare|compara|planifica)\b", request, re.I
    ):
        preferred, reason = "balanced", "Multi-step or long request"
    elif reused_procedure:
        preferred, reason = "economy", "A verified procedure is available for this task"
    else:
        preferred, reason = "economy", "Routine request; no additional model call for routing"
    ordered = [preferred, "balanced", "frontier", "economy", "local"]
    for tier in dict.fromkeys(ordered):
        matches = [item for item in ready if item.tier == tier]
        if matches:
            selected = next((item for item in matches if item.name == tier), matches[0])
            if tier != preferred:
                reason += f"; {preferred} unavailable, selected configured {tier} tier"
            return RoutingDecision(selected, reason)
    raise ValueError("No configured model is available within this request's privacy boundary")
