"""Strict JSON CLI used by the root-owned Astra wrapper."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from typing import Any

from .clients import ApiError, ImmichClient, OllamaClient, SeerrClient
from .config import Config
from .inbox import CLOUD_ERROR_CODES, Inbox, MUTABLE_STATUSES, VISIBLE_STATUSES
from .scanner import Scanner
from .store import Store

BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]{1,400}$")
MAX_ANALYSIS_BYTES = 64 * 1024


def decode_query(value: str) -> str:
    if not BASE64URL_RE.fullmatch(value):
        raise ValueError("search query must be unpadded URL-safe base64")
    padded = value + "=" * (-len(value) % 4)
    try:
        query = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8", errors="strict")
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError("search query is not valid URL-safe base64 UTF-8") from None
    query = query.strip()
    if not 1 <= len(query) <= 160 or any(ord(character) < 32 for character in query):
        raise ValueError("decoded search query must be 1-160 printable characters")
    return query


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="immich-media-inbox")
    subparsers = command_parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--healthcheck", action="store_true")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument(
        "--status", choices=sorted(VISIBLE_STATUSES), default="pending"
    )
    list_parser.add_argument("--limit", type=int, default=20)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("candidate_id")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("candidate_id")
    search_parser.add_argument("query_base64url")

    disposition_parser = subparsers.add_parser("set-status")
    disposition_parser.add_argument("candidate_id")
    disposition_parser.add_argument("status", choices=sorted(MUTABLE_STATUSES))

    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("candidate_id")
    request_parser.add_argument("media_type", choices=("movie", "tv"))
    request_parser.add_argument("media_id", type=int)
    request_parser.add_argument("--season", action="append", type=int, default=[])
    request_parser.add_argument("--confirm", action="store_true")
    request_parser.add_argument("--confirm-ambiguous", action="store_true")

    subparsers.add_parser("claim-cloud")

    export_parser = subparsers.add_parser("export-image")
    export_parser.add_argument("candidate_id")

    submit_parser = subparsers.add_parser("submit-analysis")
    submit_parser.add_argument("candidate_id")

    fail_parser = subparsers.add_parser("fail-cloud")
    fail_parser.add_argument("candidate_id")
    fail_parser.add_argument("error_code", choices=sorted(CLOUD_ERROR_CODES))
    return command_parser


def build_inbox() -> Inbox:
    config = Config.from_env()
    store = Store(config.database_path)
    immich = ImmichClient(
        config.immich_url,
        config.immich_api_key,
        request_delay_ms=config.api_request_delay_ms,
    )
    seerr = SeerrClient(
        config.seerr_url,
        config.seerr_api_key,
        request_delay_ms=config.api_request_delay_ms,
    )
    ollama = OllamaClient(config.ollama_url, config.ollama_model)
    scanner = Scanner(config, store, immich, seerr, ollama)
    return Inbox(config, store, scanner, immich, seerr)


def run(args: argparse.Namespace, inbox: Inbox) -> tuple[dict[str, Any], int]:
    if args.command == "status":
        payload = inbox.status()
        return payload, 0 if not args.healthcheck or payload["healthy"] else 1
    if args.command == "list":
        return inbox.list_candidates(status=args.status, limit=args.limit), 0
    if args.command == "show":
        return inbox.show(args.candidate_id), 0
    if args.command == "search":
        return inbox.search(args.candidate_id, decode_query(args.query_base64url)), 0
    if args.command == "set-status":
        return inbox.set_status(args.candidate_id, args.status), 0
    if args.command == "request":
        return (
            inbox.request(
                args.candidate_id,
                args.media_type,
                args.media_id,
                seasons=args.season,
                confirmed=args.confirm,
                confirm_ambiguous=args.confirm_ambiguous,
            ),
            0,
        )
    if args.command == "claim-cloud":
        return inbox.claim_cloud(), 0
    if args.command == "submit-analysis":
        payload = sys.stdin.buffer.read(MAX_ANALYSIS_BYTES + 1)
        if not payload:
            raise ValueError("analysis JSON is required on stdin")
        if len(payload) > MAX_ANALYSIS_BYTES:
            raise ValueError("analysis JSON exceeds the size limit")
        try:
            decoded = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ValueError("analysis JSON must be UTF-8") from None
        return inbox.submit_cloud_analysis(args.candidate_id, decoded), 0
    if args.command == "fail-cloud":
        return inbox.fail_cloud(args.candidate_id, args.error_code), 0
    raise ValueError("unsupported command")


def main() -> int:
    args = parser().parse_args()
    try:
        inbox = build_inbox()
        if args.command == "export-image":
            sys.stdout.buffer.write(inbox.export_cloud_image(args.candidate_id))
            return 0
        payload, exit_code = run(args, inbox)
        print(json.dumps({"ok": exit_code == 0, **payload}, sort_keys=True))
        return exit_code
    except KeyError:
        error = "candidate not found or no longer visible"
    except (ApiError, RuntimeError, ValueError) as exc:
        error = str(exc)
    print(json.dumps({"ok": False, "error": error}, sort_keys=True), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
