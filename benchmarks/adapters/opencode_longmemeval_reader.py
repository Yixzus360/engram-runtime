from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXECUTABLE = Path(
    os.environ.get("OPENCODE_EXECUTABLE", Path.home() / ".bun" / "bin" / "opencode.bat")
)
FINAL_INSTRUCTION = (
    "Apply the supplied benchmark instructions now. Treat attached images as the "
    "numbered image markers in those instructions. Return exactly the requested "
    "answer format."
)


def _write_data_image(path_stem: Path, data_url: str) -> Path:
    if not data_url.startswith("data:image/") or ";base64," not in data_url:
        raise ValueError("OpenCode reader only accepts inline base64 image URLs")
    header, encoded = data_url.split(",", 1)
    media_type = header[5:].split(";", 1)[0]
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(media_type)
    if extension is None:
        raise ValueError(f"Unsupported image media type: {media_type}")
    output = path_stem.with_suffix(extension)
    output.write_bytes(base64.b64decode(encoded, validate=True))
    return output


def materialize_message_parts(messages: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    text_chunks: list[str] = []
    image_attachments: list[Path] = []
    ordinal = 0
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            text_chunks.append(f"<<<{role.upper()} PART {ordinal}>>>\n{content}\n")
            ordinal += 1
            continue
        if not isinstance(content, list):
            raise ValueError(f"Unsupported message content for role {role}")
        for part in content:
            if not isinstance(part, dict):
                raise ValueError("OpenCode reader received a non-object message part")
            part_type = part.get("type")
            if part_type == "text" and isinstance(part.get("text"), str):
                text_chunks.append(f"<<<{role.upper()} PART {ordinal}>>>\n{part['text']}\n")
            elif part_type == "image_url":
                image_url = part.get("image_url")
                if not isinstance(image_url, dict) or not isinstance(image_url.get("url"), str):
                    raise ValueError("OpenCode reader received an invalid image URL part")
                image_number = len(image_attachments) + 1
                text_chunks.append(
                    f"<<<{role.upper()} PART {ordinal}: ATTACHED IMAGE {image_number}>>>\n"
                )
                image_attachments.append(
                    _write_data_image(output_dir / f"image-{image_number:04d}", image_url["url"])
                )
            else:
                raise ValueError(f"Unsupported OpenCode message part type: {part_type}")
            ordinal += 1
    if not text_chunks and not image_attachments:
        raise ValueError("OpenCode reader received no prompt parts")
    prompt_path = output_dir / "benchmark-prompt.txt"
    prompt_path.write_text("\n".join(text_chunks), encoding="utf-8")
    return [prompt_path, *image_attachments]


def _parse_json_events(stdout: str) -> tuple[str, dict[str, Any]]:
    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    session_id: str | None = None
    errors: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event.get("sessionID"), str):
            session_id = event["sessionID"]
        event_type = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if event_type in {"tool", "tool_use", "tool_call"} or part.get("type") in {
            "tool",
            "tool_use",
            "tool_call",
        }:
            raise RuntimeError("OpenCode reader attempted a tool call")
        if event_type == "text" and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
        elif event_type == "step_finish":
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            usage = {
                "prompt_tokens": int(tokens.get("input", 0) or 0),
                "completion_tokens": int(tokens.get("output", 0) or 0),
                "reasoning_tokens": int(tokens.get("reasoning", 0) or 0),
                "total_tokens": int(tokens.get("total", 0) or 0),
                "cached_input_tokens": int(cache.get("read", 0) or 0),
                "cache_write_tokens": int(cache.get("write", 0) or 0),
                "reported_cost_usd": float(part.get("cost", 0) or 0),
                "finish_reason": str(part.get("reason") or ""),
            }
        elif event_type == "error":
            errors.append(json.dumps(event.get("error"), ensure_ascii=True))
    text = "".join(text_parts).strip()
    if errors:
        raise RuntimeError("OpenCode reader error: " + " | ".join(errors))
    if not text:
        raise RuntimeError("OpenCode reader returned no final text")
    usage["opencode_session_id"] = session_id
    usage["transport"] = "opencode_cli_chatgpt_oauth"
    return text, usage


def call_opencode_reader(
    messages: list[dict[str, Any]],
    *,
    model: str,
    timeout_seconds: float,
    variant: str = "low",
    executable: Path = DEFAULT_EXECUTABLE,
) -> tuple[str, dict[str, Any]]:
    if not executable.exists():
        raise FileNotFoundError(f"OpenCode executable not found: {executable}")
    with tempfile.TemporaryDirectory(prefix="engram-lme-opencode-") as temp_name:
        temp_dir = Path(temp_name)
        attachments = materialize_message_parts(messages, temp_dir)
        prompt_path, *image_attachments = attachments
        opencode_arguments = [
            "run",
            "--pure",
            "--print-logs",
            "--log-level",
            "INFO",
            "--model",
            f"openai/{model}",
            "--variant",
            variant,
            "--format",
            "json",
        ]
        if image_attachments:
            opencode_arguments.extend(["--file", *(str(path) for path in image_attachments)])
        command = subprocess.list2cmdline([str(executable), *opencode_arguments])
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("OPENCODE_CONFIG", None)
        environment.pop("OPENCODE_CONFIG_DIR", None)
        environment.pop("OPENCODE_CONFIG_CONTENT", None)
        environment.update(
            {
                "OPENCODE_DISABLE_AUTOCOMPACT": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "true",
                "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
            }
        )
        prompt = prompt_path.read_text(encoding="utf-8") + "\n\n" + FINAL_INSTRUCTION
        completed = subprocess.run(
            command,
            shell=True,
            cwd=PROJECT_ROOT,
            env=environment,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"OpenCode reader exited with code {completed.returncode}: {detail[-4000:]}"
            )
        text, usage = _parse_json_events(completed.stdout)
        usage["image_attachment_count"] = len(image_attachments)
        usage["requested_model"] = model
        usage["requested_variant"] = variant
        return text, usage


async def call_opencode_reader_async(
    messages: list[dict[str, Any]],
    *,
    model: str,
    timeout_seconds: float,
    variant: str = "low",
) -> tuple[str, dict[str, Any]]:
    return await asyncio.to_thread(
        call_opencode_reader,
        messages,
        model=model,
        timeout_seconds=timeout_seconds,
        variant=variant,
    )
