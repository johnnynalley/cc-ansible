#!/usr/bin/env python3
"""Regression tests for exhaustive OpenClaw-to-Hermes parity."""

from __future__ import annotations

import argparse
import errno
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/agents/hermes-openclaw-parity-validate.py"
SPEC = importlib.util.spec_from_file_location("hermes_openclaw_parity", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def arguments(**overrides):
    values = {
        "contract": ROOT / "files/hermes/openclaw-parity-contract.json",
        "skills": ROOT / "files/hermes/profile-skills-contract.json",
        "automation": ROOT / "files/hermes/production-automation-reconciliation.json",
        "astra_manifest": ROOT / "templates/hermes/astra-production-jobs.json.j2",
        "dubble_manifest": ROOT / "templates/hermes/dubble-production-jobs.json.j2",
        "rigel_manifest": ROOT / "templates/hermes/rigel-production-jobs.json.j2",
        "rigel_delivery_mode": "dedicated",
        "source_jobs": Path("/home/johnny/.openclaw/state/openclaw.sqlite"),
        "historical_source_jobs": Path(
            "/home/johnny/.openclaw/cron/jobs.json.migrated"
        ),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class OpenClawParityTests(unittest.TestCase):
    def test_current_source_inventory_is_fully_classified(self):
        result = MODULE.validate(arguments())
        self.assertEqual(result["sourceSkills"], 29)
        self.assertEqual(result["sourceLanes"], 29)
        self.assertEqual(result["historicalLanes"], 7)
        self.assertEqual(result["nativeJobs"], 19)
        self.assertEqual(result["capabilities"], 38)
        self.assertEqual(result["dispositions"]["reenrollment-required"], 1)

    def test_missing_non_skill_capability_fails(self):
        value = json.loads(
            (ROOT / "files/hermes/openclaw-parity-contract.json").read_text()
        )
        value["capabilities"] = [
            row for row in value["capabilities"] if row["id"] != "browser"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "parity.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "capability-inventory"):
                MODULE.validate(arguments(contract=path))

    def test_every_logical_profile_requires_independent_full_parity(self):
        value = json.loads(
            (ROOT / "files/hermes/openclaw-parity-contract.json").read_text()
        )
        self.assertEqual(set(value["logicalProfiles"]), {"astra", "dubble", "rigel"})
        for profile in value["logicalProfiles"].values():
            self.assertTrue(profile["fullParityRequired"])
            self.assertTrue(profile["independentAcceptanceRequired"])
        self.assertEqual(value["logicalProfiles"]["rigel"]["deliveryConsumer"], "rigel")
        self.assertEqual(value["logicalProfiles"]["rigel"]["deliveryMode"], "dedicated-gateway")

    def test_missing_rigel_profile_fails(self):
        value = json.loads(
            (ROOT / "files/hermes/openclaw-parity-contract.json").read_text()
        )
        value["logicalProfiles"].pop("rigel")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "parity.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "logical-profile-inventory"):
                MODULE.validate(arguments(contract=path))

    def test_json_read_failure_is_not_reported_as_malformed_json(self):
        path = Path("production-jobs.json")
        failure = PermissionError(errno.EACCES, "permission denied", str(path))
        with mock.patch.object(Path, "read_text", side_effect=failure):
            with self.assertRaisesRegex(
                MODULE.ParityError,
                r"json-read-failed:production-jobs.json:errno=13",
            ):
                MODULE.load(path)

    def test_unknown_disposition_fails(self):
        value = json.loads(
            (ROOT / "files/hermes/openclaw-parity-contract.json").read_text()
        )
        value["capabilities"][0]["disposition"] = "ignored"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "parity.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "capability-disposition"):
                MODULE.validate(arguments(contract=path))

    def test_missing_hardware_skill_fails(self):
        value = json.loads(
            (ROOT / "files/hermes/profile-skills-contract.json").read_text()
        )
        value["profiles"]["astra"]["skills"] = [
            row
            for row in value["profiles"]["astra"]["skills"]
            if row["name"] != "hardware-inventory"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skills.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "missing-skills"):
                MODULE.validate(arguments(skills=path))

    def test_unclassified_source_lane_fails(self):
        value = json.loads(
            (
                ROOT / "files/hermes/production-automation-reconciliation.json"
            ).read_text()
        )
        value["lanes"].pop("heartbeat-dubble")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "automation.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "lane-count"):
                MODULE.validate(arguments(automation=path, source_jobs=None))

    def test_unclassified_historical_source_lane_fails(self):
        value = json.loads(
            (
                ROOT / "files/hermes/production-automation-reconciliation.json"
            ).read_text()
        )
        value["historicalLanes"].pop("bdede55d-2a51-49a0-81ac-04b01c3d6b55")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "automation.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "historical-lane-count"):
                MODULE.validate(arguments(automation=path, source_jobs=None))

    def test_historical_source_lane_cannot_be_reactivated(self):
        value = json.loads(
            (
                ROOT / "files/hermes/production-automation-reconciliation.json"
            ).read_text()
        )
        value["historicalLanes"][
            "387d772f-6a19-421d-bbfb-52c079004b2f"
        ]["target"] = "astra-daily-summary"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "automation.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ParityError, "historical-target-reactivated"
            ):
                MODULE.validate(arguments(automation=path, source_jobs=None))

    def test_flattened_sqlite_at_schedule_is_preserved(self):
        self.assertEqual(
            MODULE.source_schedule(
                {
                    "schedule_kind": "at",
                    "at": "2026-08-14T14:00:00.000Z",
                }
            ),
            "at 2026-08-14T14:00:00.000Z",
        )

    def test_dubble_never_receives_terminal(self):
        value = json.loads(
            (ROOT / "templates/hermes/dubble-production-jobs.json.j2").read_text()
        )
        value["jobs"][0]["enabledToolsets"].append("terminal")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dubble.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "dubble-terminal"):
                MODULE.validate(arguments(dubble_manifest=path, source_jobs=None))

    def test_daily_summary_cannot_use_local_only_delivery(self):
        value = MODULE.load(
            ROOT / "templates/hermes/astra-production-jobs.json.j2",
            {
                "hermes_rigel_dedicated_discord_enabled": True,
                "hermes_automation_rigel_channel_id": "1000000000000001",
                "hermes_automation_logs_channel_id": "1000000000000002",
                "hermes_astra_logs_channel_id": "1000000000000007",
                "hermes_automation_social_channel_id": "1000000000000003",
                "hermes_automation_owner_user_id": "1000000000000004",
                "hermes_native_update_profile_home": "/tmp/astra",
            },
        )
        daily = next(job for job in value["jobs"] if job["key"] == "daily-summary")
        daily["deliver"] = "local"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "astra.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ParityError, "daily-summary-continuity-contract"
            ):
                MODULE.validate(arguments(astra_manifest=path, source_jobs=None))


if __name__ == "__main__":
    unittest.main()
