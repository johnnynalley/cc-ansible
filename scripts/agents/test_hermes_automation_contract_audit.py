#!/usr/bin/env python3
"""Regression tests for the Hermes automation and Health contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_PATH = Path(__file__).with_name("hermes-automation-contract-audit.py")
CONTRACT_PATH = ROOT / "files" / "hermes" / "automation-contract.json"
REGRESSIONS_PATH = ROOT / "files" / "hermes" / "automation-regressions.json"

SPEC = importlib.util.spec_from_file_location(
    "hermes_automation_contract_audit", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class HermesAutomationContractAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.regressions = json.loads(REGRESSIONS_PATH.read_text(encoding="utf-8"))

    def write_json(self, root: Path, name: str, payload: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def source_inventory(self) -> dict:
        jobs = []
        for row in self.contract["schedules"]:
            source = row["source"]
            if source["type"] != "cron":
                continue
            schedule = source["schedule"]
            actual_schedule = {
                "kind": schedule["kind"],
                "expression": schedule["value"] if schedule["kind"] == "cron" else None,
                "timezone": schedule["timezone"],
                "everyMs": (
                    int(schedule["value"]) if schedule["kind"] == "every" else None
                ),
                "at": schedule["value"] if schedule["kind"] == "at" else None,
            }
            jobs.append(
                {
                    "name": source["name"],
                    "enabled": source["enabled"],
                    "deleteAfterRun": source["deleteAfterRun"],
                    "schedule": actual_schedule,
                    "payload": {"kind": source["payload"]},
                }
            )
        return {
            "schemaVersion": 1,
            "databaseQuickCheck": "ok",
            "summary": {"jobCount": len(jobs), "enabledCount": len(jobs)},
            "jobs": jobs,
        }

    def test_real_contract_passes(self) -> None:
        result = MODULE.audit_contract(CONTRACT_PATH, ROOT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["schedules"], 31)
        self.assertEqual(result["cronJobs"], 28)
        self.assertEqual(result["heartbeats"], 3)
        self.assertEqual(result["promotionCases"], 14)
        self.assertFalse(result["sourceInventoryCompared"])
        self.assertFalse(result["liveChangeAuthorized"])

    def test_cli_output_is_aggregate_only(self) -> None:
        result = subprocess.run(
            [str(MODULE_PATH), str(CONTRACT_PATH), "--repository-root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        for forbidden in ("channel-id", "user-id", "token=", "message-content"):
            self.assertNotIn(forbidden, result.stdout.lower())

    def test_every_authority_change_is_rejected(self) -> None:
        for key in MODULE.EXPECTED_AUTHORITY:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["authority"][key] = True
                path = self.write_json(Path(directory), "contract.json", payload)
                with self.assertRaisesRegex(
                    MODULE.AutomationContractError, "authority drift"
                ):
                    MODULE.audit_contract(path, ROOT)

    def test_schedule_set_and_disposition_are_fail_closed(self) -> None:
        mutations = [
            ("id", "unknown-schedule"),
            ("disposition", "retire"),
        ]
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["schedules"][0][field] = value
                path = self.write_json(Path(directory), "contract.json", payload)
                with self.assertRaises(MODULE.AutomationContractError):
                    MODULE.audit_contract(path, ROOT)

    def test_command_job_cannot_move_into_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            row = next(
                item
                for item in payload["schedules"]
                if item["id"] == "cron-self-evolution-maintenance"
            )
            row["target"]["owner"] = "hermes-astra"
            path = self.write_json(Path(directory), "contract.json", payload)
            with self.assertRaisesRegex(
                MODULE.AutomationContractError, "external command ownership"
            ):
                MODULE.audit_contract(path, ROOT)

    def test_agent_job_cannot_deliver_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            row = next(
                item
                for item in payload["schedules"]
                if item["id"] == "cron-reddit-hdd-deal-watch"
            )
            row["target"]["output"] = "discord"
            path = self.write_json(Path(directory), "contract.json", payload)
            with self.assertRaisesRegex(
                MODULE.AutomationContractError, "agent delivery boundary"
            ):
                MODULE.audit_contract(path, ROOT)

    def test_health_and_siri_boundaries_are_required(self) -> None:
        for integration, field, value in (
            ("healthReceiver", "modelAccess", "raw-database"),
            ("siriRelay", "targetState", "active"),
        ):
            with self.subTest(
                integration=integration
            ), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["integrations"][integration][field] = value
                path = self.write_json(Path(directory), "contract.json", payload)
                with self.assertRaises(MODULE.AutomationContractError):
                    MODULE.audit_contract(path, ROOT)

    def test_fresh_source_inventory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_json(
                Path(directory), "inventory.json", self.source_inventory()
            )
            result = MODULE.audit_contract(CONTRACT_PATH, ROOT, inventory)
            self.assertTrue(result["sourceInventoryCompared"])
            self.assertEqual(result["presentSourceJobs"], 28)

    def test_expired_one_shot_may_be_absent_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.source_inventory()
            payload["jobs"] = [
                row for row in payload["jobs"] if not row["deleteAfterRun"]
            ]
            payload["summary"]["jobCount"] = len(payload["jobs"])
            payload["summary"]["enabledCount"] = len(payload["jobs"])
            inventory = self.write_json(Path(directory), "inventory.json", payload)
            result = MODULE.audit_contract(CONTRACT_PATH, ROOT, inventory)
            self.assertEqual(result["presentSourceJobs"], 24)

    def test_missing_stable_or_unknown_source_job_blocks(self) -> None:
        for mutation in ("missing", "unknown"):
            with self.subTest(
                mutation=mutation
            ), tempfile.TemporaryDirectory() as directory:
                payload = self.source_inventory()
                if mutation == "missing":
                    payload["jobs"] = payload["jobs"][1:]
                else:
                    payload["jobs"].append(
                        {
                            "name": "Unreviewed live job",
                            "enabled": True,
                            "deleteAfterRun": False,
                            "schedule": {
                                "kind": "cron",
                                "expression": "0 0 * * *",
                                "timezone": "America/Chicago",
                                "everyMs": None,
                                "at": None,
                            },
                            "payload": {"kind": "agentTurn"},
                        }
                    )
                payload["summary"]["jobCount"] = len(payload["jobs"])
                payload["summary"]["enabledCount"] = len(payload["jobs"])
                inventory = self.write_json(Path(directory), "inventory.json", payload)
                with self.assertRaises(MODULE.AutomationContractError):
                    MODULE.audit_contract(CONTRACT_PATH, ROOT, inventory)

    def test_regression_corpus_is_blocking_and_sanitized(self) -> None:
        self.assertEqual(len(self.regressions["cases"]), 14)
        for case in self.regressions["cases"]:
            self.assertEqual(case["risk"], "blocking")
            encoded = json.dumps(case)
            self.assertNotIn("/home/", encoded)
            self.assertNotRegex(encoded, r"\b\d{16,20}\b")


if __name__ == "__main__":
    unittest.main()
