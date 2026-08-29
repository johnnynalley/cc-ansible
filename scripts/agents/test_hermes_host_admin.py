#!/usr/bin/env python3
"""Focused regressions for Astra's bounded host administration boundary."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = ROOT / "scripts/agents/hermes-host-admin-target.py"
PLUGIN_PATH = ROOT / "files/hermes/plugins/host-admin/__init__.py"
PLAYBOOK = ROOT / "playbooks/agents/hermes-host-admin.yml"
HARDENING = ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
VARS = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"
SHARED_VARS = ROOT / "inventory/group_vars/all/hermes-host-admin.yml"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TARGET = load("hermes_host_admin_target", TARGET_PATH)
PLUGIN = load("hermes_host_admin_plugin", PLUGIN_PATH)


class Context:
    def __init__(self) -> None:
        self.hooks = []
        self.tools = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class HostAdminTests(unittest.TestCase):
    def test_target_rejects_unknown_fields_and_protected_services(self) -> None:
        with self.assertRaisesRegex(TARGET.AdminError, "invalid-request"):
            TARGET.handle({"schemaVersion": 1, "action": "status", "command": "id"})
        with self.assertRaisesRegex(TARGET.AdminError, "protected-service"):
            TARGET.handle({"schemaVersion": 1, "action": "service-restart", "service": "sshd.service"})
        with self.assertRaisesRegex(TARGET.AdminError, "protected-service"):
            TARGET.handle({"schemaVersion": 1, "action": "service-stop", "service": "hermes-gateway-astra.service"})
        with self.assertRaisesRegex(TARGET.AdminError, "invalid-probe"):
            TARGET.handle({"schemaVersion": 1, "action": "health", "probe": "shell"})

    def test_health_probes_are_typed_read_only_and_host_scoped(self) -> None:
        with mock.patch.object(TARGET, "canonical_host", return_value="docker-vm"), mock.patch.object(TARGET.Path, "is_file", return_value=True), mock.patch.object(TARGET, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="OK: healthy\n")
            body = TARGET.health_probe({"probe": "media-stack"})
        self.assertEqual(body["probe"], "media-stack")
        self.assertEqual(body["output"], ["OK: healthy"])
        command = run.call_args.args[0]
        self.assertEqual(command, ["/usr/local/sbin/media-stack-health", "--status"])
        with mock.patch.object(TARGET, "canonical_host", return_value="media-vm"):
            with self.assertRaisesRegex(TARGET.AdminError, "probe-unavailable"):
                TARGET.health_probe({"probe": "media-stack"})

    def test_media_storage_view_probe_is_host_scoped_and_bounded(self) -> None:
        layered_mount = json.dumps(
            {
                "filesystems": [
                    {
                        "target": "/srv/media",
                        "fstype": "autofs",
                        "children": [
                            {"target": "/srv/media", "fstype": "nfs4"}
                        ],
                    }
                ]
            }
        )
        incomplete_mount = json.dumps(
            {
                "filesystems": [
                    {
                        "target": "/srv/incomplete_downloads",
                        "fstype": "autofs",
                        "children": [
                            {
                                "target": "/srv/incomplete_downloads",
                                "fstype": "nfs4",
                            }
                        ],
                    }
                ]
            }
        )
        results = [
            mock.Mock(returncode=0, stdout=layered_mount),
            mock.Mock(returncode=0, stdout=incomplete_mount),
            mock.Mock(returncode=0, stdout="/srv/media/plex/Movies/example\n"),
            mock.Mock(returncode=0, stdout=""),
        ]
        with mock.patch.object(
            TARGET, "canonical_host", return_value="docker-vm"
        ), mock.patch.object(TARGET, "run", side_effect=results) as run:
            body = TARGET.health_probe({"probe": "media-storage-view"})
        self.assertEqual(body["probe"], "media-storage-view")
        self.assertEqual(body["exitCode"], 0)
        self.assertIn("/srv/media=nfs4", body["output"])
        self.assertEqual(run.call_count, 4)
        for call in run.call_args_list:
            self.assertNotIn("/bin/sh", call.args[0])
            self.assertNotIn("/bin/bash", call.args[0])

        with mock.patch.object(TARGET, "canonical_host", return_value="media-vm"):
            with self.assertRaisesRegex(TARGET.AdminError, "probe-unavailable"):
                TARGET.health_probe({"probe": "media-storage-view"})

    def test_mount_fstype_requires_one_concrete_leaf(self) -> None:
        single = json.dumps(
            {"filesystems": [{"target": "/srv/media", "fstype": "nfs4"}]}
        )
        with mock.patch.object(
            TARGET, "run", return_value=mock.Mock(returncode=0, stdout=single)
        ):
            self.assertEqual(TARGET._mount_fstype("/srv/media"), "nfs4")

        for payload in (
            "not-json",
            json.dumps({"filesystems": []}),
            json.dumps(
                {
                    "filesystems": [
                        {"target": "/srv/media", "fstype": "autofs"}
                    ]
                }
            ),
        ):
            with self.subTest(payload=payload), mock.patch.object(
                TARGET,
                "run",
                return_value=mock.Mock(returncode=0, stdout=payload),
            ), self.assertRaisesRegex(
                TARGET.AdminError, "storage-view-unavailable"
            ):
                TARGET._mount_fstype("/srv/media")

    def test_target_uses_only_root_managed_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = Path(directory) / "identity.json"
            identity.write_text('{"schemaVersion":1,"host":"docker-vm"}', encoding="ascii")
            identity.chmod(0o444)
            original = TARGET.IDENTITY
            TARGET.IDENTITY = identity
            try:
                real = TARGET.os.lstat(identity)
                trusted = mock.Mock(
                    st_mode=real.st_mode,
                    st_uid=0,
                    st_size=real.st_size,
                )
                with mock.patch.object(TARGET.os, "lstat", return_value=trusted):
                    self.assertEqual(TARGET.canonical_host(), "docker-vm")
                trusted.st_uid = 1000
                with mock.patch.object(TARGET.os, "lstat", return_value=trusted):
                    with self.assertRaisesRegex(TARGET.AdminError, "identity-invalid"):
                        TARGET.canonical_host()
            finally:
                TARGET.IDENTITY = original

    def test_proxmox_quorum_blocks_unsafe_reboot(self) -> None:
        result = mock.Mock(returncode=0, stdout="Quorate: Yes\nTotal votes: 2\nQuorum: 2\n")
        with mock.patch.object(TARGET.shutil, "which", return_value="/usr/bin/pvecm"), mock.patch.object(TARGET, "run", return_value=result):
            with self.assertRaisesRegex(TARGET.AdminError, "quorum-blocked"):
                TARGET.proxmox_reboot_guard()

    def test_plugin_manifest_is_dynamic_and_rejects_duplicate_hosts(self) -> None:
        value = {"schemaVersion": 1, "hosts": [{"name": "docker-vm", "address": "192.168.1.153"}]}
        self.assertEqual(PLUGIN._load_hosts.__name__, "_load_hosts")
        with self.assertRaisesRegex(PLUGIN.HostAdminError, "invalid-response"):
            PLUGIN._validate_body({"apiKey": "leak"})
        duplicate = {**value, "hosts": value["hosts"] * 2}
        with self.assertRaisesRegex(PLUGIN.HostAdminError, "invalid-endpoints"):
            PLUGIN._validate_host_data(duplicate)
        value["hosts"][0]["address"] = "100.108.254.100"
        with self.assertRaisesRegex(PLUGIN.HostAdminError, "invalid-endpoints"):
            PLUGIN._validate_host_data(value)

    def test_plugin_registers_typed_tools_and_turn_bound_mutation_approval(self) -> None:
        context = Context()
        PLUGIN.register(context)
        self.assertEqual([item[0] for item in context.hooks], ["pre_tool_call"])
        self.assertEqual([item["name"] for item in context.tools], ["host_admin_hosts", "host_admin_request"])
        self.assertEqual({item["toolset"] for item in context.tools}, {"host_admin"})
        hook = context.hooks[0][1]
        self.assertIsNone(hook("host_admin_request", {"action": "status"}, turn_id="turn-1"))
        self.assertIsNone(hook("host_admin_request", {"action": "health"}, turn_id="turn-1"))
        approval = hook("host_admin_request", {"host": "docker-vm", "action": "update"}, turn_id="turn-1")
        self.assertEqual(approval["action"], "approve")
        self.assertEqual(approval["rule_key"], "host-admin:turn-1")
        self.assertEqual(hook("host_admin_request", {"action": "reboot"}, turn_id="")["action"], "block")

    def test_plugin_ssh_has_no_remote_command_or_forwarding(self) -> None:
        with mock.patch.object(PLUGIN, "_load_hosts", return_value={"docker-vm": "192.168.1.153"}), mock.patch.object(PLUGIN, "_credential", return_value=Path("/credential")), mock.patch.object(PLUGIN.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"schemaVersion": 1, "status": "ok", "host": "docker-vm", "action": "status", "body": {}}).encode())
            PLUGIN._call("docker-vm", "status")
            command = run.call_args.args[0]
        self.assertIn("ClearAllForwardings=yes", command)
        self.assertEqual(command[-1], "agent-host-admin@192.168.1.153")
        self.assertNotIn("sudo", command)
        self.assertNotIn("systemctl", command)

    def test_plugin_requires_known_probe_only_for_health(self) -> None:
        self.assertEqual(
            json.loads(PLUGIN._handle_request({"host": "docker-vm", "action": "health"}))["code"],
            "invalid-request",
        )
        self.assertEqual(
            json.loads(PLUGIN._handle_request({"host": "docker-vm", "action": "status", "probe": "media-stack"}))["code"],
            "invalid-request",
        )
        with mock.patch.object(PLUGIN, "_call") as call:
            call.return_value = {
                "schemaVersion": 1,
                "status": "ok",
                "host": "docker-vm",
                "action": "health",
                "body": {"probe": "media-stack", "exitCode": 0, "output": [], "truncated": False},
            }
            value = json.loads(PLUGIN._handle_request({"host": "docker-vm", "action": "health", "probe": "media-stack"}))
        self.assertEqual(value["status"], "ok")
        call.assert_called_once_with("docker-vm", "health", None, "media-stack")
        self.assertIn("media-storage-view", PLUGIN._PROBES)

    def test_plugin_rejects_response_from_another_inventory_host(self) -> None:
        response = {
            "schemaVersion": 1,
            "status": "ok",
            "host": "media-vm",
            "action": "status",
            "body": {},
        }
        with mock.patch.object(PLUGIN, "_load_hosts", return_value={"docker-vm": "192.168.1.153"}), mock.patch.object(PLUGIN, "_credential", return_value=Path("/credential")), mock.patch.object(PLUGIN.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(response).encode())
            with self.assertRaisesRegex(PLUGIN.HostAdminError, "invalid-response"):
                PLUGIN._call("docker-vm", "status")

    def test_managed_sources_contain_no_secret_or_general_shell_boundary(self) -> None:
        for path in (TARGET_PATH, PLUGIN_PATH):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text)
            self.assertNotIn("GEMINI_API_KEY", text)
            self.assertNotIn("OPENAI_API_KEY", text)
        target = TARGET_PATH.read_text(encoding="utf-8")
        self.assertNotIn("os.system", target)
        self.assertNotIn("subprocess.Popen", target)

    def test_playbook_and_gateway_contract(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        hardening = HARDENING.read_text(encoding="utf-8")
        variables = VARS.read_text(encoding="utf-8")
        shared_variables = SHARED_VARS.read_text(encoding="utf-8")
        self.assertIn("hermes_host_admin_mode: disabled", shared_variables)
        self.assertIn("hermes_host_admin_defer_gateway_restart: false", shared_variables)
        self.assertIn("enable-bounded-host-admin-for-hermes-astra", shared_variables)
        self.assertNotIn("hermes_host_admin_mode: disabled", variables)
        self.assertLess(playbook.index("Back up prior host-admin target paths"), playbook.index("Deploy root-owned host-admin target"))
        self.assertIn("Probe bounded target SSH reachability", playbook)
        self.assertIn("Leave offline target pending without repeated SSH retries", playbook)
        self.assertIn("Freeze one rollback identifier for this target transaction", playbook)
        self.assertIn("hermes_host_admin_target_transaction_id", playbook)
        self.assertIn("Deploy root-owned canonical host-admin identity", playbook)
        self.assertIn("hermes_host_admin_target_identity", playbook)
        self.assertIn("Discover the target LAN endpoint", playbook)
        self.assertIn("Require the target endpoint on the managed LAN", playbook)
        self.assertIn("Stop after target read-only check-mode preflight\n      ansible.builtin.meta: end_host", playbook)
        self.assertIn("restrict,command=", playbook)
        self.assertIn('NOPASSWD: {{ hermes_host_admin_target_live }} ""', playbook)
        self.assertNotIn("requiretty", playbook)
        self.assertNotIn("NOPASSWD: ALL", playbook)
        self.assertIn("LoadCredential=agent-host-admin-key", hardening)
        self.assertNotIn("docker.sock", hardening)
        self.assertIn("not hermes_host_admin_defer_gateway_restart | bool", playbook)
        self.assertIn("restartDeferred", playbook)


if __name__ == "__main__":
    unittest.main()
