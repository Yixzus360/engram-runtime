import os
import uuid

import pytest

from engram_runtime.inference_gateway import standard_router
from engram_runtime.profiles import ProfileRequest, ProfileStore, choose_profile
from engram_runtime.state_core import StateCore

DATABASE_URL = os.getenv(
    "ENGRAM_TEST_DATABASE_URL",
    "postgresql://engram:engram@localhost:5439/engram",
)


@pytest.fixture(scope="module")
def core() -> StateCore:
    instance = StateCore(DATABASE_URL)
    try:
        instance.open()
        instance.migrate()
    except Exception as error:
        pytest.skip(f"State Core is unavailable: {error}")
    yield instance
    instance.close()


def test_auto_route_and_private_boundary():
    profiles = standard_router(local_model="local-test").list_profiles()
    ready = lambda profile: (True, "configured")  # noqa: E731
    assert choose_profile(profiles, "Calculate 8 + 5", available=ready).profile.name == "economy"
    assert choose_profile(profiles, "Audit security", available=ready).profile.name == "frontier"
    assert choose_profile(
        profiles, "Audit security", local_only=True, available=ready
    ).profile.provider == "ollama"
    with pytest.raises(ValueError, match="privacy boundary"):
        choose_profile(profiles[1:], "Private task", local_only=True, available=ready)


def test_profile_rejects_inline_credentials_and_reserved_names():
    for changes in [
        {"base_url": "https://user:password@example.com"},
        {"api_key": "not-allowed"},
        {"name": "auto"},
    ]:
        with pytest.raises(ValueError):
            ProfileRequest(**{"name": "test", "provider": "openai", "model": "test", **changes})
    with pytest.raises(ValueError, match="local tier"):
        ProfileRequest(name="test", provider="openai", model="test", tier="local").profile()


def test_profile_store_persists_workspace_override(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"profiles-{uuid.uuid4().hex[:8]}", "Profile test")
    store = ProfileStore(core, workspace["id"])
    saved = store.save(
        ProfileRequest(
            name="reviewer",
            provider="openai",
            model="gpt-review",
            tier="frontier",
            reasoning_effort="high",
            credential_env="OPENAI_API_KEY",
        )
    )

    loaded = {profile.name: profile for profile in store.list([])}["reviewer"]

    assert loaded == saved
    assert loaded.credential_env == "OPENAI_API_KEY"
