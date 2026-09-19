from __future__ import annotations

import argparse

from .config import get_settings
from .state_core import StateCore


def main() -> None:
    parser = argparse.ArgumentParser(prog="engram")
    parser.add_argument("command", choices=("migrate", "health", "serve"))
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("engram_runtime.web:app", host="127.0.0.1", port=8765)
        return

    core = StateCore(settings.database_url)
    core.open()
    try:
        if args.command == "migrate":
            applied = core.migrate()
            detail = "Applied: " + ", ".join(applied) if applied else "No changes."
            print("State Core ready.", detail)
        else:
            print("State Core healthy." if core.ping() else "State Core unavailable.")
    finally:
        core.close()


if __name__ == "__main__":
    main()
