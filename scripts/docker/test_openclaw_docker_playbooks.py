#!/usr/bin/python3
"""Static regression tests for the agent Docker access playbooks."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPORT_PLAYBOOK = ROOT / "playbooks/docker/agent-docker-report.yml"
BROKER_PLAYBOOK = ROOT / "playbooks/docker/openclaw-docker-update-broker.yml"
BROKER_VARS = (
    ROOT / "inventory/group_vars/docker_hosts/openclaw-docker-update-broker.yml"
)
BROKER_MANIFEST = ROOT / "templates/docker/openclaw-docker-update-manifest.json.j2"
REPORT_VARS = ROOT / "inventory/group_vars/docker_hosts/agent-docker-report.yml"


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
    def test_broker_manifest_schema_matches_runtime(self) -> None:
        template = BROKER_MANIFEST.read_text(encoding="utf-8")
        self.assertIn('"schemaVersion": 2', template)
        self.assertNotIn('"schemaVersion": 1', template)
        runtime = (ROOT / "scripts/docker/openclaw-docker-update-broker.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SCHEMA_VERSION = 2", runtime)

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

    def test_forced_command_accounts_have_locked_passwords(self) -> None:
        cases = (
            (REPORT_PLAYBOOK, "Create Agent Docker report account"),
            (
                BROKER_PLAYBOOK,
                "Create OpenClaw Docker update request account",
            ),
        )
        for path, task_name in cases:
            with self.subTest(path=path.name):
                task = task_named(load_tasks(path), task_name)
                user = task["ansible.builtin.user"]
                self.assertIs(user["password_lock"], True)
                self.assertNotIn("password", user)

    def test_both_boundaries_require_explicit_rollout_approval(self) -> None:
        report_inventory = yaml.safe_load(REPORT_VARS.read_text(encoding="utf-8"))
        broker_inventory = yaml.safe_load(BROKER_VARS.read_text(encoding="utf-8"))
        self.assertIs(report_inventory["agent_docker_report_enabled"], False)
        self.assertIs(report_inventory["agent_docker_report_rollout_approved"], False)
        self.assertIs(broker_inventory["openclaw_docker_update_broker_enabled"], False)
        self.assertIs(
            broker_inventory["openclaw_docker_update_broker_rollout_approved"],
            False,
        )

    def test_forced_command_accounts_are_checked_for_supplementary_groups(
        self,
    ) -> None:
        cases = (
            (
                REPORT_PLAYBOOK,
                "Require isolated Agent Docker report account groups",
            ),
            (
                BROKER_PLAYBOOK,
                "Require isolated OpenClaw Docker update request account groups",
            ),
        )
        for path, task_name in cases:
            with self.subTest(path=path.name):
                task = task_named(load_tasks(path), task_name)
                assertions = "\n".join(task["ansible.builtin.assert"]["that"])
                self.assertIn("stdout.split()", assertions)

    def test_source_cidrs_use_python_ipaddress_strict_parsing(self) -> None:
        cases = (
            (
                REPORT_PLAYBOOK,
                "Parse Agent Docker report source CIDRs exactly",
            ),
            (
                BROKER_PLAYBOOK,
                "Parse OpenClaw Docker update source CIDRs exactly",
            ),
        )
        for path, task_name in cases:
            with self.subTest(path=path.name):
                task = task_named(load_tasks(path), task_name)
                argv = task["ansible.builtin.command"]["argv"]
                self.assertEqual(argv[0], "/usr/bin/python3")
                self.assertIn("ipaddress.ip_network", argv[2])
                self.assertIn("strict=True", argv[2])
                self.assertIs(task["check_mode"], False)

    def test_update_targets_are_stateless_only(self) -> None:
        task = task_named(
            load_tasks(BROKER_PLAYBOOK),
            "Validate OpenClaw Docker update target IDs",
        )
        assertions = "\n".join(task["ansible.builtin.assert"]["that"])
        self.assertIn("item.value.updateClass == 'stateless-image'", assertions)
        self.assertIn("item.value.recreateServices == [item.value.service]", assertions)
        self.assertIn("item.value.verifyServices == [item.value.service]", assertions)
        inventory = BROKER_VARS.read_text(encoding="utf-8")
        self.assertIn("updateClass: stateless-image", inventory)
        self.assertIn("Stateful services require", inventory)

    def test_broker_uses_isolated_docker_client_configuration(self) -> None:
        source = (ROOT / "scripts/docker/openclaw-docker-update-broker.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"DOCKER_CONFIG": "/etc/openclaw-docker-update/docker-client"', source
        )
        playbook = BROKER_PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn(
            "openclaw_docker_update_broker_config_dir }}/docker-client", playbook
        )

    def test_disabled_reporter_stops_both_units_without_timer_probe(self) -> None:
        tasks = load_tasks(REPORT_PLAYBOOK)
        task = task_named(
            tasks,
            "Stop and disable Agent Docker report units when disabled",
        )
        self.assertEqual(
            task["loop"],
            [
                "agent-docker-report.timer",
                "agent-docker-report.service",
                "openclaw-docker-report.timer",
                "openclaw-docker-report.service",
            ],
        )
        self.assertFalse(
            any(
                item.get("name") == "Check for an existing Agent Docker report timer"
                for item in tasks
            )
        )

    def test_enabled_rollouts_back_up_prior_managed_artifacts(self) -> None:
        cases = (
            (
                REPORT_PLAYBOOK,
                "Back up prior Agent Docker report artifacts",
                "Create Agent Docker report group",
            ),
            (
                BROKER_PLAYBOOK,
                "Back up prior OpenClaw Docker update broker artifacts",
                "Create OpenClaw Docker update group",
            ),
        )
        for path, backup_name, first_mutation_name in cases:
            with self.subTest(path=path.name):
                tasks = load_tasks(path)
                backup_index = next(
                    index
                    for index, task in enumerate(tasks)
                    if task.get("name") == backup_name
                )
                mutation_index = next(
                    index
                    for index, task in enumerate(tasks)
                    if task.get("name") == first_mutation_name
                )
                self.assertLess(backup_index, mutation_index)
                backup = tasks[backup_index]
                argv = backup["ansible.builtin.command"]["argv"]
                self.assertIn("backup_argv", argv)
                self.assertIn("not ansible_check_mode", backup["when"])

    def test_rollout_backups_reject_existing_symlinks(self) -> None:
        cases = (
            (
                REPORT_PLAYBOOK,
                "Reject symlinked Agent Docker report artifacts",
            ),
            (
                BROKER_PLAYBOOK,
                "Reject symlinked OpenClaw Docker update broker artifacts",
            ),
        )
        for path, task_name in cases:
            with self.subTest(path=path.name):
                task = task_named(load_tasks(path), task_name)
                assertions = "\n".join(task["ansible.builtin.assert"]["that"])
                self.assertIn("islnk", assertions)

    def test_reporter_migrates_legacy_artifacts_only_after_validation(self) -> None:
        tasks = load_tasks(REPORT_PLAYBOOK)
        validate_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name") == "Generate and validate the initial redacted report"
        )
        enable_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name") == "Enable and start Agent Docker report timer"
        )
        remove_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name")
            == "Remove validated legacy OpenClaw Docker report artifacts"
        )
        self.assertLess(validate_index, enable_index)
        self.assertLess(enable_index, remove_index)
        remove = tasks[remove_index]
        self.assertEqual(remove["loop"], "{{ agent_docker_report_legacy_artifacts }}")
        self.assertIn("not ansible_check_mode", remove["when"])

    def test_report_account_never_joins_docker_group(self) -> None:
        task = task_named(
            load_tasks(REPORT_PLAYBOOK), "Create Agent Docker report account"
        )
        account = task["ansible.builtin.user"]
        self.assertEqual(account["groups"], "")
        self.assertIs(account["append"], False)
        self.assertNotEqual(account["group"], "docker")


if __name__ == "__main__":
    unittest.main()
