#!/usr/bin/env python3
"""Focused regressions for the typed Compose transaction target."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/docker/agent-compose-transaction.py"

spec = importlib.util.spec_from_file_location("agent_compose_transaction", SOURCE)
assert spec and spec.loader
TARGET = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TARGET)


def valid_spec() -> dict:
    return {
        "schemaVersion": 1,
        "services": {
            "hello": {
                "image": "docker.io/library/nginx:1.29.1",
                "ports": [{"target": 8080, "published": 18080, "scope": "loopback", "protocol": "tcp"}],
                "volumes": [{"name": "data", "target": "/data", "readOnly": False}],
                "tmpfs": ["/tmp"],
                "environment": {"LOG_LEVEL": "info"},
            }
        },
    }


class ComposeTransactionTests(unittest.TestCase):
    def test_render_is_allowlisted_and_hardened(self) -> None:
        compose, summary = TARGET.render_spec("demo", valid_spec(), "192.168.1.153")
        service = compose["services"]["hello"]
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["ports"], ["127.0.0.1:18080:8080/tcp"])
        self.assertEqual(set(compose["volumes"]), {"data"})
        self.assertEqual(summary["services"], ["hello"])

    def test_rejects_dangerous_or_unversioned_images(self) -> None:
        for image, code in (
            ("localhost:5000/root/image:1", "registry-denied"),
            ("nginx", "image-version-required"),
            ("nginx:latest", "latest-tag-denied"),
        ):
            value = valid_spec()
            value["services"]["hello"]["image"] = image
            with self.assertRaisesRegex(TARGET.TransactionError, code):
                TARGET.render_spec("demo", value, "192.168.1.153")

    def test_rejects_inline_secret_and_unlisted_compose_keys(self) -> None:
        value = valid_spec()
        value["services"]["hello"]["environment"] = {"API_TOKEN": "value"}
        with self.assertRaisesRegex(TARGET.TransactionError, "sensitive-environment-denied"):
            TARGET.render_spec("demo", value, "192.168.1.153")
        value = valid_spec()
        value["services"]["hello"]["privileged"] = True
        with self.assertRaisesRegex(TARGET.TransactionError, "invalid-service"):
            TARGET.render_spec("demo", value, "192.168.1.153")

    def test_named_volumes_cannot_become_host_binds(self) -> None:
        value = valid_spec()
        value["services"]["hello"]["volumes"][0]["name"] = "/var/run/docker.sock"
        with self.assertRaisesRegex(TARGET.TransactionError, "invalid-volumes"):
            TARGET.render_spec("demo", value, "192.168.1.153")

    def test_plan_validates_compose_without_persistent_stack_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(TARGET, "ROOT", Path(directory) / "stacks"), mock.patch.object(TARGET, "RUNTIME", Path(directory)), mock.patch.object(TARGET, "current_spec", return_value=None), mock.patch.object(TARGET, "validate_candidate") as validate:
                result = TARGET.plan("demo", valid_spec(), {"host": "docker-vm", "lanAddress": "192.168.1.153"})
            self.assertEqual(result["outcome"], "create")
            validate.assert_called_once()
            self.assertFalse((Path(directory) / "stacks" / "demo").exists())

    def test_apply_noop_never_invokes_docker(self) -> None:
        value = valid_spec()
        with mock.patch.object(TARGET, "recover_interrupted"), mock.patch.object(TARGET, "current_spec", return_value=value), mock.patch.object(TARGET, "run") as run, mock.patch.object(TARGET, "audit"):
            result = TARGET.apply("demo", value, {"host": "docker-vm", "lanAddress": "192.168.1.153"})
        self.assertEqual(result["outcome"], "noop")
        run.assert_not_called()

    def test_request_shapes_are_exact(self) -> None:
        with self.assertRaisesRegex(TARGET.TransactionError, "invalid-request"):
            TARGET.handle({"schemaVersion": 1, "action": "remove", "stack": "demo", "force": True})
        with self.assertRaisesRegex(TARGET.TransactionError, "invalid-request"):
            TARGET.handle({"schemaVersion": 1, "action": "apply", "stack": "demo"})

    def test_read_only_status_does_not_create_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "absent"
            with mock.patch.object(TARGET, "ROOT", root):
                result = TARGET.status(None, {"host": "docker-vm", "lanAddress": "192.168.1.153"})
            self.assertEqual(result["stacks"], [])
            self.assertFalse(root.exists())

    def test_status_rejects_linked_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "target"
            target.mkdir(mode=0o700)
            linked = parent / "linked"
            linked.symlink_to(target, target_is_directory=True)
            with mock.patch.object(TARGET, "ROOT", linked), self.assertRaisesRegex(TARGET.TransactionError, "state-root-invalid"):
                TARGET.status(None, {"host": "docker-vm", "lanAddress": "192.168.1.153"})

    def test_stack_state_requires_private_root_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "stacks"
            root.mkdir(mode=0o755)
            with mock.patch.object(TARGET, "ROOT", root), self.assertRaisesRegex(TARGET.TransactionError, "state-root-invalid"):
                TARGET.current_spec("demo")

    def test_mutations_recover_interrupted_transaction_first(self) -> None:
        value = valid_spec()
        with mock.patch.object(TARGET, "recover_interrupted") as recover, mock.patch.object(TARGET, "current_spec", return_value=value), mock.patch.object(TARGET, "audit"):
            TARGET.apply("demo", value, {"host": "docker-vm", "lanAddress": "192.168.1.153"})
        recover.assert_called_once()

    def test_source_has_no_shell_or_volume_deletion_path(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn('"-v"', source)
        self.assertNotIn('"--volumes"', source)
        self.assertNotIn("/var/run/docker.sock", source)


if __name__ == "__main__":
    unittest.main()
