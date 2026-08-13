#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("openclaw-heartbeat-event-check.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_heartbeat_event_check", MODULE_PATH
)
assert SPEC and SPEC.loader
event_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(event_module)


class HeartbeatEventCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started_at = 1_000
        self.base = {
            "ts": 2_000,
            "status": "ok-empty",
            "reason": "interval",
            "durationMs": 37,
            "silent": True,
            "indicatorType": "ok",
        }

    def test_native_ok_empty_event_passes(self) -> None:
        self.assertEqual(
            event_module.validate_event(self.base, self.started_at), self.base
        )

    def test_native_ok_token_event_passes(self) -> None:
        event = {
            **self.base,
            "status": "ok-token",
            "preview": "No sourced event is due.",
        }
        self.assertEqual(event_module.validate_event(event, self.started_at), event)

    def test_null_stale_and_skipped_events_wait(self) -> None:
        self.assertIsNone(event_module.validate_event(None, self.started_at))
        self.assertIsNone(
            event_module.validate_event({**self.base, "ts": 999}, self.started_at)
        )
        self.assertIsNone(
            event_module.validate_event(
                {**self.base, "status": "skipped"}, self.started_at
            )
        )

    def test_delivery_route_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            event_module.HeartbeatEventError, "heartbeat-event-route-present"
        ):
            event_module.validate_event(
                {**self.base, "channel": "discord"}, self.started_at
            )

    def test_sent_and_failed_events_are_rejected(self) -> None:
        for status in ("sent", "failed"):
            with self.subTest(status=status), self.assertRaisesRegex(
                event_module.HeartbeatEventError,
                "heartbeat-event-unexpected-status",
            ):
                event_module.validate_event(
                    {**self.base, "status": status}, self.started_at
                )

    def test_ok_empty_event_cannot_hide_preview_text(self) -> None:
        with self.assertRaisesRegex(
            event_module.HeartbeatEventError, "heartbeat-empty-preview-present"
        ):
            event_module.validate_event(
                {**self.base, "preview": "BEAT_OK"}, self.started_at
            )

    def test_waiter_returns_first_fresh_success(self) -> None:
        responses = iter(
            [
                None,
                {**self.base, "ts": 999},
                self.base,
            ]
        )
        with mock.patch.object(event_module.time, "sleep", return_value=None):
            result = event_module.wait_for_event(
                Path("/immutable/openclaw"),
                self.started_at,
                wait_seconds=30,
                poll_seconds=0.01,
                query_timeout_seconds=1,
                query=lambda _path, _timeout: next(responses),
            )
        self.assertEqual(result, self.base)

    def test_timeout_reports_only_last_event_metadata(self) -> None:
        event = {
            **self.base,
            "status": "skipped",
            "reason": "requests-in-flight",
            "preview": "private content must not leak",
            "to": "private target must not leak",
        }
        with mock.patch.object(
            event_module.time, "monotonic", side_effect=[0.0, 1.0]
        ), mock.patch.object(event_module.time, "sleep", return_value=None):
            with self.assertRaises(event_module.HeartbeatEventError) as raised:
                event_module.wait_for_event(
                    Path("/immutable/openclaw"),
                    self.started_at,
                    wait_seconds=0.5,
                    poll_seconds=0.01,
                    query_timeout_seconds=1,
                    query=lambda _path, _timeout: event,
                )
        message = str(raised.exception)
        self.assertIn("queries=1", message)
        self.assertIn("status='skipped'", message)
        self.assertIn("reason='requests-in-flight'", message)
        self.assertNotIn("private content", message)
        self.assertNotIn("private target", message)

    def test_rehearsal_start_requires_unix_milliseconds(self) -> None:
        now_ms = 1_786_590_901_000
        self.assertEqual(
            event_module.validate_started_at_ms(now_ms, now_ms=now_ms), now_ms
        )
        with self.assertRaisesRegex(
            event_module.HeartbeatEventError,
            "started-at-not-unix-milliseconds",
        ):
            event_module.validate_started_at_ms(
                1_786_590_901_301_169_606,
                now_ms=now_ms,
            )

    def test_rehearsal_start_rejects_stale_milliseconds(self) -> None:
        now_ms = 1_786_590_901_000
        with self.assertRaisesRegex(
            event_module.HeartbeatEventError, "started-at-too-old"
        ):
            event_module.validate_started_at_ms(
                now_ms - event_module.MAX_START_AGE_MS - 1,
                now_ms=now_ms,
            )

    def test_executable_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "openclaw.mjs"
            target.write_text("#!/bin/sh\n", encoding="utf-8")
            target.chmod(0o755)
            alias = root / "openclaw"
            alias.symlink_to(target)
            with self.assertRaisesRegex(
                event_module.HeartbeatEventError, "openclaw-symlink"
            ):
                event_module._executable(alias)


if __name__ == "__main__":
    unittest.main()
