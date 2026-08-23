#!/usr/bin/env python3
"""Regression tests for Arr grab-context notification configuration."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("arr_grab_context_configure.py")
SPEC = importlib.util.spec_from_file_location("arr_grab_context_configure", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NotificationTests(unittest.TestCase):
    def test_only_grab_event_is_enabled(self) -> None:
        schema = {
            "name": "Webhook",
            "implementation": "Webhook",
            "configContract": "WebhookSettings",
            "onGrab": False,
            "onDownload": True,
            "onHealthIssue": True,
            "fields": [
                {"name": "url", "value": None},
                {"name": "method", "value": 0},
                {"name": "headers", "value": []},
            ],
            "presets": [{"name": "ignored"}],
            "tags": [1],
        }
        desired = MODULE.desired_notification(schema, "Arr Grab Context", "http://ledger/v1/events")
        self.assertTrue(desired["onGrab"])
        self.assertFalse(desired["onDownload"])
        self.assertFalse(desired["onHealthIssue"])
        self.assertNotIn("presets", desired)
        self.assertEqual(desired["tags"], [])
        self.assertEqual(
            next(field for field in desired["fields"] if field["name"] == "url")["value"],
            "http://ledger/v1/events",
        )


if __name__ == "__main__":
    unittest.main()
