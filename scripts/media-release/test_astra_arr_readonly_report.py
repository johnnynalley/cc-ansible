#!/usr/bin/env python3
"""Regression tests for Astra's bounded Arr reports."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("astra_arr_readonly_report.py")
SPEC = importlib.util.spec_from_file_location("astra_arr_readonly_report", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ArrReadonlyReportTests(unittest.TestCase):
    def test_queue_report_bounds_and_allowlists_qbit_samples(self) -> None:
        transaction = {
            "checked_at": "2026-09-03T00:00:00Z",
            "live_queue": {"queue_count": 2},
            "snapshots": {"last_count": 2},
        }
        qbit = {
            "total": 1,
            "state_counts": {"stalledDL": 1},
            "classification_counts": {"stale_no_peers": 1},
            "finding_counts": {"stale_no_peers": 1},
            "samples": {
                "stalledDL": [
                    {
                        "name": "Example",
                        "hash": "a" * 12,
                        "state": "stalledDL",
                        "tracker": "must-not-leak",
                        "arr_correlation": {
                            "app": "sonarr",
                            "classification": "stale_no_peers",
                            "findings": ["stale_no_peers"],
                            "history": {"grab_batch_count": 2, "indexers": ["Example"]},
                        },
                    }
                ]
            },
        }
        with mock.patch.object(MODULE, "transaction_payload", return_value=transaction), mock.patch.object(
            MODULE, "run_json", return_value=qbit
        ):
            report = MODULE.queue_report()

        self.assertEqual(report["report"], "arr-queue")
        self.assertEqual(report["qBittorrent"]["samples"][0]["arr"]["grabBatchCount"], 2)
        self.assertNotIn("tracker", report["qBittorrent"]["samples"][0])

    def test_policy_report_retains_invariants_but_not_arbitrary_fields(self) -> None:
        value = {
            "instances": [
                {
                    "instance": "sonarr",
                    "custom_format_count": 100,
                    "custom_format_limit": 100,
                    "failures": [],
                    "ignored": "no",
                    "profiles": [
                        {
                            "profile": "shows-anime-efficient",
                            "x265_score": 5000,
                            "stacks": {"best": {"score": 1880}},
                            "secret": "must-not-leak",
                        }
                    ],
                }
            ]
        }
        with mock.patch.object(MODULE, "run_json", return_value=value):
            report = MODULE.policy_report()

        profile = report["instances"][0]["profiles"][0]
        self.assertEqual(profile["x265_score"], 5000)
        self.assertNotIn("secret", profile)

    def test_unknown_report_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.ReportError, "invalid-report"):
            MODULE.build_report("delete")


if __name__ == "__main__":
    unittest.main()
