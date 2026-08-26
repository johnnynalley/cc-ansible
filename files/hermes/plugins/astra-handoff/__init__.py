"""Expose a fixed-target Dubble-to-Astra Hermes peer handoff."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from agent.secret_scope import get_secret


HERMES = Path("/usr/local/bin/hermes")
MAX_RESPONSE = 64 * 1024

SCHEMA = {
    "name": "astra_handoff",
    "description": (
        "Ask Astra for private guidance about one active Dubble support thread. "
        "The target is fixed to Astra and the response must be relayed without "
        "exposing Astra sessions, memory, or tools."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 4000}
        },
        "required": ["message"],
        "additionalProperties": False,
    },
}


def _handler(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or set(args) != {"message"}:
        return json.dumps({"status": "error", "code": "invalid-request"})
    message = args.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return json.dumps({"status": "error", "code": "invalid-message"})
    key = (get_secret("HERMES_PEER_ASTRA_KEY", "") or "").strip()
    if not key:
        return json.dumps({"status": "error", "code": "peer-key-unavailable"})
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": "/var/lib/hermes/dubble",
            "HERMES_HOME": "/var/lib/hermes/dubble/.hermes/profiles/dubble",
            "HERMES_MANAGED_DIR": "/etc/hermes/dubble",
            "HERMES_PEER_ASTRA_KEY": key,
        }
    )
    try:
        result = subprocess.run(
            [str(HERMES), "peer", "dm", "astra", message.strip()],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=630,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return json.dumps({"status": "error", "code": "peer-request-failed"})
    output = result.stdout.strip()
    if result.returncode != 0:
        return json.dumps(
            {
                "status": "error",
                "code": "peer-request-rejected",
                "detail": result.stderr.strip()[:240],
            }
        )
    if not output or len(output.encode("utf-8")) > MAX_RESPONSE:
        return json.dumps({"status": "error", "code": "peer-response-invalid"})
    return json.dumps({"status": "ok", "response": output})


def _check() -> bool:
    return HERMES.is_file() and not HERMES.is_symlink()


def register(ctx: Any) -> None:
    ctx.register_tool(
        name=SCHEMA["name"],
        toolset="astra_handoff",
        schema=SCHEMA,
        handler=_handler,
        check_fn=_check,
        is_async=False,
    )
