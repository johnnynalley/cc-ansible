#!/usr/bin/python3
"""Regression tests for the approval-gated OpenClaw Docker update broker."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("openclaw-docker-update-broker.py")
SPEC = importlib.util.spec_from_file_location("openclaw_docker_update_broker", SCRIPT)
assert SPEC and SPEC.loader
broker_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = broker_module
SPEC.loader.exec_module(broker_module)


OLD_ID = "sha256:" + "1" * 64
NEW_ID = "sha256:" + "2" * 64
OLD_DIGEST = "registry.example/app@sha256:" + "3" * 64
NEW_DIGEST = "registry.example/app@sha256:" + "4" * 64
CONTAINER_ID = "5" * 64
REDACTION_SENTINEL = "DO_NOT_LEAK_BROKER_SENTINEL"


class FakeRunner:
    def __init__(self, project: Path, fail_candidate_health: bool = False):
        self.project = project
        self.current_image = OLD_ID
        self.local_tag_image = OLD_ID
        self.fail_candidate_health = fail_candidate_health
        self.current_unhealthy = False
        self.commands: list[list[str]] = []
        self.config = {
            "services": {
                "app": {
                    "image": "registry.example/app:stable",
                    "environment": {"SETTING": REDACTION_SENTINEL},
                }
            }
        }

    def image_payload(self, image_id: str) -> list[dict[str, Any]]:
        is_new = image_id == NEW_ID
        return [
            {
                "Id": image_id,
                "RepoDigests": [NEW_DIGEST if is_new else OLD_DIGEST],
                "Config": {
                    "Env": [f"SETTING={REDACTION_SENTINEL}"],
                    "Labels": {
                        "org.opencontainers.image.version": (
                            "2.0.0" if is_new else "1.0.0"
                        ),
                        "org.opencontainers.image.revision": "new" if is_new else "old",
                        "private.secret": REDACTION_SENTINEL,
                    },
                },
            }
        ]

    def run(self, command: list[str], code: str) -> bytes:
        del code
        self.commands.append(command.copy())
        if "config" in command and command[-2:] == ["--format", "json"]:
            return broker_module.canonical_bytes(self.config)
        if "pull" in command:
            self.local_tag_image = NEW_ID
            return b"pulled\n"
        if "ps" in command and "-q" in command:
            return f"{CONTAINER_ID}\n".encode()
        if command[1:2] == ["inspect"] and command[-1] == CONTAINER_ID:
            state: dict[str, Any] = {"Status": "running"}
            if self.current_unhealthy:
                state["Health"] = {
                    "Status": "unhealthy",
                    "Log": [REDACTION_SENTINEL],
                }
            else:
                state["Health"] = {
                    "Status": "healthy",
                    "Log": [REDACTION_SENTINEL],
                }
            return broker_module.canonical_bytes(
                [
                    {
                        "Image": self.current_image,
                        "State": state,
                        "Mounts": [REDACTION_SENTINEL],
                    }
                ]
            )
        if command[1:3] == ["image", "inspect"]:
            image = command[-1]
            if image == "registry.example/app:stable":
                image = self.local_tag_image
            elif image.startswith("openclaw-rollback/"):
                image = OLD_ID
            return broker_module.canonical_bytes(self.image_payload(image))
        if command[1:3] == ["image", "tag"]:
            return b""
        if "up" in command:
            override = Path(command[command.index("up") - 1])
            image = json.loads(override.read_text())["services"]["app"]["image"]
            if image == NEW_DIGEST:
                self.current_image = NEW_ID
                self.current_unhealthy = self.fail_candidate_health
            elif image.startswith("openclaw-rollback/"):
                self.current_image = OLD_ID
                self.current_unhealthy = False
            else:
                raise AssertionError(f"unexpected override image: {image}")
            return b"updated\n"
        raise AssertionError(f"unexpected command: {command}")


class BrokerFixture:
    def __init__(self, fail_candidate_health: bool = False):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.compose = self.project / "docker-compose.yml"
        self.env = self.project / ".env"
        self.compose.write_text(
            "services:\n  app:\n    image: registry.example/app:stable\n"
        )
        self.env.write_text(f"SETTING={REDACTION_SENTINEL}\n")
        target = broker_module.Target(
            target_id="example.app",
            project_dir=self.project,
            compose_files=(self.compose,),
            backup_files=(self.compose, self.env),
            service="app",
            recreate_services=("app",),
            verify_services=("app",),
            required_paths=(),
            health_timeout_seconds=10,
        )
        self.settings = broker_module.Settings(
            host=socket.gethostname().split(".")[0],
            state_dir=self.root / "state",
            docker_binary="/usr/bin/docker",
            plan_ttl_seconds=1800,
            approval_ttl_seconds=900,
            proposal_cooldown_seconds=300,
            command_timeout_seconds=900,
            health_poll_seconds=1,
            targets={"example.app": target},
        )
        self.runner = FakeRunner(self.project, fail_candidate_health)
        self.broker = broker_module.Broker(self.settings, self.runner)
        self.broker.ensure_state()

    def close(self) -> None:
        self.temporary.cleanup()


class ManifestTests(unittest.TestCase):
    def valid_manifest(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "host": socket.gethostname().split(".")[0],
            "stateDir": "/var/lib/openclaw-docker-update",
            "dockerBinary": "/usr/bin/docker",
            "planTtlSeconds": 1800,
            "approvalTtlSeconds": 900,
            "proposalCooldownSeconds": 300,
            "commandTimeoutSeconds": 900,
            "healthPollSeconds": 5,
            "targets": {
                "media-stack.gluetun": {
                    "projectDir": "/opt/media-stack",
                    "composeFiles": ["docker-compose.yml"],
                    "backupFiles": ["docker-compose.yml", ".env"],
                    "service": "gluetun",
                    "recreateServices": ["gluetun", "qbittorrent"],
                    "verifyServices": ["gluetun", "qbittorrent"],
                    "requiredPaths": ["/srv/archive"],
                    "healthTimeoutSeconds": 180,
                }
            },
        }

    def test_manifest_accepts_only_fixed_target_structure(self) -> None:
        settings = broker_module.parse_manifest(self.valid_manifest())
        self.assertEqual(set(settings.targets), {"media-stack.gluetun"})

    def test_manifest_rejects_project_traversal(self) -> None:
        manifest = self.valid_manifest()
        manifest["targets"]["media-stack.gluetun"]["composeFiles"] = ["../secret"]
        with self.assertRaisesRegex(broker_module.BrokerError, "invalid-manifest"):
            broker_module.parse_manifest(manifest)

    def test_manifest_rejects_unknown_fields(self) -> None:
        manifest = self.valid_manifest()
        manifest["targets"]["media-stack.gluetun"]["command"] = "docker ps"
        with self.assertRaisesRegex(broker_module.BrokerError, "invalid-manifest"):
            broker_module.parse_manifest(manifest)


class RequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = BrokerFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def propose(self) -> dict[str, Any]:
        return self.fixture.broker.handle_request(
            {"schemaVersion": 1, "action": "propose", "targetId": "example.app"}
        )

    def test_request_rejects_free_form_fields(self) -> None:
        with self.assertRaisesRegex(broker_module.BrokerError, "invalid-request"):
            self.fixture.broker.handle_request(
                {
                    "schemaVersion": 1,
                    "action": "propose",
                    "targetId": "example.app",
                    "path": "/root",
                }
            )

    def test_proposal_is_content_addressed_and_redacted(self) -> None:
        response = self.propose()
        self.assertEqual(response["status"], "approval-required")
        self.assertRegex(response["planId"], r"^[a-f0-9]{64}$")
        encoded = broker_module.canonical_bytes(response).decode()
        self.assertNotIn(REDACTION_SENTINEL, encoded)
        self.assertNotIn(str(self.fixture.project), encoded)
        self.assertFalse(
            any("up" in command for command in self.fixture.runner.commands)
        )

    def test_execution_requires_separate_approval(self) -> None:
        plan = self.propose()
        with self.assertRaisesRegex(broker_module.BrokerError, "approval-required"):
            self.fixture.broker.execute(plan["planId"])

    def test_approved_plan_executes_once(self) -> None:
        plan = self.propose()
        self.fixture.broker.approve(plan["planId"])
        result = self.fixture.broker.execute(plan["planId"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["rollback"], "not-needed")
        self.assertNotIn(
            REDACTION_SENTINEL, broker_module.canonical_bytes(result).decode()
        )
        with self.assertRaisesRegex(broker_module.BrokerError, "plan-already-consumed"):
            self.fixture.broker.execute(plan["planId"])

    def test_candidate_drift_is_rejected_before_apply(self) -> None:
        plan = self.propose()
        self.fixture.broker.approve(plan["planId"])
        self.fixture.runner.local_tag_image = OLD_ID
        with self.assertRaisesRegex(broker_module.BrokerError, "candidate-drift"):
            self.fixture.broker.execute(plan["planId"])
        self.assertEqual(
            self.fixture.broker.load_state(plan["planId"])["status"], "proposed"
        )

    def test_failed_health_check_rolls_back(self) -> None:
        self.fixture.runner.fail_candidate_health = True
        plan = self.propose()
        self.fixture.broker.approve(plan["planId"])
        result = self.fixture.broker.execute(plan["planId"])
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(result["rollback"], "succeeded")
        self.assertEqual(result["errorCode"], "health-check-failed")
        self.assertEqual(self.fixture.runner.current_image, OLD_ID)

    def test_plan_tampering_is_detected(self) -> None:
        plan = self.propose()
        path = self.fixture.broker.plan_path(plan["planId"])
        payload = json.loads(path.read_text())
        payload["service"] = "other"
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(broker_module.BrokerError, "invalid-plan"):
            self.fixture.broker.status(plan["planId"])

    def test_approval_expiry_is_enforced(self) -> None:
        plan = self.propose()
        self.fixture.broker.approve(plan["planId"])
        approval_path = self.fixture.broker.approval_path(plan["planId"])
        approval = json.loads(approval_path.read_text())
        approval["expiresAt"] = broker_module.format_time(
            broker_module.utc_now() - dt.timedelta(seconds=1)
        )
        broker_module.atomic_write_json(approval_path, approval)
        with self.assertRaisesRegex(broker_module.BrokerError, "approval-expired"):
            self.fixture.broker.execute(plan["planId"])


if __name__ == "__main__":
    unittest.main()
