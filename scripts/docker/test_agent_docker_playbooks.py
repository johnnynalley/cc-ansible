#!/usr/bin/python3
"""Static regressions for the agent Docker access playbooks."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPORT_PLAYBOOK = ROOT / "playbooks/docker/agent-docker-report.yml"
TRIGGER_PLAYBOOK = ROOT / "playbooks/docker/agent-docker-update-trigger.yml"
REPORT_VARS = ROOT / "inventory/group_vars/docker_hosts/agent-docker-report.yml"
TRIGGER_VARS = (
    ROOT / "inventory/group_vars/docker_hosts/agent-docker-update-trigger.yml"
)
AUTO_UPDATE_PLAYBOOK = ROOT / "playbooks/docker/docker-auto-update.yml"
SOCKET_PROXY_HOST_VARS = (
    ROOT / "inventory/host_vars/docker-vm/docker.yml",
    ROOT / "inventory/host_vars/media-vm/docker.yml",
    ROOT / "inventory/host_vars/nextcloud-vm/docker.yml",
)


def load_tasks(path: Path) -> list[dict[str, Any]]:
    plays = yaml.safe_load(path.read_text(encoding="utf-8"))
    return plays[0]["tasks"]


def task_named(tasks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for task in tasks:
        if task.get("name") == name:
            return task
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if isinstance(nested, list):
                try:
                    return task_named(nested, name)
                except StopIteration:
                    pass
    raise StopIteration(name)


class DockerAccessPlaybookTests(unittest.TestCase):
    def test_report_schema_matches_runtime_and_playbook(self) -> None:
        runtime = (ROOT / "scripts/docker/agent-docker-report.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SCHEMA_VERSION = 2", runtime)
        task = task_named(
            load_tasks(REPORT_PLAYBOOK),
            "Validate generated Agent Docker report schema",
        )
        argv = task["ansible.builtin.command"]["argv"]
        self.assertIn("schemaVersion", argv[2])
        self.assertIn("== 2", argv[2])

    def test_reporter_uses_managed_inventory_identity(self) -> None:
        self.assertIn(
            "--host {{ inventory_hostname }}",
            REPORT_PLAYBOOK.read_text(encoding="utf-8"),
        )

    def test_forced_command_accounts_have_locked_passwords(self) -> None:
        cases = (
            (REPORT_PLAYBOOK, "Create Agent Docker report account"),
            (TRIGGER_PLAYBOOK, "Create Docker update trigger account"),
        )
        for path, task_name in cases:
            with self.subTest(path=path.name):
                user = task_named(load_tasks(path), task_name)["ansible.builtin.user"]
                self.assertIs(user["password_lock"], True)
                self.assertNotIn("password", user)

    def test_trigger_shell_is_usable_only_behind_forced_key(self) -> None:
        tasks = load_tasks(TRIGGER_PLAYBOOK)
        user = task_named(tasks, "Create Docker update trigger account")[
            "ansible.builtin.user"
        ]
        key = task_named(tasks, "Install forced-command Docker update trigger key")[
            "ansible.builtin.copy"
        ]["content"]
        self.assertEqual(user["shell"], "/bin/sh")
        self.assertIn("restrict,command=", key)
        self.assertIn('from="', key)
        self.assertNotIn("{{ lookup(", key)

    def test_both_boundaries_require_explicit_rollout_approval(self) -> None:
        report = yaml.safe_load(REPORT_VARS.read_text(encoding="utf-8"))
        trigger = yaml.safe_load(TRIGGER_VARS.read_text(encoding="utf-8"))
        self.assertTrue(report["agent_docker_report_enabled"])
        self.assertTrue(report["agent_docker_report_rollout_approved"])
        self.assertEqual(len(report["agent_docker_report_authorized_keys"]), 1)
        self.assertEqual(report["agent_docker_report_source_cidrs"], ["192.168.1.31/32"])
        self.assertTrue(trigger["agent_docker_update_trigger_rollout_approved"])
        self.assertEqual(len(trigger["agent_docker_update_trigger_authorized_keys"]), 1)
        self.assertEqual(
            trigger["agent_docker_update_trigger_source_cidrs"],
            ["192.168.1.31/32"],
        )

    def test_forced_command_accounts_are_group_isolated(self) -> None:
        cases = (
            (
                REPORT_PLAYBOOK,
                "Require isolated Agent Docker report account groups",
            ),
            (TRIGGER_PLAYBOOK, "Verify Docker update trigger has no supplementary groups"),
        )
        for path, task_name in cases:
            assertions = "\n".join(
                task_named(load_tasks(path), task_name)["ansible.builtin.assert"]["that"]
            )
            self.assertIn("stdout.split()", assertions)

    def test_trigger_accepts_no_target_or_command_from_agent(self) -> None:
        playbook = TRIGGER_PLAYBOOK.read_text(encoding="utf-8")
        source = (ROOT / "scripts/docker/agent-docker-update-trigger.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("docker-auto-update.service", source)
        self.assertIn('set(value) != {"schemaVersion", "action"}', source)
        self.assertNotIn("docker compose", source)
        self.assertNotIn("/var/run/docker.sock", source)
        self.assertIn("--cooldown", playbook)
        sudo_content = task_named(
            load_tasks(TRIGGER_PLAYBOOK),
            "Install exact Docker update trigger sudo rule",
        )["ansible.builtin.copy"]["content"]
        self.assertIn("ALL=(root) NOPASSWD", sudo_content)
        self.assertIn("agent_docker_update_trigger_exact_command", sudo_content)

    def test_update_trigger_backups_precede_account_mutation(self) -> None:
        tasks = load_tasks(TRIGGER_PLAYBOOK)
        backup = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name") == "Back up prior Docker update trigger artifacts"
        )
        mutation = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name") == "Create Docker update trigger group"
        )
        self.assertLess(backup, mutation)

    def test_trigger_python_validation_writes_no_bytecode(self) -> None:
        validate = task_named(load_tasks(TRIGGER_PLAYBOOK), "Deploy fixed Docker update trigger")[
            "ansible.builtin.copy"
        ]["validate"]
        self.assertIn("ast.parse", validate)
        self.assertNotIn("py_compile", validate)

    def test_report_backup_roots_are_narrowly_allowlisted(self) -> None:
        playbook = REPORT_PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("'/srv/live-rollbacks'", playbook)
        self.assertIn("'/var/backups/agent-docker-access'", playbook)

    def test_credential_bearing_updater_is_root_only(self) -> None:
        task = task_named(
            load_tasks(AUTO_UPDATE_PLAYBOOK),
            "Create docker-auto-update script",
        )["ansible.builtin.template"]
        self.assertEqual(task["owner"], "root")
        self.assertEqual(task["group"], "root")
        self.assertEqual(task["mode"], "0700")

    def test_socket_proxy_is_never_blind_auto_updated(self) -> None:
        for path in SOCKET_PROXY_HOST_VARS:
            with self.subTest(path=path.name):
                stacks = yaml.safe_load(path.read_text(encoding="utf-8"))[
                    "docker_stacks"
                ]
                proxy = next(
                    stack for stack in stacks if stack["name"] == "docker-socket-proxy"
                )
                self.assertIs(proxy.get("auto_update"), False)
                self.assertNotIn("auto_update_services", proxy)


if __name__ == "__main__":
    unittest.main()
