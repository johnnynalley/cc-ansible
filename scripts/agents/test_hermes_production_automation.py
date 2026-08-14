#!/usr/bin/env python3
"""Structural acceptance tests for production Hermes automation."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class ProductionAutomationTests(unittest.TestCase):
    def test_manifest_is_bounded_and_uses_fixed_delivery(self):
        source = (
            ROOT / "templates/hermes/astra-production-jobs.json.j2"
        ).read_text()
        value = json.loads(source)
        jobs = value["jobs"]
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["profile"], "astra")
        self.assertEqual(len(jobs), 7)
        self.assertEqual(len({job["key"] for job in jobs}), len(jobs))
        self.assertEqual(
            {job["deliver"] for job in jobs},
            {
                "discord:{{ hermes_automation_rigel_channel_id }}",
                "discord:{{ hermes_automation_logs_channel_id }}",
                "discord:{{ hermes_automation_social_channel_id }}",
            },
        )
        self.assertIsNone(re.search(r"[0-9]{17,20}", source))
        self.assertNotIn("heartbeat", " ".join(job["key"] for job in jobs))

    def test_every_historical_schedule_has_a_final_disposition(self):
        design = json.loads(
            (ROOT / "files/hermes/automation-contract.json").read_text()
        )
        production = json.loads(
            (
                ROOT
                / "files/hermes/production-automation-reconciliation.json"
            ).read_text()
        )
        source_ids = {row["id"] for row in design["schedules"]}
        self.assertEqual(set(production["lanes"]), source_ids)
        self.assertEqual(production["source"]["totalReconciledLanes"], 31)
        self.assertEqual(production["production"]["nativeCronJobs"], 7)
        self.assertEqual(
            production["pendingOneShots"]["cron-warframe-reminder-snootydeath"][
                "sourceDueAt"
            ],
            "2026-08-17T00:00:00Z",
        )

    def test_playbook_has_approval_backup_health_and_rescue_gates(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        for required in (
            "hermes_automation_required_confirmation",
            "Require the OpenClaw scheduler and delivery path offline",
            "Create targeted pre-automation rollback directory",
            "Normalize existing native profile backup locks",
            "Create private native profile backup staging directories",
            "Preserve native profile backups in the rollback directory",
            "Require unique rollback paths inside approved roots",
            "Resolve the managed Hermes Python prerequisite",
            "Hash bounded Hermes policy and environment",
            "Deploy bounded Hermes policy checksum manifests",
            "Deploy exact native Gateway update sudoers bridge",
            "Deploy Astra production cron manifest",
            "Verify zero Astra cron drift through the native API",
            "Require Health receiver continuity",
            "Stop available Hermes automation timers before restore",
            "Exclude existing timers from the automation transaction",
            "Recheck native updater workers after timer exclusion",
            "Restore pre-transaction timer state",
            "Stop after read-only Hermes automation check-mode preflight",
        ):
            self.assertIn(required, text)
        self.assertIn("managed-policy.sha256", text)
        self.assertIn("/usr/sbin/runuser", text)
        self.assertIn('"HERMES_HOME={{ item.home }}"', text)
        self.assertNotIn('become_user: "{{ item.user }}"', text)
        self.assertIn("/.backup.lock", text)
        self.assertIn("ansible.builtin.template", text)
        self.assertIn("templates/hermes", text)

    def test_native_update_exception_remains_exactly_scoped(self):
        text = (ROOT / "templates/hermes/hermes-native-update.service.j2").read_text()
        self.assertIn("NoNewPrivileges=false", text)
        self.assertNotIn("/usr/bin/sudo", text)
        self.assertIn("hermes update --gateway --yes", text)
        self.assertNotIn("RestrictSUIDSGID=true", text)
        self.assertIn("CapabilityBoundingSet=CAP_SETUID CAP_SETGID", text)
        self.assertIn("AmbientCapabilities=", text)

    def test_snap_exception_is_public_fetch_only(self):
        fetch = (
            ROOT / "templates/hermes/hermes-fortnite-calendar-fetch.service.j2"
        ).read_text()
        apply = (
            ROOT / "templates/hermes/hermes-fortnite-calendar.service.j2"
        ).read_text()
        self.assertIn("NoNewPrivileges=false", fetch)
        self.assertIn("PYTHONNOUSERSITE=1", fetch)
        self.assertIn("hermes_fortnite_calendar_fetch_live", fetch)
        self.assertNotIn("legacy_workspace", fetch)
        self.assertNotIn("source_env", fetch)
        self.assertIn("NoNewPrivileges=true", apply)
        self.assertIn("hermes-fortnite-calendar-fetch.service", apply)
        self.assertIn("--schedule-file", apply)

    def test_gateway_policy_serializes_cron_and_suppresses_progress(self):
        text = (ROOT / "templates/hermes/hermes-managed-config.yaml.j2").read_text()
        self.assertIn("max_parallel_jobs: 1", text)
        self.assertIn('tool_progress: "off"', text)
        self.assertIn("progress_notices: false", text)
        self.assertIn("background_process_notifications: error", text)

    def test_gateway_uses_live_manifest_instead_of_design_contract(self):
        base = (ROOT / "templates/hermes/hermes-gateway.service.j2").read_text()
        dropin = (
            ROOT
            / "templates/hermes/hermes-gateway-astra-automation.conf.j2"
        ).read_text()
        self.assertNotIn("hermes_automation_audit_live", base)
        self.assertIn("hermes_cron_reconcile_live", dropin)
        self.assertIn("--check", dropin)
        self.assertIn("hermes_automation_manifest_live", dropin)

    def test_retained_collector_has_no_conflicting_workspace_mount(self):
        text = (
            ROOT / "templates/hermes/hermes-retained-automation@.service.j2"
        ).read_text()
        self.assertIn("ProtectHome=tmpfs", text)
        self.assertIn(
            "BindReadOnlyPaths={{ hermes_automation_legacy_workspace }}/scripts",
            text,
        )
        self.assertIn(
            "BindPaths={{ hermes_automation_legacy_workspace }}/fortnite-progress",
            text,
        )
        readwrite = next(
            line for line in text.splitlines() if line.startswith("ReadWritePaths=")
        )
        self.assertNotIn("hermes_automation_legacy_workspace", readwrite)
        self.assertNotIn("ProtectHome=read-only", text)

    def test_convergence_does_not_execute_user_workflows(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        for forbidden in (
            "Run retained Daily Summary collection once",
            "Run retained Fortnite progress collection once",
            "Run verified Warframe feed collection once",
            "Run validated Fortnite calendar transaction once",
            "retained-automation-state.tar.gz",
        ):
            self.assertNotIn(forbidden, text)

    def test_rescue_is_not_best_effort(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        rescue = text.split("      rescue:", 1)[1]
        self.assertNotIn("failed_when: false", rescue)

    def test_all_user_home_collectors_use_explicit_bind_allowlists(self):
        for name in (
            "hermes-retained-automation@.service.j2",
            "hermes-warframe-feed.service.j2",
            "hermes-fortnite-calendar.service.j2",
            "hermes-fortnite-calendar-fetch.service.j2",
        ):
            text = (ROOT / "templates" / "hermes" / name).read_text()
            self.assertIn("ProtectHome=tmpfs", text, name)
            self.assertNotIn("ProtectHome=read-only", text, name)

    def test_unsafe_legacy_update_collector_is_not_invoked(self):
        text = (ROOT / "scripts/agents/hermes-retained-automation.py").read_text()
        self.assertNotIn("daily_updates_collect.py", text)
        self.assertNotIn("shell=True", text)

    def test_no_custom_discord_publisher_or_thread_archiver(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        variables = (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        self.assertNotIn("discord-thread-archive", playbook)
        self.assertNotIn("discord_thread_archive", variables)
        self.assertNotIn("message queue", playbook.casefold())


if __name__ == "__main__":
    unittest.main()
