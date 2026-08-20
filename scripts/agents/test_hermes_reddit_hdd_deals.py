#!/usr/bin/env python3
"""Tests for the bounded multi-source HDD deal collector."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("hermes-reddit-hdd-deals.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("hermes_reddit_hdd_deals", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HddCollectorTests(unittest.TestCase):
    def test_ebay_candidate_keeps_review_fields(self) -> None:
        value = {
            "itemSummaries": [
                {
                    "itemId": "v1|123|0",
                    "title": "HGST 12TB SATA HDD",
                    "itemWebUrl": "https://www.ebay.com/itm/123",
                    "condition": "Seller refurbished",
                    "price": {"value": "89.00", "currency": "USD"},
                    "shippingOptions": [
                        {"shippingCost": {"value": "0.00", "currency": "USD"}}
                    ],
                    "itemLocation": {"country": "US", "stateOrProvince": "TX"},
                    "buyingOptions": ["FIXED_PRICE"],
                }
            ]
        }

        rows = MODULE.ebay_candidates(value, set())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "eBay")
        self.assertEqual(rows[0]["price"]["value"], "89.00")
        self.assertEqual(rows[0]["location"]["stateOrProvince"], "TX")

    def test_all_source_failures_degrade_without_alert_wall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"HERMES_HOME": temporary}, clear=False),
                mock.patch.object(MODULE, "load_job_status", return_value={}),
                mock.patch.object(MODULE, "reconcile", return_value=("new", None)),
                mock.patch.object(MODULE, "fetch", side_effect=OSError("blocked")),
                mock.patch.object(
                    MODULE, "ebay_token", side_effect=RuntimeError("credentials-missing")
                ),
                contextlib.redirect_stdout(output),
            ):
                result = MODULE.main()

            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(output.getvalue()),
                {"status": "degraded", "candidates": []},
            )
            state = json.loads(
                (Path(temporary) / "state/reddit-hdd-seen.json").read_text()
            )
            self.assertEqual(state["sourceHealth"]["status"], "degraded")
            self.assertEqual(len(state["sourceHealth"]["errors"]), 3)

    def test_ebay_continues_when_reddit_is_blocked(self) -> None:
        listing = {
            "itemSummaries": [
                {
                    "itemId": "v1|456|0",
                    "title": "Seagate Exos 16TB SATA hard drive",
                    "itemWebUrl": "https://www.ebay.com/itm/456",
                    "condition": "Used",
                    "price": {"value": "110.00", "currency": "USD"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"HERMES_HOME": temporary}, clear=False),
                mock.patch.object(MODULE, "load_job_status", return_value={}),
                mock.patch.object(MODULE, "reconcile", return_value=("new", None)),
                mock.patch.object(MODULE, "fetch", side_effect=OSError("blocked")),
                mock.patch.object(MODULE, "ebay_token", return_value="token"),
                mock.patch.object(MODULE, "fetch_ebay", return_value=listing),
                mock.patch.object(
                    MODULE,
                    "stage",
                    return_value={"keys": ["v1|456|0"], "payload": "staged"},
                ),
                contextlib.redirect_stdout(output),
            ):
                result = MODULE.main()

            self.assertEqual(result, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(len(payload["candidates"]), 1)
            self.assertEqual(payload["candidates"][0]["source"], "eBay")
            state = json.loads(
                (Path(temporary) / "state/reddit-hdd-seen.json").read_text()
            )
            self.assertEqual(state["sourceHealth"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
