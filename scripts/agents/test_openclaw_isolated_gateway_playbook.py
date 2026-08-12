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
ACCESS_CHECK_PATH = Path(__file__).parent / "openclaw-access-check"


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
        cls.access_check = ACCESS_CHECK_PATH.read_text(encoding="utf-8")

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

    def test_static_security_failure_reports_only_safe_classifications(self) -> None:
        run_audit = self.playbook.index(
            "- name: Run static isolated Gateway security audit"
        )
        classify = self.playbook.index(
            "- name: Classify safe isolated Gateway static audit findings"
        )
        report = self.playbook.index(
            "- name: Report isolated Gateway static security finding classifications"
        )
        gate = self.playbook.index(
            "- name: Require clean static isolated Gateway security policy"
        )
        self.assertLess(run_audit, classify)
        self.assertLess(classify, report)
        self.assertLess(report, gate)
        classify_task = self.task(
            "Classify safe isolated Gateway static audit findings"
        )
        self.assertIn("'checkId': item.checkId", classify_task)
        self.assertIn("'severity': item.severity", classify_task)
        self.assertIn("'title': item.title", classify_task)
        self.assertNotIn("item.detail", classify_task)
        self.assertNotIn("item.remediation", classify_task)
        self.assertIn("no_log: true", classify_task)

    def test_deep_security_failure_reports_only_safe_classifications(self) -> None:
        run_audit = self.playbook.index(
            "- name: Run deep isolated Gateway security audit"
        )
        classify = self.playbook.index(
            "- name: Classify safe isolated Gateway deep audit findings"
        )
        report = self.playbook.index(
            "- name: Report isolated Gateway deep security finding classifications"
        )
        gate = self.playbook.index(
            "- name: Require clean deep isolated Gateway security audit"
        )
        self.assertLess(run_audit, classify)
        self.assertLess(classify, report)
        self.assertLess(report, gate)
        classify_task = self.task("Classify safe isolated Gateway deep audit findings")
        self.assertIn("'checkId': item.checkId", classify_task)
        self.assertIn("'severity': item.severity", classify_task)
        self.assertIn("'title': item.title", classify_task)
        self.assertNotIn("item.detail", classify_task)
        self.assertNotIn("item.remediation", classify_task)
        self.assertIn("no_log: true", classify_task)

    def test_deep_probe_uses_native_read_only_device_pairing(self) -> None:
        runtime = self.playbook.index(
            "- name: Require trusted Codex runtime and durable ownership records"
        )
        pairing = self.playbook.index(
            "- name: Bootstrap native read-only CLI device authentication"
        )
        auth_gate = self.playbook.index(
            "- name: Require native read-only CLI device authentication boundary"
        )
        deep = self.playbook.index("- name: Run deep isolated Gateway security audit")
        self.assertLess(runtime, pairing)
        self.assertLess(pairing, auth_gate)
        self.assertLess(auth_gate, deep)

        resolution = self.task("Require pairing proxy hostname to remain host-local")
        self.assertIn("openclaw_isolated_gateway_pairing_proxy_bind", resolution)
        proxy = self.task("Start one-shot isolated Gateway pairing proxy")
        self.assertIn("127.0.0.1:{{ openclaw_isolated_gateway_port }}", proxy)
        self.assertIn("NoNewPrivileges=yes", proxy)
        self.assertIn("CapabilityBoundingSet=", proxy)
        listener = self.task("Observe one-shot isolated Gateway pairing proxy listener")
        self.assertIn("/usr/bin/ss", listener)
        self.assertIn("-ltn4", listener)
        self.assertNotIn("wait_for", listener)
        cleanup = self.task("Stop one-shot isolated Gateway pairing proxy")
        self.assertIn("state: stopped", cleanup)
        self.assertIn("failed_when: false", cleanup)

        create = self.task(
            "Create native least-privilege CLI pairing without exposing token"
        )
        self.assertIn("ansible.builtin.command", create)
        self.assertIn("stdin: |", create)
        self.assertIn('OPENCLAW_GATEWAY_TOKEN="$(', create)
        self.assertNotIn("--token", create)
        self.assertIn("gateway call health --json", create)
        self.assertIn("no_log: true", create)

        metadata = self.task("Inspect native CLI device authentication metadata")
        self.assertIn("operatorTokenPresent", metadata)
        self.assertIn("operatorScopes", metadata)
        self.assertNotIn("token:", metadata)
        gate = self.task("Require native read-only CLI device authentication boundary")
        self.assertIn("operatorScopes == ['operator.read']", gate)
        self.assertIn("stat.mode", gate)
        self.assertIn("'0600'", gate)

        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_pairing_proxy_bind"],
            "127.0.1.1",
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_pairing_proxy_host"],
            "jn-t14s-lin",
        )
        self.assertNotIn(
            self.inventory["openclaw_isolated_gateway_pairing_proxy_port"],
            {
                self.inventory["openclaw_isolated_gateway_port"],
                self.inventory["openclaw_isolated_codex_port"],
            },
        )

    def test_config_read_warning_has_independent_boundary_gates(self) -> None:
        self.assertNotIn('"security"', self.config_template)
        group_gate = self.task(
            "Require exclusive isolated Gateway config-reading group"
        )
        self.assertIn("== [openclaw_isolated_gateway_user]", group_gate)
        config_gate = self.task(
            "Require root-managed read-only isolated Gateway configuration"
        )
        self.assertIn("stat.mode == '0640'", config_gate)
        self.assertIn("stat.pw_name == 'root'", config_gate)
        self.assertIn("openclaw_isolated_gateway_group", config_gate)
        audit_gate = self.task("Require clean static isolated Gateway security policy")
        self.assertIn("suppressedFindings", audit_gate)
        self.assertIn("fs.config.perms_group_readable", audit_gate)
        self.assertIn("== 1", audit_gate)
        self.assertIn("== 0", audit_gate)

    def test_recursive_cleanup_does_not_emit_dependency_tree_diffs(self) -> None:
        for name in (
            "Remove generated plugin-code remnants before native install",
            "Remove native plugin convergence scratch state",
            "Remove failed isolated Gateway managed paths before rollback",
        ):
            self.assertIn("diff: false", self.task(name))

    def test_gateway_reads_plugins_through_primary_group_after_cleanup(self) -> None:
        freeze = self.task("Freeze native managed-plugin code against service writes")
        self.assertIn('group: "{{ openclaw_isolated_gateway_group }}"', freeze)
        self.assertNotIn("openclaw_isolated_runtime_group", self.playbook)
        cleanup = self.playbook.index(
            "- name: Remove native plugin convergence scratch state"
        )
        read_gate = self.playbook.index(
            "- name: Prove isolated Gateway can read frozen native plugin manifest"
        )
        service = self.playbook.index(
            "- name: Restart isolated Gateway from converged immutable release"
        )
        self.assertLess(cleanup, read_gate)
        self.assertLess(read_gate, service)
        probe = self.task(
            "Prove isolated Gateway can read frozen native plugin manifest"
        )
        self.assertIn("runuser", probe)
        self.assertIn("openclaw.plugin.json", probe)

    def test_workspace_root_uses_dedicated_read_only_sharing_group(self) -> None:
        directory_task = self.task("Create isolated Gateway directories")
        self.assertIn("owner: root", directory_task)
        self.assertIn(
            'group: "{{ openclaw_isolated_workspace_group }}"', directory_task
        )
        self.assertIn('mode: "0750"', directory_task)
        self.assertEqual(
            self.inventory["openclaw_isolated_workspace_group"],
            "openclaw-workspace",
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_supplementary_groups"],
            ["openclaw-workspace"],
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_codex_supplementary_groups"],
            ["openclaw-workspace"],
        )
        self.assertNotEqual(
            self.inventory["openclaw_isolated_workspace_group"],
            self.inventory["openclaw_isolated_gateway_group"],
        )
        self.assertNotEqual(
            self.inventory["openclaw_isolated_workspace_group"],
            self.inventory["openclaw_isolated_codex_group"],
        )
        self.assertIn("UMask=0027", self.codex_service_template)
        self.assertIn(
            "ExecStartPre={{ openclaw_isolated_access_check_path }} -x "
            "{{ openclaw_isolated_gateway_workspace_dir }}",
            self.codex_service_template,
        )
        self.assertIn(
            "ExecStartPre={{ openclaw_isolated_access_check_path }} ! -w "
            "{{ openclaw_isolated_gateway_workspace_dir }}",
            self.codex_service_template,
        )
        self.assertNotIn("/usr/bin/test", self.codex_service_template)
        self.assertNotIn("/usr/bin/test", self.service_template)

        membership_gate = self.task("Wait for isolated service group memberships")
        self.assertIn("until:", membership_gate)
        self.assertIn("item.groups", membership_gate)

    def test_codex_filesystem_boundaries_are_independently_diagnosed(self) -> None:
        source_gate = self.task("Prove root-managed Codex runtime source exists")
        self.assertIn("@openai/codex/bin/codex.js", source_gate)
        self.assertNotIn("runuser", source_gate)
        task = self.task("Prove isolated Codex executor filesystem boundaries")
        self.assertNotIn("/usr/bin/bash", task)
        self.assertNotIn("&&", task)
        self.assertIn("openclaw_isolated_access_check_path", task)
        for label in (
            "Gateway-owned Codex runtime source is unreadable",
            "Gateway-owned provider source is immutable",
            "isolated Codex runtime mirror is readable",
            "isolated Codex runtime mirror is immutable",
            "shared workspace is readable",
            "shared workspace root is immutable",
            "Gateway secrets are unreadable",
            "Gateway config is unreadable",
            "Docker socket is unreadable",
            "legacy human home is not traversable",
        ):
            self.assertIn(f"label: {label}", task)
        self.assertIn('label: "{{ item.label }}"', task)
        self.assertIn(
            'label: Gateway-owned Codex runtime source is unreadable\n              argv:\n                - "!"\n                - -r',
            task,
        )

    def test_access_checker_is_constrained_and_deployed_before_boundaries(self) -> None:
        self.assertIn('builtin test "$@"', self.access_check)
        self.assertIn('[[ "$1" == "-r"', self.access_check)
        self.assertNotIn("eval", self.access_check)
        install = self.playbook.index(
            "- name: Install supplementary-group-aware access checker"
        )
        boundary = self.playbook.index(
            "- name: Prove isolated Codex executor filesystem boundaries"
        )
        service = self.playbook.index(
            "- name: Restart isolated Codex executor from frozen provider package"
        )
        self.assertLess(install, boundary)
        self.assertLess(install, service)
        self.assertEqual(
            self.inventory["openclaw_isolated_access_check_path"],
            "/usr/local/libexec/openclaw-isolated/openclaw-access-check",
        )

    def test_codex_runtime_mirror_is_atomic_and_content_verified(self) -> None:
        stage = self.playbook.index(
            "- name: Stage exact isolated Codex runtime dependency tree"
        )
        verify = self.playbook.index(
            "- name: Require exact isolated Codex runtime mirror content"
        )
        remove = self.playbook.index(
            "- name: Remove prior isolated Codex runtime mirror"
        )
        promote = self.playbook.index(
            "- name: Promote isolated Codex runtime mirror atomically"
        )
        service = self.playbook.index(
            "- name: Restart isolated Codex executor from frozen provider package"
        )
        self.assertLess(stage, verify)
        self.assertLess(verify, remove)
        self.assertLess(remove, promote)
        self.assertLess(promote, service)
        self.assertIn(
            "--no-dereference",
            self.task("Require exact isolated Codex runtime mirror content"),
        )

    def test_rollback_reports_preflight_status_before_cleanup(self) -> None:
        inspect = self.playbook.index(
            "- name: Inspect failed isolated service preflight statuses"
        )
        report = self.playbook.index(
            "- name: Report failed isolated service preflight statuses"
        )
        stop = self.playbook.index("- name: Stop failed isolated Gateway canary")
        cleanup = self.playbook.index(
            "- name: Remove failed isolated Gateway managed paths before rollback"
        )
        self.assertLess(inspect, report)
        self.assertLess(report, stop)
        self.assertLess(stop, cleanup)
        task = self.task("Inspect failed isolated service preflight statuses")
        self.assertIn("--property=ExecStartPre", task)
        self.assertIn("failed_when: false", task)

    def test_canary_disables_channels_and_scheduler(self) -> None:
        self.assertIn("Environment=OPENCLAW_SKIP_CHANNELS=1", self.service_template)
        self.assertIn("Environment=OPENCLAW_SKIP_CRON=1", self.service_template)
        self.assertIn('"every": "0m"', self.config_template)
        self.assertIn('"target": "none"', self.config_template)
        self.assertIs(self.inventory["openclaw_isolated_gateway_skip_cron"], True)

    def test_codex_executor_has_only_workspace_supplementary_group(self) -> None:
        self.assertEqual(
            self.inventory["openclaw_isolated_codex_supplementary_groups"],
            ["openclaw-workspace"],
        )
        gate = self.task("Reject supplementary isolated Codex executor privileges")
        self.assertIn("openclaw_isolated_codex_supplementary_groups", gate)
        self.assertIn("data-only workspace group", gate)

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
            openclaw_isolated_gateway_supplementary_groups=["openclaw-workspace"],
            openclaw_isolated_access_check_path=(
                "/usr/local/libexec/openclaw-isolated/openclaw-access-check"
            ),
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
            openclaw_isolated_codex_supplementary_groups=["openclaw-workspace"],
            openclaw_isolated_access_check_path=(
                "/usr/local/libexec/openclaw-isolated/openclaw-access-check"
            ),
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
            openclaw_isolated_codex_supplementary_groups=["openclaw-workspace"],
            openclaw_isolated_access_check_path=(
                "/usr/local/libexec/openclaw-isolated/openclaw-access-check"
            ),
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
        self.assertNotIn("BindReadOnlyPaths=", self.codex_service_template)
        self.assertIn(
            "ReadOnlyPaths={{ openclaw_isolated_codex_runtime_dir }}",
            self.codex_service_template,
        )
        self.assertIn(
            "TemporaryFileSystem={{ openclaw_isolated_gateway_state_dir }}:ro",
            self.codex_service_template,
        )
        self.assertNotIn(
            "InaccessiblePaths=-{{ openclaw_isolated_gateway_config_dir }} "
            "-{{ openclaw_isolated_gateway_state_dir }}",
            self.codex_service_template,
        )
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
