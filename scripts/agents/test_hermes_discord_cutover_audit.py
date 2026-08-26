#!/usr/bin/env python3
"""Regression tests for the Hermes Discord cutover contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_PATH = Path(__file__).with_name("hermes-discord-cutover-audit.py")
CONTRACT_PATH = ROOT / "files" / "hermes" / "discord-cutover-contract.json"
REGRESSIONS_PATH = ROOT / "files" / "hermes" / "discord-regressions.json"

SPEC = importlib.util.spec_from_file_location(
    "hermes_discord_cutover_audit", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class HermesDiscordCutoverAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.regressions = json.loads(REGRESSIONS_PATH.read_text(encoding="utf-8"))

    def write_contract(self, root: Path, payload: dict) -> Path:
        path = root / "contract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_real_contract_passes(self) -> None:
        result = MODULE.audit_contract(CONTRACT_PATH, ROOT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["profiles"], ["astra", "dubble", "rigel"])
        self.assertEqual(result["distinctIdentities"], 3)
        self.assertEqual(result["promotionCases"], 12)
        self.assertFalse(result["liveChangeAuthorized"])
        dubble = next(
            profile for profile in self.contract["profiles"]
            if profile["name"] == "dubble"
        )
        self.assertEqual(
            dubble["allowedRolesRef"],
            "policy:dubble-discord-parity/guilds-as-everyone-roles",
        )

    def test_cli_output_is_content_free(self) -> None:
        result = subprocess.run(
            [str(MODULE_PATH), str(CONTRACT_PATH), "--repository-root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        serialized = result.stdout.lower()
        for forbidden in ("token=", "channel-id", "user-id", "message-content"):
            self.assertNotIn(forbidden, serialized)

    def test_every_authority_change_is_rejected(self) -> None:
        for key in MODULE.EXPECTED_AUTHORITY:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["authority"][key] = True
                with self.assertRaisesRegex(
                    MODULE.DiscordCutoverAuditError, "authority drift"
                ):
                    MODULE.audit_contract(
                        self.write_contract(Path(directory), payload), ROOT
                    )

    def test_duplicate_token_identity_or_home_is_rejected(self) -> None:
        for field in (
            "botTokenRef",
            "applicationIdentityRef",
            "home",
            "credentialFile",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["profiles"][1][field] = payload["profiles"][0][field]
                with self.assertRaises(MODULE.DiscordCutoverAuditError):
                    MODULE.audit_contract(
                        self.write_contract(Path(directory), payload), ROOT
                    )

    def test_rigel_cannot_reuse_astra_discord_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            rigel = payload["profiles"][2]
            rigel["applicationIdentityRef"] = payload["profiles"][0][
                "applicationIdentityRef"
            ]
            with self.assertRaisesRegex(
                MODULE.DiscordCutoverAuditError, "not distinct"
            ):
                MODULE.audit_contract(
                    self.write_contract(Path(directory), payload), ROOT
                )

    def test_allow_all_pairing_bot_input_or_backfill_is_rejected(self) -> None:
        mutations = {
            "allowAllUsers": True,
            "credentialFilesAgentWritable": True,
            "credentialFilesServiceReadable": False,
            "unknownDirectMessages": "pair",
            "allowBots": "mentions",
            "historyBackfill": True,
            "missedMessageBackfill": True,
            "groupSessionsPerUser": False,
            "threadRequireMention": False,
        }
        for key, value in mutations.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload["invariants"][key] = value
                with self.assertRaisesRegex(
                    MODULE.DiscordCutoverAuditError, "invariants drift"
                ):
                    MODULE.audit_contract(
                        self.write_contract(Path(directory), payload), ROOT
                    )

    def test_source_must_stop_and_drain_before_target_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            payload["cutover"]["sourceStopOrder"] = list(
                reversed(payload["cutover"]["sourceStopOrder"])
            )
            with self.assertRaisesRegex(
                MODULE.DiscordCutoverAuditError, "source stop order drift"
            ):
                MODULE.audit_contract(
                    self.write_contract(Path(directory), payload), ROOT
                )

    def test_health_receiver_cannot_be_stopped(self) -> None:
        for section in ("cutover", "rollback"):
            with self.subTest(
                section=section
            ), tempfile.TemporaryDirectory() as directory:
                payload = copy.deepcopy(self.contract)
                payload[section]["healthReceiverDisposition"] = "stop"
                with self.assertRaisesRegex(
                    MODULE.DiscordCutoverAuditError, "Health receiver"
                ):
                    MODULE.audit_contract(
                        self.write_contract(Path(directory), payload), ROOT
                    )

    def test_rollback_requires_hermes_stop_before_openclaw_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            order = payload["rollback"]["order"]
            restart = order.pop(order.index("start-openclaw-user-gateway"))
            order.insert(0, restart)
            with self.assertRaisesRegex(
                MODULE.DiscordCutoverAuditError, "rollback order"
            ):
                MODULE.audit_contract(
                    self.write_contract(Path(directory), payload), ROOT
                )

    def test_source_pin_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = copy.deepcopy(self.contract)
            payload["sourcePins"]["sourceDeliveryAudit"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(
                MODULE.DiscordCutoverAuditError, "source pin drift"
            ):
                MODULE.audit_contract(
                    self.write_contract(Path(directory), payload), ROOT
                )

    def test_all_runtime_cases_are_blocking_and_sanitized(self) -> None:
        cases = self.regressions["cases"]
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case["id"] for case in cases}), 12)
        for case in cases:
            self.assertEqual(case["risk"], "blocking")
            serialized = json.dumps(case)
            self.assertNotIn("/home/", serialized)
            self.assertNotIn("@Jaah", serialized)
            self.assertNotRegex(serialized, r"\b\d{16,20}\b")


if __name__ == "__main__":
    unittest.main()
