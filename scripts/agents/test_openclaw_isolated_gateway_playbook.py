#!/usr/bin/env python3

from __future__ import annotations

import unittest
import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

PLAYBOOK_PATH = (
    Path(__file__).parents[2] / "playbooks/agents/openclaw-isolated-gateway.yml"
)
CONFIG_TEMPLATE_PATH = (
    Path(__file__).parents[2] / "templates/openclaw/openclaw-isolated.json.j2"
)
SERVICE_TEMPLATE_PATH = (
    Path(__file__).parents[2]
    / "templates/openclaw/openclaw-isolated-gateway.service.j2"
)
CODEX_SERVICE_TEMPLATE_PATH = (
    Path(__file__).parents[2] / "templates/openclaw/openclaw-isolated-codex.service.j2"
)
INVENTORY_PATH = (
    Path(__file__).parents[2] / "inventory/host_vars/jn-t14s-lin/openclaw.yml"
)


class IsolatedGatewayPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        cls.config_template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.service_template = SERVICE_TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.codex_service_template = CODEX_SERVICE_TEMPLATE_PATH.read_text(
            encoding="utf-8"
        )
        cls.inventory = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))

    def task(self, name: str) -> str:
        start = self.playbook.index(f"- name: {name}")
        end = self.playbook.find("\n        - name:", start + 1)
        if end == -1:
            end = len(self.playbook)
        return self.playbook[start:end]

    def test_release_permissions_converge_without_symlink_traversal(self) -> None:
        task = self.task("Converge promoted isolated release ownership and access")
        self.assertIn("owner: root", task)
        self.assertIn("group: root", task)
        self.assertIn("mode: u=rwX,go=rX", task)
        self.assertIn("recurse: true", task)
        self.assertIn("follow: false", task)

    def test_service_identity_executes_selected_runtime_before_restart(self) -> None:
        probe = self.playbook.index(
            "- name: Prove isolated service identity can execute selected runtime"
        )
        validate = self.playbook.index(
            "- name: Validate isolated Gateway configuration"
        )
        restart = self.playbook.index(
            "- name: Restart isolated Gateway from converged immutable release"
        )
        self.assertLess(probe, validate)
        self.assertLess(validate, restart)
        self.assertIn(
            "state: restarted",
            self.task("Restart isolated Gateway from converged immutable release"),
        )

    def test_local_targeted_backup_precedes_build(self) -> None:
        mount = self.playbook.index(
            "- name: Require local writable rollback filesystem"
        )
        capacity = self.playbook.index(
            "- name: Require rollback and build capacity before mutation"
        )
        backup = self.playbook.index(
            "- name: Create consistent isolated Gateway rollback artifact"
        )
        build = self.playbook.index(
            "- name: Build isolated OpenClaw runtime from stable channel"
        )
        self.assertLess(mount, capacity)
        self.assertLess(capacity, backup)
        self.assertLess(backup, build)
        self.assertIn("/var/backups/openclaw-isolated", self.playbook)
        mount_probe = self.task("Inspect isolated Gateway rollback filesystem")
        self.assertIn("--first-only", mount_probe)
        self.assertIn("TARGET,FSTYPE,OPTIONS", mount_probe)
        self.assertNotIn("nfs,nfs4", mount_probe)
        archive = self.task("Back up existing isolated Gateway state")
        self.assertIn("--exclude=var/lib/openclaw-isolated/.npm", archive)
        self.assertIn("--exclude=var/lib/openclaw-isolated/compile-cache", archive)
        rollback_cleanup = self.task(
            "Remove failed isolated Gateway managed paths before rollback"
        )
        self.assertIn("openclaw_isolated_gateway_runtime_dir", rollback_cleanup)
        self.assertNotIn(
            '"{{ openclaw_isolated_gateway_runtime_root }}"', rollback_cleanup
        )
        release_cleanup = self.task("Remove unverified newly built isolated release")
        self.assertIn("openclaw_isolated_gateway_release_verified", release_cleanup)

    def test_check_mode_stops_after_preflight_and_before_mutation(self) -> None:
        capacity = self.playbook.index(
            "- name: Require rollback and build capacity before mutation"
        )
        boundary = self.playbook.index(
            "- name: End isolated Gateway check-mode validation before mutation"
        )
        timestamp = self.playbook.index("- name: Set isolated Gateway backup timestamp")
        accounts = self.playbook.index("- name: Create isolated Gateway group")
        self.assertLess(capacity, boundary)
        self.assertLess(boundary, timestamp)
        self.assertLess(boundary, accounts)
        boundary_task = self.playbook[
            boundary : self.playbook.index("\n    - name:", boundary + 1)
        ]
        self.assertIn("ansible.builtin.meta: end_host", boundary_task)
        self.assertIn("when: ansible_check_mode", boundary_task)

    def test_plugins_use_native_install_records_not_path_injection(self) -> None:
        self.assertNotIn('"load": {', self.config_template)
        self.assertNotIn("Create read-only managed-plugin sentinel", self.playbook)
        self.assertNotIn("Stage new isolated managed plugin releases", self.playbook)
        install = self.task(
            "Install exact plugins through OpenClaw native ownership transaction"
        )
        self.assertIn("'plugins', 'install'", install)
        self.assertIn("'npm:' + item.package.name", install)
        self.assertIn("'--pin'", install)
        provenance = self.task(
            "Require native plugin provenance and exact selected packages"
        )
        self.assertIn("installRecords", provenance)
        self.assertIn("integrity", provenance)
        trust_inspect = self.task("Inspect managed plugin trust classifications")
        self.assertIn("'plugins', 'inspect'", trust_inspect)
        trust_gate = self.task("Require exact managed plugin trust classifications")
        self.assertIn("trustedOfficialInstall", trust_gate)
        self.assertIn("convergence_status", trust_gate)
        final_registry_gate = self.task(
            "Require one compatible root-managed Codex provider"
        )
        self.assertNotIn("trustedOfficialInstall", final_registry_gate)

    def test_plugin_status_and_trust_policy_is_explicit(self) -> None:
        plugins = {
            plugin["id"]: plugin
            for plugin in self.inventory["openclaw_isolated_gateway_managed_plugins"]
        }
        self.assertEqual(
            {
                "codex": (True, "loaded"),
                "discord": (True, "loaded"),
                "lossless-claw": (False, "loaded"),
                "openclaw-mem0": (False, "disabled"),
            },
            {
                plugin_id: (
                    plugin["trusted_official"],
                    plugin["convergence_status"],
                )
                for plugin_id, plugin in plugins.items()
            },
        )

    def test_runtime_registration_is_a_pre_model_cutover_gate(self) -> None:
        restart = self.playbook.index(
            "- name: Restart isolated Gateway from converged immutable release"
        )
        inspect_runtime = self.playbook.index(
            "- name: Inspect Codex runtime registration after startup"
        )
        require_runtime = self.playbook.index(
            "- name: Require trusted Codex runtime and durable ownership records"
        )
        model = self.playbook.index("- name: Run isolated Gateway model canary")
        self.assertLess(restart, inspect_runtime)
        self.assertLess(inspect_runtime, require_runtime)
        self.assertLess(require_runtime, model)
        runtime_task = self.task("Inspect Codex runtime registration after startup")
        self.assertIn("--runtime", runtime_task)
        startup_gate = self.task(
            "Require trusted Codex runtime and durable ownership records"
        )
        self.assertIn("trustedOfficialInstall", startup_gate)
        self.assertIn("installRecords", startup_gate)

    def test_model_probe_uses_real_agent_and_disposable_session(self) -> None:
        identity = self.playbook.index(
            "- name: Generate isolated Gateway model-probe identity"
        )
        model = self.playbook.index("- name: Run isolated Gateway model canary")
        self.assertLess(identity, model)
        task = self.task("Run isolated Gateway model canary")
        self.assertIn("- main", task)
        self.assertIn("agent:main:explicit:model-run-", task)
        self.assertNotIn("agent:canary:", task)

    def test_native_security_audits_gate_restart_and_model(self) -> None:
        secrets = self.playbook.index("- name: Audit isolated Gateway SecretRefs")
        static = self.playbook.index(
            "- name: Run static isolated Gateway security audit"
        )
        restart = self.playbook.index(
            "- name: Restart isolated Gateway from converged immutable release"
        )
        deep = self.playbook.index("- name: Run deep isolated Gateway security audit")
        model = self.playbook.index("- name: Run isolated Gateway model canary")
        self.assertLess(secrets, static)
        self.assertLess(static, restart)
        self.assertLess(restart, deep)
        self.assertLess(deep, model)

        secrets_task = self.task("Audit isolated Gateway SecretRefs")
        self.assertIn("- --check", secrets_task)
        self.assertNotIn("--allow-exec", secrets_task)

        for name in (
            "Run static isolated Gateway security audit",
            "Run deep isolated Gateway security audit",
        ):
            task = self.task(name)
            self.assertNotIn("--fix", task)
            self.assertNotIn("--token", task)
            self.assertNotIn("--password", task)
        self.assertIn("- --deep", self.task("Run deep isolated Gateway security audit"))

    def test_canary_disables_channels_and_scheduler(self) -> None:
        self.assertIn("Environment=OPENCLAW_SKIP_CHANNELS=1", self.service_template)
        self.assertIn("Environment=OPENCLAW_SKIP_CRON=1", self.service_template)
        self.assertIn('"every": "0m"', self.config_template)
        self.assertIn('"target": "none"', self.config_template)
        self.assertIs(self.inventory["openclaw_isolated_gateway_skip_cron"], True)

    def test_service_denies_privileged_syscall_classes(self) -> None:
        for template in (self.service_template, self.codex_service_template):
            self.assertIn(
                "SystemCallFilter=~@clock @cpu-emulation @debug @module @mount "
                "@obsolete @privileged @raw-io @reboot @swap",
                template,
            )
            self.assertIn("SystemCallErrorNumber=EPERM", template)

    def test_service_template_passes_systemd_verify(self) -> None:
        environment = Environment(undefined=StrictUndefined, autoescape=False)
        template = environment.from_string(self.service_template)
        rendered = template.render(
            openclaw_isolated_gateway_user="openclaw",
            openclaw_isolated_gateway_group="openclaw",
            openclaw_isolated_gateway_supplementary_groups=[
                "openclaw-runtime",
                "openclaw-workspace",
            ],
            openclaw_isolated_gateway_state_dir="/var/lib/openclaw-isolated",
            openclaw_isolated_gateway_config_file=(
                "/etc/openclaw-isolated/openclaw.json"
            ),
            openclaw_isolated_gateway_config_dir="/etc/openclaw-isolated",
            openclaw_isolated_gateway_secret_file=(
                "/etc/openclaw-isolated/secrets.json"
            ),
            openclaw_isolated_gateway_workspace_dir=(
                "/usr/local/share/openclaw-isolated/workspace"
            ),
            openclaw_isolated_gateway_runtime_dir=("/opt/openclaw-isolated/current"),
            openclaw_isolated_gateway_runtime_root="/opt/openclaw-isolated",
            openclaw_isolated_gateway_codex_plugin_dir=(
                "/var/lib/openclaw-isolated/state/npm/projects/codex"
            ),
            openclaw_isolated_gateway_port=19789,
            openclaw_isolated_codex_config_dir="/etc/openclaw-codex",
            openclaw_isolated_codex_state_dir="/var/lib/openclaw-codex",
            openclaw_isolated_gateway_legacy_user="johnny",
            openclaw_workspace="/opt/cc-ansible",
            openclaw_security_rehearsal_root=("/var/lib/openclaw-security-rehearsal"),
        )
        codex_template = environment.from_string(self.codex_service_template)
        codex_rendered = codex_template.render(
            openclaw_isolated_codex_user="openclaw-codex",
            openclaw_isolated_codex_group="openclaw-codex",
            openclaw_isolated_codex_supplementary_groups=[
                "openclaw-runtime",
                "openclaw-workspace",
            ],
            openclaw_isolated_codex_state_dir="/var/lib/openclaw-codex",
            openclaw_isolated_codex_config_dir="/etc/openclaw-codex",
            openclaw_isolated_codex_token_file=("/etc/openclaw-codex/app-server.token"),
            openclaw_isolated_codex_runtime_dir="/opt/openclaw-codex/runtime",
            openclaw_isolated_codex_port=19790,
            openclaw_isolated_gateway_codex_plugin_dir=(
                "/var/lib/openclaw-isolated/state/npm/projects/codex"
            ),
            openclaw_isolated_gateway_workspace_dir=(
                "/usr/local/share/openclaw-isolated/workspace"
            ),
            openclaw_isolated_gateway_secret_file=(
                "/etc/openclaw-isolated/secrets.json"
            ),
            openclaw_isolated_gateway_config_file=(
                "/etc/openclaw-isolated/openclaw.json"
            ),
            openclaw_isolated_gateway_config_dir="/etc/openclaw-isolated",
            openclaw_isolated_gateway_state_dir="/var/lib/openclaw-isolated",
            openclaw_isolated_gateway_legacy_user="johnny",
            openclaw_workspace="/opt/cc-ansible",
            openclaw_security_rehearsal_root=("/var/lib/openclaw-security-rehearsal"),
        )
        with tempfile.TemporaryDirectory() as directory_name:
            unit = Path(directory_name) / "openclaw-isolated-gateway.service"
            unit.write_text(rendered, encoding="utf-8")
            codex_unit = Path(directory_name) / "openclaw-isolated-codex.service"
            codex_unit.write_text(codex_rendered, encoding="utf-8")
            result = subprocess.run(
                [
                    "/usr/bin/systemd-analyze",
                    "verify",
                    str(unit),
                    str(codex_unit),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        sandbox_socket_errors = {
            "Failed to turn off SO_PASSRIGHTS on user lookup socket, ignoring: "
            "Operation not permitted",
            "Failed to enable SO_PASSCRED on handoff timestamp socket: "
            "Operation not permitted",
        }
        stderr_lines = {
            line.strip() for line in result.stderr.splitlines() if line.strip()
        }
        if result.returncode != 0 and stderr_lines == sandbox_socket_errors:
            self.skipTest("systemd-analyze host sockets blocked by test sandbox")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_codex_service_template_passes_systemd_verify(self) -> None:
        environment = Environment(undefined=StrictUndefined, autoescape=False)
        template = environment.from_string(self.codex_service_template)
        rendered = template.render(
            openclaw_isolated_codex_user="openclaw-codex",
            openclaw_isolated_codex_group="openclaw-codex",
            openclaw_isolated_codex_supplementary_groups=[
                "openclaw-runtime",
                "openclaw-workspace",
            ],
            openclaw_isolated_codex_state_dir="/var/lib/openclaw-codex",
            openclaw_isolated_codex_config_dir="/etc/openclaw-codex",
            openclaw_isolated_codex_token_file=("/etc/openclaw-codex/app-server.token"),
            openclaw_isolated_codex_runtime_dir="/opt/openclaw-codex/runtime",
            openclaw_isolated_codex_port=19790,
            openclaw_isolated_gateway_codex_plugin_dir=(
                "/var/lib/openclaw-isolated/state/npm/projects/codex"
            ),
            openclaw_isolated_gateway_workspace_dir=(
                "/usr/local/share/openclaw-isolated/workspace"
            ),
            openclaw_isolated_gateway_secret_file=(
                "/etc/openclaw-isolated/secrets.json"
            ),
            openclaw_isolated_gateway_config_file=(
                "/etc/openclaw-isolated/openclaw.json"
            ),
            openclaw_isolated_gateway_config_dir="/etc/openclaw-isolated",
            openclaw_isolated_gateway_state_dir="/var/lib/openclaw-isolated",
            openclaw_isolated_gateway_legacy_user="johnny",
            openclaw_workspace="/opt/cc-ansible",
            openclaw_security_rehearsal_root=("/var/lib/openclaw-security-rehearsal"),
        )
        with tempfile.TemporaryDirectory() as directory_name:
            unit = Path(directory_name) / "openclaw-isolated-codex.service"
            unit.write_text(rendered, encoding="utf-8")
            result = subprocess.run(
                ["/usr/bin/systemd-analyze", "verify", str(unit)],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        sandbox_socket_errors = {
            "Failed to turn off SO_PASSRIGHTS on user lookup socket, ignoring: "
            "Operation not permitted",
            "Failed to enable SO_PASSCRED on handoff timestamp socket: "
            "Operation not permitted",
        }
        stderr_lines = {
            line.strip() for line in result.stderr.splitlines() if line.strip()
        }
        if result.returncode != 0 and stderr_lines == sandbox_socket_errors:
            self.skipTest("systemd-analyze host sockets blocked by test sandbox")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_codex_is_a_separate_authenticated_loopback_executor(self) -> None:
        self.assertIn(
            "User={{ openclaw_isolated_codex_user }}", self.codex_service_template
        )
        self.assertIn("--listen ws://127.0.0.1:", self.codex_service_template)
        self.assertIn("--ws-auth capability-token", self.codex_service_template)
        self.assertIn("BindReadOnlyPaths=", self.codex_service_template)
        self.assertIn(
            "InaccessiblePaths=-{{ openclaw_isolated_gateway_config_dir }}",
            self.codex_service_template,
        )
        self.assertIn(
            "InaccessiblePaths=-{{ openclaw_security_rehearsal_root }}",
            self.codex_service_template,
        )
        self.assertIn('"transport": "websocket"', self.config_template)
        self.assertIn('"sandbox": "workspace-write"', self.config_template)

    def test_canary_uses_real_agent_topology_without_routes(self) -> None:
        rendered = self.config_template
        rendered = rendered.replace(
            "{{ openclaw_isolated_gateway_secret_file | to_json }}",
            '"/etc/openclaw-isolated/secrets.json"',
        )
        rendered = rendered.replace(
            "{{ openclaw_isolated_gateway_workspace_dir | to_json }}",
            '"/usr/local/share/openclaw-isolated/workspace"',
        )
        rendered = rendered.replace(
            "{{ openclaw_isolated_gateway_model | to_json }}",
            '"openai/gpt-5.6-sol"',
        )
        rendered = rendered.replace(
            "{{ openclaw_isolated_gateway_port | int }}", "19789"
        )
        rendered = rendered.replace(
            "{{ ('ws://127.0.0.1:' ~ (openclaw_isolated_codex_port | string)) | to_json }}",
            '"ws://127.0.0.1:19790"',
        )
        for agent in ("dubble", "vega", "antares", "rigel"):
            rendered = rendered.replace(
                "{{ (openclaw_isolated_gateway_workspace_dir ~ '/"
                + agent
                + "') | to_json }}",
                '"/usr/local/share/openclaw-isolated/workspace/' + agent + '"',
            )
        config = json.loads(rendered)
        self.assertEqual(
            [agent["id"] for agent in config["agents"]["list"]],
            ["main", "dubble", "vega", "antares", "rigel"],
        )
        self.assertTrue(config["agents"]["list"][0]["default"])
        self.assertNotIn("channels", config)
        self.assertNotIn("bindings", config)
        self.assertNotIn("cron", config)


if __name__ == "__main__":
    unittest.main()
