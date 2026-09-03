#!/usr/bin/env python3
"""Regression tests for the managed Sonarr transaction monitor."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[2] / "files" / "sonarr-transaction-monitor.py"
SPEC = importlib.util.spec_from_file_location("sonarr_transaction_monitor", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SonarrTransactionMonitorTests(unittest.TestCase):
    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            no_qbit_audit=False,
            qbit_audit_script=Path("/usr/local/bin/qbit-arr-stall-audit"),
            qbit_audit_sample_limit=20,
            qbit_audit_timeout_sec=120,
        )

    @mock.patch.object(MODULE.subprocess, "run")
    def test_qbit_stall_audit_records_only_bounded_safe_report(
        self,
        run: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "total": 2,
                    "state_counts": {"stalledDL": 2},
                    "category_counts": {"tv-sonarr": 2},
                    "classification_counts": {"stale_no_peers": 2},
                    "finding_counts": {"stale_no_peers": 2},
                    "samples": {"stalledDL": [{"name": "Example"}]},
                    "delete_candidates": [{"name": "must not be copied"}],
                }
            ),
            stderr="",
        )

        event = MODULE.qbit_stall_audit_event(
            self.args(),
            "2026-09-03T00:00:00Z",
        )

        self.assertTrue(event["ok"])
        self.assertEqual(event["classificationCounts"], {"stale_no_peers": 2})
        self.assertNotIn("delete_candidates", event)
        command = run.call_args.args[0]
        self.assertIn("--correlate-arr", command)
        self.assertNotIn("--include-arr-history", command)

    @mock.patch.object(MODULE.subprocess, "run")
    def test_qbit_stall_audit_timeout_is_a_monitoring_failure(
        self,
        run: mock.Mock,
    ) -> None:
        run.side_effect = subprocess.TimeoutExpired(["audit"], 120)

        event = MODULE.qbit_stall_audit_event(
            self.args(),
            "2026-09-03T00:00:00Z",
        )

        self.assertFalse(event["ok"])
        self.assertIn("timed out", event["error"])
        self.assertEqual(event["samples"], {})


if __name__ == "__main__":
    unittest.main()
